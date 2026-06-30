#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Serve the financial UI and proxy chat to the local Hermes gateway."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "ui" / "dist"
HERMES_URL = "http://127.0.0.1:8642"
PHOENIX_GRAPHQL_URL = os.environ.get(
    "FINANCE_PHOENIX_GRAPHQL_URL", "http://127.0.0.1:6006/graphql"
)
MODEL = os.environ.get("FINANCE_MODEL", "financial-assistant")
HERMES_TOKEN = os.environ.get("FINANCE_HERMES_TOKEN", "")
REQUEST_LIMIT = 2 * 1024 * 1024
QUOTE_TTL_SECONDS = 25
QUOTE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
YAHOO_CHART_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1m"
)


class DemoServer(ThreadingHTTPServer):
    daemon_threads = True


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(DIST_DIR), **kwargs)

    def end_headers(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path in {"/", "/index.html", "/config", "/health"} or path.endswith(
            (".js", ".css")
        ):
            self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path == "/health":
            self._json({"status": "ok", "service": "financial-assistant-ui"})
        elif path == "/config":
            self._json({"model": MODEL})
        elif path == "/api/quotes":
            self._quotes()
        elif path == "/api/phoenix/recent":
            self._phoenix_recent()
        else:
            super().do_GET()

    def do_POST(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path == "/v1/chat/completions":
            self._proxy_chat()
        else:
            self.send_error(404)

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _quotes(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        raw_symbols = query.get("symbols", ["NVDA,MSFT,AAPL"])[0]
        symbols = []
        for candidate in raw_symbols.replace(";", ",").split(","):
            symbol = candidate.strip().upper()
            if symbol and re.fullmatch(r"[A-Z0-9.^-]{1,12}", symbol):
                symbols.append(symbol)
        symbols = symbols[:8]
        if not symbols:
            self._json({"ok": False, "error": "No valid symbols provided"}, 400)
            return
        self._json(
            {
                "ok": True,
                "source": "Yahoo Finance chart API",
                "quotes": [fetch_quote(symbol) for symbol in symbols],
            }
        )

    def _phoenix_recent(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        since = query.get("since", [""])[0]
        try:
            spans = fetch_recent_phoenix_spans(since=since)
            self._json({"ok": True, "spans": spans})
        except Exception as exc:  # Phoenix must not take down chat.
            self._json(
                {
                    "ok": False,
                    "spans": [],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    def _proxy_chat(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json({"error": {"message": "Invalid request length"}}, 400)
            return
        if length <= 0 or length > REQUEST_LIMIT:
            self._json({"error": {"message": "Invalid request size"}}, 413)
            return

        request = urllib.request.Request(
            f"{HERMES_URL}/v1/chat/completions",
            data=self.rfile.read(length),
            headers={
                "Authorization": f"Bearer {HERMES_TOKEN}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream, application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=360) as response:
                self._relay(response)
        except urllib.error.HTTPError as exc:
            self._relay_http_error(exc)
        except (TimeoutError, urllib.error.URLError, ConnectionError) as exc:
            self._json(
                {
                    "error": {
                        "message": f"Hermes is unavailable: {exc.reason if isinstance(exc, urllib.error.URLError) else exc}",
                        "type": type(exc).__name__,
                    }
                },
                502,
            )

    def _relay(self, response: Any) -> None:
        content_type = response.headers.get("Content-Type", "application/json")
        self.send_response(response.status)
        self.send_header("Content-Type", content_type)
        if "text/event-stream" in content_type:
            self.send_header("Cache-Control", "no-cache, no-store")
            self.end_headers()
            try:
                while chunk := response.read(4096):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        else:
            data = response.read()
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def _relay_http_error(self, exc: urllib.error.HTTPError) -> None:
        data = exc.read()
        self.send_response(exc.code)
        self.send_header(
            "Content-Type", exc.headers.get("Content-Type", "application/json")
        )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def fetch_quote(symbol: str) -> dict[str, Any]:
    now = time.time()
    cached = QUOTE_CACHE.get(symbol)
    if cached and now - cached[0] < QUOTE_TTL_SECONDS:
        return cached[1]

    try:
        request = urllib.request.Request(
            YAHOO_CHART_URL.format(symbol=symbol),
            headers={"User-Agent": "NemoHermes financial assistant demo"},
        )
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.load(response)
        result = payload["chart"]["result"][0]
        meta = result.get("meta", {})
        price = meta.get("regularMarketPrice")
        previous = meta.get("chartPreviousClose") or meta.get("previousClose")
        change_percent = None
        if (
            isinstance(price, (int, float))
            and isinstance(previous, (int, float))
            and previous
        ):
            change_percent = ((price - previous) / previous) * 100
        quote = {
            "symbol": symbol,
            "ok": True,
            "price": price,
            "change_percent": change_percent,
            "currency": meta.get("currency", "USD"),
            "exchange": meta.get("exchangeName") or meta.get("fullExchangeName"),
            "market_state": meta.get("marketState"),
            "as_of": meta.get("regularMarketTime"),
        }
    except (KeyError, IndexError, TypeError, urllib.error.URLError) as exc:
        quote = {"symbol": symbol, "ok": False, "error": type(exc).__name__}

    QUOTE_CACHE[symbol] = (now, quote)
    return quote


def fetch_recent_phoenix_spans(
    *, since: str = "", limit: int = 16
) -> list[dict[str, Any]]:
    query = """
    {
      projects {
        edges {
          node {
            name
            spans(first: 500) {
              edges {
                node {
                  name
                  spanKind
                  statusCode
                  startTime
                  spanId
                  parentId
                  trace { traceId }
                }
              }
            }
          }
        }
      }
    }
    """
    request = urllib.request.Request(
        PHOENIX_GRAPHQL_URL,
        data=json.dumps({"query": query}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError(payload["errors"][0].get("message", "Phoenix query failed"))

    projects = payload.get("data", {}).get("projects", {}).get("edges", [])
    target_projects = [
        edge
        for edge in projects
        if edge.get("node", {}).get("name") == "financial-assistant-agent"
    ] or projects
    since_time = parse_timestamp(since)
    spans: list[dict[str, Any]] = []
    for project_edge in target_projects:
        for span_edge in project_edge.get("node", {}).get("spans", {}).get("edges", []):
            node = span_edge.get("node", {})
            started_at = node.get("startTime") or ""
            if (
                since_time
                and (
                    parse_timestamp(started_at)
                    or datetime.min.replace(tzinfo=timezone.utc)
                )
                < since_time
            ):
                continue
            trace_id = node.get("trace", {}).get("traceId") or ""
            spans.append(
                {
                    "name": node.get("name") or "unnamed",
                    "kind": str(node.get("spanKind") or "unknown").lower(),
                    "status": node.get("statusCode") or "UNSET",
                    "trace_id": trace_id[-12:] if trace_id else "",
                    "span_id": (node.get("spanId") or "")[-12:],
                    "parent_id": (node.get("parentId") or "")[-12:],
                    "started_at": started_at,
                }
            )

    spans.sort(key=lambda item: item["started_at"], reverse=True)
    return select_trace_rows(spans, limit)


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def select_trace_rows(spans: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected = spans[:limit]
    if any(span["kind"] == "tool" for span in selected):
        return selected
    tool = next((span for span in spans[limit:] if span["kind"] == "tool"), None)
    if tool and selected:
        selected[-1] = tool
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()

    if not DIST_DIR.is_dir():
        parser.error(f"UI build not found at {DIST_DIR}; run npm run build")
    if not HERMES_TOKEN:
        parser.error("FINANCE_HERMES_TOKEN is required")

    server = DemoServer((args.host, args.port), Handler)
    print(
        f"Financial assistant UI listening on http://{args.host}:{args.port}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
