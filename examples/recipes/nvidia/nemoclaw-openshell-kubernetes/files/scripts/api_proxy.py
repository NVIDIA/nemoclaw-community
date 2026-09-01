# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Bearer-authenticated, method-bounded proxy to the in-cluster Kubernetes API."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import secrets
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import Request, urlopen


UPSTREAM = "https://kubernetes.default.svc"
SERVICE_ACCOUNT_TOKEN = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
SERVICE_ACCOUNT_CA = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
DEFAULT_CLIENT_TOKEN = Path("/proxy-auth/token")
ALLOWED_PATH_ROOTS = ("/api", "/apis", "/version", "/healthz", "/livez", "/readyz")


def read_bounded(path: Path, maximum: int = 4096) -> str:
    """Read a small token file without accepting empty or oversized content."""
    data = path.read_bytes()
    if not data or len(data) > maximum:
        raise ValueError(f"invalid token file: {path}")
    value = data.decode("utf-8").strip()
    if not value:
        raise ValueError(f"empty token file: {path}")
    return value


def is_authorized(header: str | None, token_path: Path = DEFAULT_CLIENT_TOKEN) -> bool:
    """Compare the caller's bearer credential with the mounted client token."""
    if not header or not header.startswith("Bearer "):
        return False
    supplied = header.removeprefix("Bearer ").strip()
    if not supplied:
        return False
    try:
        expected = read_bounded(token_path)
    except (OSError, UnicodeError, ValueError):
        return False
    return secrets.compare_digest(supplied, expected)


def validate_request_target(raw_target: str) -> str:
    """Accept only relative Kubernetes API paths and preserve a safe query string."""
    parsed = urlsplit(raw_target)
    if parsed.scheme or parsed.netloc or parsed.fragment or not parsed.path.startswith("/"):
        raise ValueError("request target must be an absolute Kubernetes API path")
    if parsed.path.startswith("//"):
        raise ValueError("network-path references are forbidden")
    decoded_segments = unquote(parsed.path).split("/")
    if any(segment in {".", ".."} for segment in decoded_segments):
        raise ValueError("dot path segments are forbidden")
    if not any(parsed.path == root or parsed.path.startswith(f"{root}/") for root in ALLOWED_PATH_ROOTS):
        raise ValueError("request target is outside the Kubernetes API")
    return urlunsplit(("", "", parsed.path, parsed.query, ""))


class ProxyHandler(BaseHTTPRequestHandler):
    """Authenticate the sandbox client, then use the proxy ServiceAccount upstream."""

    server_version = "NemoClawKubernetesProxy/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        """Avoid logging resource names, query strings, or caller-supplied data."""

    def send_payload(self, status: int, payload: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def reject(self, status: int, message: str) -> None:
        payload = (f'{{"error":"{message}"}}\n').encode("utf-8")
        self.send_payload(status, payload)

    def request_body(self) -> bytes | None:
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("transfer-encoded request bodies are not supported")
        length_text = self.headers.get("Content-Length")
        if length_text is None:
            return None
        try:
            length = int(length_text)
        except ValueError as error:
            raise ValueError("invalid Content-Length") from error
        maximum = int(os.environ.get("PROXY_MAX_REQUEST_BYTES", "10485760"))
        if length < 0 or length > maximum:
            raise ValueError("request body exceeds the configured limit")
        return self.rfile.read(length) if length else None

    def proxy(self) -> None:
        token_path = Path(os.environ.get("PROXY_CLIENT_TOKEN_FILE", str(DEFAULT_CLIENT_TOKEN)))
        if not is_authorized(self.headers.get("Authorization"), token_path):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Bearer realm="nemoclaw-kubernetes-proxy"')
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        allowed_methods = {
            method.strip().upper()
            for method in os.environ.get("PROXY_ALLOWED_METHODS", "GET").split(",")
            if method.strip()
        }
        if self.command not in allowed_methods:
            self.reject(405, "method_not_allowed")
            return

        try:
            target = validate_request_target(self.path)
            body = self.request_body()
            service_account_token = read_bounded(SERVICE_ACCOUNT_TOKEN, maximum=16384)
        except (OSError, UnicodeError, ValueError):
            self.reject(400, "invalid_request")
            return

        headers = {
            "Authorization": f"Bearer {service_account_token}",
            "Accept": self.headers.get("Accept", "application/json"),
        }
        if self.headers.get("Content-Type"):
            headers["Content-Type"] = self.headers["Content-Type"]
        request = Request(UPSTREAM + target, data=body, headers=headers, method=self.command)
        context = ssl.create_default_context(cafile=SERVICE_ACCOUNT_CA)
        timeout = int(os.environ.get("PROXY_REQUEST_TIMEOUT_SECONDS", "30"))
        maximum_response = int(os.environ.get("PROXY_MAX_RESPONSE_BYTES", "33554432"))

        try:
            upstream = urlopen(request, context=context, timeout=timeout)  # noqa: S310 - fixed upstream.
        except HTTPError as error:
            upstream = error
        except (OSError, URLError, ValueError):
            self.reject(502, "upstream_unavailable")
            return

        with upstream:
            payload = upstream.read(maximum_response + 1)
            if len(payload) > maximum_response:
                self.reject(502, "upstream_response_too_large")
                return
            content_type = upstream.headers.get("Content-Type", "application/json")
            self.send_payload(upstream.status, payload, content_type)

    do_GET = proxy
    do_POST = proxy
    do_PUT = proxy
    do_PATCH = proxy
    do_DELETE = proxy


def main() -> None:
    """Start a thread-per-request proxy; Kubernetes readiness is handled externally."""
    read_bounded(Path(os.environ.get("PROXY_CLIENT_TOKEN_FILE", str(DEFAULT_CLIENT_TOKEN))))
    read_bounded(SERVICE_ACCOUNT_TOKEN, maximum=16384)
    port = int(os.environ.get("PROXY_PORT", "8001"))
    server = ThreadingHTTPServer(("0.0.0.0", port), ProxyHandler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
