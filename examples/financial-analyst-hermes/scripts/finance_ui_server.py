#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Serve the finance UI and proxy browser chat requests to Hermes.

This helper is intentionally small. It is not an agent runtime, a tracing
exporter, or a skill runner. Hermes owns skills and LLM calls; the NeMo Relay
sidecar owns trace forwarding. This process only serves static files and avoids
browser CORS problems by forwarding /v1/* to the local Hermes API.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from urllib.parse import urlsplit
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "ui"
DIST_DIR = UI_DIR / "dist"
STATIC_DIR = DIST_DIR if DIST_DIR.exists() else UI_DIR
YAHOO_CHART_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1m"
)

PROXY_BASE_URL = ""
PROXY_TIMEOUT = 240
PROXY_AUTH_ENV = ""
PROXY_API_KEY = ""
CHAT_MODEL = "financial-assistant"
UPSTREAM_LABEL = "Compatible API"
PHOENIX_GRAPHQL_URL = "http://127.0.0.1:6006/graphql"
QUOTE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
QUOTE_TTL_SECONDS = 25


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, X-Finance-Channel, X-Finance-Run-Id",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        clean_path = urlsplit(self.path).path
        if clean_path in {
            "/",
            "/index.html",
            "/config",
            "/health",
        } or clean_path.endswith((".js", ".css")):
            self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        clean_path = urlsplit(self.path).path
        if clean_path == "/health":
            self._json(
                {
                    "status": "ok",
                    "platform": "finance-ui",
                    "upstream": PROXY_BASE_URL or None,
                    "model": CHAT_MODEL,
                    "static_dir": str(STATIC_DIR),
                }
            )
            return
        if clean_path == "/config":
            self._json({"model": CHAT_MODEL, "upstream_label": UPSTREAM_LABEL})
            return
        if clean_path == "/api/quotes":
            self._quotes()
            return
        if clean_path == "/api/phoenix/recent":
            self._phoenix_recent()
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path.startswith("/v1/"):
            self._proxy()
            return
        self.send_error(404)

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _quotes(self) -> None:
        query = urlsplit(self.path).query
        params = dict(part.split("=", 1) for part in query.split("&") if "=" in part)
        raw_symbols = params.get("symbols", "NVDA,MSFT,AAPL")
        symbols = [
            symbol.strip().upper()
            for symbol in raw_symbols.replace(";", ",").split(",")
            if symbol.strip()
        ][:8]
        if not symbols:
            self._json({"ok": False, "error": "No symbols provided"}, status=400)
            return
        self._json(
            {
                "ok": True,
                "source": "yahoo-finance-chart-json",
                "quotes": [fetch_quote(symbol) for symbol in symbols],
            }
        )

    def _phoenix_recent(self) -> None:
        try:
            self._json({"ok": True, "spans": fetch_recent_phoenix_spans()})
        except Exception as exc:
            self._json(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "spans": [],
                },
                status=200,
            )

    def _proxy(self) -> None:
        if not PROXY_BASE_URL:
            self._json(
                {
                    "error": {
                        "message": "The UI server needs --api-url pointing at the Hermes /v1 endpoint.",
                        "type": "configuration_error",
                    }
                },
                status=503,
            )
            return

        target = f"{PROXY_BASE_URL.rstrip('/')}{self.path}"
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        headers = self._upstream_headers()
        req = urllib.request.Request(
            target, data=body, headers=headers, method=self.command
        )

        try:
            with urllib.request.urlopen(req, timeout=PROXY_TIMEOUT) as response:
                self._relay_response(response)
        except urllib.error.HTTPError as exc:
            self._relay_error(exc)
        except Exception as exc:
            self._json(
                {"error": {"message": str(exc), "type": type(exc).__name__}}, status=502
            )

    def _upstream_headers(self) -> dict[str, str]:
        skip = {
            "host",
            "content-length",
            "origin",
            "referer",
            "sec-fetch-dest",
            "sec-fetch-mode",
            "sec-fetch-site",
        }
        headers = {
            key: value for key, value in self.headers.items() if key.lower() not in skip
        }
        if "Authorization" not in headers:
            token = PROXY_API_KEY or (
                os.environ.get(PROXY_AUTH_ENV, "") if PROXY_AUTH_ENV else ""
            )
            if token:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    def _relay_response(self, response: Any) -> None:
        content_type = response.headers.get("Content-Type", "application/json")
        self.send_response(response.status)
        self.send_header("Content-Type", content_type)

        if "text/event-stream" in content_type:
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            while True:
                chunk = response.read(4096)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
            return

        data = response.read()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _relay_error(self, exc: urllib.error.HTTPError) -> None:
        data = exc.read()
        self.send_response(exc.code)
        self.send_header(
            "Content-Type", exc.headers.get("Content-Type", "application/json")
        )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    global \
        PROXY_BASE_URL, \
        PROXY_TIMEOUT, \
        PROXY_AUTH_ENV, \
        PROXY_API_KEY, \
        CHAT_MODEL, \
        UPSTREAM_LABEL, \
        PHOENIX_GRAPHQL_URL

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--api-url",
        dest="proxy_base_url",
        default=os.environ.get(
            "FINANCE_API_URL", os.environ.get("OPENAI_BASE_URL", "")
        ),
        help="proxy /v1/* to an OpenAI-compatible API URL, e.g. http://127.0.0.1:8642",
    )
    parser.add_argument("--proxy-timeout", type=int, default=240)
    parser.add_argument(
        "--api-key",
        default=os.environ.get("FINANCE_API_KEY", os.environ.get("OPENAI_API_KEY", "")),
        help="upstream bearer token to inject server-side; never sent to the browser",
    )
    parser.add_argument(
        "--auth-env",
        default="",
        help="environment variable containing an upstream bearer token to inject server-side",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get(
            "FINANCE_MODEL", os.environ.get("OPENAI_MODEL", CHAT_MODEL)
        ),
        help="model name sent by the browser client in chat completions requests",
    )
    parser.add_argument(
        "--upstream-label",
        default=os.environ.get("FINANCE_UPSTREAM_LABEL", UPSTREAM_LABEL),
        help="short non-secret label shown in the UI header",
    )
    parser.add_argument(
        "--phoenix-url",
        default=os.environ.get("FINANCE_PHOENIX_GRAPHQL_URL", PHOENIX_GRAPHQL_URL),
        help="Phoenix GraphQL endpoint used for read-only recent span display",
    )
    parser.add_argument(
        "--env-file",
        default="",
        help="optional dotenv file to load before starting the UI server",
    )
    args = parser.parse_args()

    if args.env_file:
        load_env_file(Path(args.env_file))

    PROXY_BASE_URL = args.proxy_base_url
    PROXY_TIMEOUT = args.proxy_timeout
    PROXY_AUTH_ENV = args.auth_env
    PROXY_API_KEY = args.api_key
    CHAT_MODEL = args.model
    UPSTREAM_LABEL = args.upstream_label
    PHOENIX_GRAPHQL_URL = args.phoenix_url

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    mode = (
        f"proxying Hermes at {PROXY_BASE_URL}"
        if PROXY_BASE_URL
        else "waiting for --api-url"
    )
    print(f"Serving finance UI at http://{args.host}:{args.port} ({mode})", flush=True)
    server.serve_forever()
    return 0


def fetch_recent_phoenix_spans(limit: int = 12) -> list[dict[str, Any]]:
    query = """
    {
      projects {
        edges {
          node {
            name
            spans(first: 1000) {
              edges {
                node {
                  name
                  spanKind
                  statusCode
                  startTime
                  trace { traceId }
                }
              }
            }
          }
        }
      }
    }
    """
    req = urllib.request.Request(
        PHOENIX_GRAPHQL_URL,
        data=json.dumps({"query": query}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        payload = json.load(response)

    spans: list[dict[str, Any]] = []
    for project_edge in payload.get("data", {}).get("projects", {}).get("edges", []):
        project = project_edge.get("node", {})
        project_name = project.get("name") or "default"
        for span_edge in project.get("spans", {}).get("edges", []):
            node = span_edge.get("node", {})
            name = node.get("name") or "unnamed"
            kind = str(node.get("spanKind") or "unknown").lower()
            if not should_show_span(project_name, name, kind):
                continue
            trace_id = node.get("trace", {}).get("traceId") or ""
            spans.append(
                {
                    "project": project_name,
                    "name": name,
                    "kind": kind,
                    "status": node.get("statusCode") or "UNSET",
                    "trace_id": trace_id[-8:] if trace_id else "",
                    "started_at": node.get("startTime") or "",
                }
            )

    spans.sort(key=lambda item: item.get("started_at") or "", reverse=True)
    return select_trace_rows(spans, limit)


def select_trace_rows(spans: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add(span: dict[str, Any]) -> None:
        key = (
            str(span.get("project", "")),
            str(span.get("name", "")),
            str(span.get("kind", "")),
            str(span.get("trace_id", "")),
        )
        if key in seen or len(selected) >= limit:
            return
        seen.add(key)
        selected.append(span)

    for span in spans[: max(6, limit - 4)]:
        add(span)
    for span in spans:
        if span.get("kind") == "tool":
            add(span)
        if len(selected) >= limit:
            break
    for span in spans:
        add(span)
        if len(selected) >= limit:
            break

    return selected


def should_show_span(project: str, name: str, kind: str) -> bool:
    haystack = f"{project} {name} {kind}".lower()
    return any(
        token in haystack
        for token in (
            "financial",
            "finance",
            "relay",
            "market",
            "sec",
            "skill",
            "tool",
            "llm",
            "chat.completions",
            "terminal",
        )
    )


def load_env_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def fetch_quote(symbol: str) -> dict[str, Any]:
    now = time.time()
    cached = QUOTE_CACHE.get(symbol)
    if cached and now - cached[0] < QUOTE_TTL_SECONDS:
        return cached[1]

    quote: dict[str, Any] = {"symbol": symbol, "ok": False}
    try:
        req = urllib.request.Request(
            YAHOO_CHART_URL.format(symbol=symbol),
            headers={"User-Agent": "NemoHermes financial assistant demo"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            payload = json.load(response)
        result = payload.get("chart", {}).get("result", [{}])[0]
        meta = result.get("meta", {})
        price = meta.get("regularMarketPrice")
        previous = meta.get("chartPreviousClose") or meta.get("previousClose")
        change = None
        change_percent = None
        if (
            isinstance(price, (int, float))
            and isinstance(previous, (int, float))
            and previous
        ):
            change = price - previous
            change_percent = (change / previous) * 100
        quote = {
            "symbol": symbol,
            "ok": True,
            "price": price,
            "previous_close": previous,
            "change": change,
            "change_percent": change_percent,
            "currency": meta.get("currency", "USD"),
            "exchange": meta.get("exchangeName") or meta.get("fullExchangeName"),
            "market_state": meta.get("marketState"),
            "as_of": meta.get("regularMarketTime"),
        }
    except Exception as exc:
        quote = {"symbol": symbol, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

    QUOTE_CACHE[symbol] = (now, quote)
    return quote


if __name__ == "__main__":
    raise SystemExit(main())
