# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Bearer-authenticated, method-bounded proxy to the in-cluster Kubernetes API."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import Request, urlopen


UPSTREAM = "https://kubernetes.default.svc"
SERVICE_ACCOUNT_TOKEN = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
SERVICE_ACCOUNT_CA = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
DEFAULT_CLIENT_TOKEN = Path("/proxy-auth/token")
DEFAULT_TLS_CERTIFICATE = Path("/proxy-tls/tls.crt")
DEFAULT_TLS_PRIVATE_KEY = Path("/proxy-tls/tls.key")
ALLOWED_PATH_ROOTS = ("/api", "/apis", "/version", "/healthz", "/livez", "/readyz")


def decoded_path_segment(raw_segment: str) -> str:
    """Fully decode one bounded segment while forbidding structural changes."""
    decoded = raw_segment
    for _ in range(8):
        expanded = unquote(decoded)
        if expanded == decoded:
            break
        decoded = expanded
    else:
        raise ValueError("over-encoded path segment is forbidden")
    if decoded in {".", ".."}:
        raise ValueError("dot path segments are forbidden")
    if "/" in decoded or "\\" in decoded:
        raise ValueError("encoded path separators are forbidden")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in decoded):
        raise ValueError("control characters in path segments are forbidden")
    return decoded


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
    for raw_segment in parsed.path.split("/"):
        decoded_path_segment(raw_segment)
    if not any(parsed.path == root or parsed.path.startswith(f"{root}/") for root in ALLOWED_PATH_ROOTS):
        raise ValueError("request target is outside the Kubernetes API")
    return urlunsplit(("", "", parsed.path, parsed.query, ""))


def resource_target(
    target: str,
) -> tuple[str, str | None, str, str | None, str | None, tuple[str, ...]] | None:
    """Return API resource identity and any path below its subresource."""
    parts = [decoded_path_segment(part) for part in urlsplit(target).path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "api":
        api_group = ""
        cursor = 2
    elif len(parts) >= 3 and parts[0] == "apis":
        api_group = parts[1]
        cursor = 3
    else:
        return None
    # Kubernetes still accepts the legacy watch URL form where `watch`
    # appears between the API version and the resource path. Normalize it
    # before applying the resource/subresource deny rules so it cannot shift
    # `secrets`, service-account tokens, or pod exec into the name position.
    if cursor < len(parts) and parts[cursor] == "watch":
        cursor += 1
    if cursor >= len(parts):
        return None
    namespace = None
    if parts[cursor] == "namespaces":
        if cursor + 2 >= len(parts):
            return None
        namespace = parts[cursor + 1]
        cursor += 2
    resource = parts[cursor]
    name = parts[cursor + 1] if cursor + 1 < len(parts) else None
    subresource = parts[cursor + 2] if cursor + 2 < len(parts) else None
    tail = tuple(parts[cursor + 3 :])
    return api_group, namespace, resource, name, subresource, tail


def exact_delete_allowlist() -> set[tuple[str, str, str]]:
    """Load only exact apiGroup/resource/name tuples supplied by Helm."""
    try:
        entries = json.loads(os.environ.get("PROXY_DELETE_ALLOWED_RESOURCES", "[]"))
    except json.JSONDecodeError:
        return set()
    if not isinstance(entries, list):
        return set()
    allowed: set[tuple[str, str, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"apiGroup", "resource", "name"}:
            return set()
        values = (entry["apiGroup"], entry["resource"], entry["name"])
        if not all(isinstance(value, str) and value for value in values[1:]) or not isinstance(values[0], str):
            return set()
        allowed.add(values)
    return allowed


def request_allowed(target: str, method: str, policy: str) -> bool:
    """Enforce proxy-specific restrictions beyond Kubernetes RBAC."""
    try:
        target = validate_request_target(target)
    except ValueError:
        return False
    parsed = resource_target(target)
    method = method.upper()
    if policy == "exact-service-proxy":
        # The metrics kubeconfig points directly at this chart proxy. Accept
        # only the two Prometheus query endpoints and construct the fixed
        # upstream Service URL separately; never accept a caller-supplied
        # Service identity or host.
        path = urlsplit(target).path
        return method == "GET" and path in {"/api/v1/query", "/api/v1/query_range"}
    if policy == "exact-delete":
        if method != "DELETE" or parsed is None:
            return False
        api_group, namespace, resource, name, subresource, tail = parsed
        return bool(
            namespace
            and namespace == os.environ.get("PROXY_DELETE_NAMESPACE")
            and name
            and subresource is None
            and not tail
            and (api_group, resource, name) in exact_delete_allowlist()
        )
    if policy != "general":
        return False
    if parsed is None:
        return method == "GET"
    _api_group, namespace, resource, _name, subresource, _tail = parsed
    if resource == "secrets":
        return False
    if resource == "serviceaccounts" and subresource == "token":
        return False
    if resource == "pods" and subresource in {
        "attach",
        "ephemeralcontainers",
        "eviction",
        "exec",
        "portforward",
        "proxy",
    }:
        return False
    if resource == "nodes" and subresource == "proxy":
        return False
    if resource == "services" and subresource == "proxy":
        return bool(
            method in {"GET", "POST"}
            and namespace
            and namespace == os.environ.get("PROXY_SERVICE_PROXY_NAMESPACE")
        )
    return True


def direct_service_url(target: str) -> str:
    """Convert one allowlisted metrics path to a fixed in-cluster HTTPS Service."""
    if not request_allowed(target, "GET", "exact-service-proxy"):
        raise ValueError("service target is outside the exact allowlist")
    parsed_target = urlsplit(target)
    namespace = os.environ.get("PROXY_SERVICE_NAMESPACE", "")
    service = os.environ.get("PROXY_SERVICE_NAME", "")
    port_text = os.environ.get("PROXY_SERVICE_PORT", "")
    if (
        os.environ.get("PROXY_SERVICE_SCHEME", "https") != "https"
        or namespace is None
        or re.fullmatch(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?", namespace) is None
        or re.fullmatch(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?", service) is None
        or not port_text.isdigit()
        or not 1 <= int(port_text) <= 65535
    ):
        raise ValueError("invalid service target configuration")
    return urlunsplit(
        (
            "https",
            f"{service}.{namespace}.svc:{port_text}",
            parsed_target.path,
            parsed_target.query,
            "",
        )
    )


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
        # Rejections can happen before the request body is consumed. Closing
        # the connection prevents an unread body from being parsed as a second
        # HTTP request on a persistent connection.
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

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
            self.close_connection = True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Bearer realm="nemoclaw-kubernetes-proxy"')
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
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
            policy = os.environ.get("PROXY_POLICY", "general")
            if not request_allowed(target, self.command, policy):
                self.reject(403, "request_forbidden_by_proxy_policy")
                return
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
        if policy == "exact-service-proxy":
            try:
                upstream_url = direct_service_url(target)
            except ValueError:
                self.reject(400, "invalid_request")
                return
            upstream_ca = os.environ.get("PROXY_UPSTREAM_CA_FILE")
        else:
            upstream_url = UPSTREAM + target
            upstream_ca = SERVICE_ACCOUNT_CA
        request = Request(upstream_url, data=body, headers=headers, method=self.command)
        context = ssl.create_default_context(cafile=upstream_ca)
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
    """Start a TLS-only thread-per-request proxy."""
    read_bounded(Path(os.environ.get("PROXY_CLIENT_TOKEN_FILE", str(DEFAULT_CLIENT_TOKEN))))
    read_bounded(SERVICE_ACCOUNT_TOKEN, maximum=16384)
    certificate = Path(
        os.environ.get("PROXY_TLS_CERT_FILE", str(DEFAULT_TLS_CERTIFICATE))
    )
    private_key = Path(
        os.environ.get("PROXY_TLS_KEY_FILE", str(DEFAULT_TLS_PRIVATE_KEY))
    )
    if certificate.is_symlink() or private_key.is_symlink():
        # Kubernetes Secret keys are symlinks by design, so resolve and validate
        # that both files remain inside the mounted Secret directory.
        tls_root = certificate.parent.resolve(strict=True)
        certificate = certificate.resolve(strict=True)
        private_key = private_key.resolve(strict=True)
        if not certificate.is_relative_to(tls_root) or not private_key.is_relative_to(tls_root):
            raise SystemExit("invalid proxy TLS Secret projection")
    if not certificate.is_file() or not private_key.is_file():
        raise SystemExit("missing proxy TLS certificate")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=certificate, keyfile=private_key)
    port = int(os.environ.get("PROXY_PORT", "8001"))
    server = ThreadingHTTPServer(("0.0.0.0", port), ProxyHandler)
    server.daemon_threads = True
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
