#!/usr/local/bin/python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Bring the NemoClaw Hermes dashboard and API out of the OpenShell sandbox.

The NemoClaw CLI runs ``openshell forward start`` on a workstation so the
Hermes dashboard (port 18789) and OpenAI-compatible API (port 8642) become
reachable on loopback. On Kubernetes there is no workstation next to the
gateway, so this relay performs the equivalent step inside the cluster:

* ``serve`` supervises one ``openshell forward service`` process per port.
  The forward is a gateway gRPC stream to the loopback listener inside the
  sandbox network namespace; no SSH client, socat, or custom image is needed.
* ``gateway-token`` prints Hermes' ``API_SERVER_KEY`` exactly like
  ``nemohermes <sandbox> gateway-token --quiet`` does, by reading the
  sandbox-owned ``.env`` through the authenticated exec API.
* ``status`` prints the OpenShell sandbox phase for ``nemohermes <name> status``
  parity.

The relay authenticates with a projected ServiceAccount token that carries only
the OpenShell user audience. It refuses lifecycle admin tokens and never
receives model or messaging credentials.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import urlparse


CLI = "/tools/openshell"
FORWARD_RESTART_DELAY_SECONDS = 3
TOKEN_REFRESH_MARGIN_SECONDS = 120
POLL_INTERVAL_SECONDS = 5
# Written once gateway credentials are staged. The Deployment readiness probe
# checks this file rather than the forward listener because the listener can
# only bind after the post-install bootstrap hook has created the sandbox; a
# listener-based probe would deadlock `helm install --wait`.
READY_MARKER = Path("/tmp/access-relay.ready")


def atomic_private_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(value)
    temporary.chmod(0o600)
    temporary.replace(path)


def atomic_private_json(path: Path, value: dict[str, object]) -> None:
    atomic_private_bytes(path, (json.dumps(value, sort_keys=True) + "\n").encode())


def log(message: str) -> None:
    print(f"[access-relay] {message}", flush=True)


def stage_client_tls() -> None:
    """Copy the gateway CA and client certificate into the CLI registry."""
    source = Path(os.environ["OPENSHELL_CLIENT_TLS_SOURCE"])
    source_root = source.resolve(strict=True)
    destination = (
        Path(os.environ["XDG_CONFIG_HOME"])
        / "openshell"
        / "gateways"
        / os.environ["OPENSHELL_GATEWAY"]
        / "mtls"
    )
    for name in ("ca.crt", "tls.crt", "tls.key"):
        try:
            resolved = (source / name).resolve(strict=True)
            resolved.relative_to(source_root)
        except (FileNotFoundError, RuntimeError, ValueError) as error:
            raise SystemExit(f"client TLS file {name} escapes its mounted Secret") from error
        data = resolved.read_bytes()
        if not data or len(data) > 1024 * 1024:
            raise SystemExit(f"client TLS file {name} has an invalid size")
        atomic_private_bytes(destination / name, data)


def jwt_claims(token: str) -> dict[str, object]:
    try:
        encoded = token.split(".", 2)[1]
        padded = encoded + "=" * (-len(encoded) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (IndexError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit("projected access relay token is not a valid JWT") from error
    if not isinstance(claims, dict):
        raise SystemExit("projected access relay JWT claims must be an object")
    return claims


def validate_token(
    token: str,
    *,
    issuer: str,
    audience: str,
    admin_role: str,
    subject: str,
) -> int:
    """Reject a token that is stale, misbound, or carries lifecycle admin power."""
    claims = jwt_claims(token)
    token_audience = claims.get("aud", [])
    if isinstance(token_audience, str):
        token_audience = [token_audience]
    if not isinstance(token_audience, list) or any(not isinstance(item, str) for item in token_audience):
        raise SystemExit("projected access relay token audiences are invalid")
    if admin_role in token_audience:
        raise SystemExit("access relay token must not contain the OpenShell admin role")
    if set(token_audience) != {audience}:
        raise SystemExit("access relay token must contain only the OpenShell user audience")
    if claims.get("iss") != issuer:
        raise SystemExit("access relay token issuer does not match the configured OIDC issuer")
    if claims.get("sub") != subject:
        raise SystemExit("access relay token subject does not match its ServiceAccount")
    expires_at = claims.get("exp")
    if not isinstance(expires_at, int) or expires_at <= int(time.time()) + 60:
        raise SystemExit("access relay token is expired or too close to expiry")
    return expires_at


def read_projected_token() -> str:
    token_path = Path(os.environ["OPENSHELL_SERVICE_ACCOUNT_TOKEN"])
    token_root = token_path.parent.resolve(strict=True)
    try:
        resolved = token_path.resolve(strict=True)
        resolved.relative_to(token_root)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        raise SystemExit("projected access relay token escapes its mounted volume") from error
    token = resolved.read_text(encoding="utf-8").strip()
    if not token or len(token) > 1024 * 1024:
        raise SystemExit("projected access relay token has an invalid size")
    return token


def configure_cli_authentication() -> int:
    """Write the OIDC bearer credential for the released CLI and return its expiry."""
    token = read_projected_token()
    issuer = os.environ["OPENSHELL_OIDC_ISSUER"]
    audience = os.environ["OPENSHELL_OIDC_AUDIENCE"]
    expires_at = validate_token(
        token,
        issuer=issuer,
        audience=audience,
        admin_role=os.environ["OPENSHELL_OIDC_ADMIN_ROLE"],
        subject=os.environ["OPENSHELL_OIDC_SUBJECT"],
    )
    gateway = os.environ["OPENSHELL_GATEWAY"]
    endpoint = os.environ["OPENSHELL_GATEWAY_ENDPOINT"]
    directory = Path(os.environ["XDG_CONFIG_HOME"]) / "openshell" / "gateways" / gateway
    parsed = urlparse(endpoint)
    atomic_private_json(
        directory / "metadata.json",
        {
            "name": gateway,
            "gateway_endpoint": endpoint,
            "is_remote": False,
            "gateway_port": parsed.port or 443,
            "auth_mode": "oidc",
            "oidc_issuer": issuer,
            "oidc_client_id": "openshell-access-relay",
            "oidc_audience": audience,
        },
    )
    atomic_private_json(
        directory / "oidc_token.json",
        {
            "access_token": token,
            "expires_at": expires_at,
            "issuer": issuer,
            "client_id": "openshell-access-relay",
        },
    )
    return expires_at


def run_cli(arguments: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [CLI, *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=timeout,
    )


def sandbox_phase() -> str:
    result = run_cli(
        ["sandbox", "get", os.environ["OPENSHELL_SANDBOX_NAME"], "--output", "json"],
        timeout=60,
    )
    if result.returncode != 0:
        return ""
    try:
        return str(json.loads(result.stdout).get("phase", "")).lower()
    except json.JSONDecodeError:
        return ""


def wait_for_sandbox() -> None:
    announced = False
    while True:
        if sandbox_phase() in {"ready", "running"}:
            return
        if not announced:
            log("waiting for the OpenShell-managed Hermes sandbox to become ready")
            announced = True
        time.sleep(POLL_INTERVAL_SECONDS)


def parse_forwards() -> list[tuple[str, int]]:
    """Parse ``name=port,name=port`` into validated (name, port) pairs."""
    forwards: list[tuple[str, int]] = []
    seen_ports: set[int] = set()
    for item in filter(None, (part.strip() for part in os.environ.get("ACCESS_FORWARDS", "").split(","))):
        name, separator, raw_port = item.partition("=")
        if not separator or not name.isidentifier():
            raise SystemExit(f"invalid ACCESS_FORWARDS entry: {item}")
        try:
            port = int(raw_port)
        except ValueError as error:
            raise SystemExit(f"invalid ACCESS_FORWARDS port: {item}") from error
        if port < 1024 or port > 65535 or port in seen_ports:
            raise SystemExit(f"ACCESS_FORWARDS port must be unique and between 1024 and 65535: {item}")
        seen_ports.add(port)
        forwards.append((name, port))
    if not forwards:
        raise SystemExit("ACCESS_FORWARDS must list at least one name=port forward")
    return forwards


def forward_command(port: int) -> list[str]:
    bind = os.environ.get("ACCESS_BIND", "0.0.0.0")
    return [
        CLI,
        "forward",
        "service",
        os.environ["OPENSHELL_SANDBOX_NAME"],
        "--target-port",
        str(port),
        "--target-host",
        "127.0.0.1",
        "--local",
        f"{bind}:{port}",
    ]


class ForwardSupervisor:
    """Keep one gRPC service forward alive per configured port."""

    def __init__(self, forwards: list[tuple[str, int]]) -> None:
        self.forwards = forwards
        self.children: dict[int, subprocess.Popen[bytes]] = {}
        self.stopping = False

    def start(self, name: str, port: int) -> None:
        log(f"starting {name} forward on 0.0.0.0:{port} -> sandbox 127.0.0.1:{port}")
        self.children[port] = subprocess.Popen(  # noqa: S603 - fixed argv from chart values.
            forward_command(port),
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
        )

    def start_all(self) -> None:
        for name, port in self.forwards:
            if port not in self.children:
                self.start(name, port)

    def stop_all(self, reason: str) -> None:
        if not self.children:
            return
        log(f"stopping forwards: {reason}")
        for child in self.children.values():
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + 10
        for child in self.children.values():
            remaining = max(0.1, deadline - time.monotonic())
            try:
                child.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        self.children.clear()

    def reap_exited(self) -> list[tuple[str, int, int]]:
        exited: list[tuple[str, int, int]] = []
        for name, port in self.forwards:
            child = self.children.get(port)
            if child is not None and child.poll() is not None:
                exited.append((name, port, child.returncode))
                del self.children[port]
        return exited

    def request_stop(self, *_: object) -> None:
        self.stopping = True


def serve() -> int:
    forwards = parse_forwards()
    stage_client_tls()
    expires_at = configure_cli_authentication()
    supervisor = ForwardSupervisor(forwards)
    signal.signal(signal.SIGTERM, supervisor.request_stop)
    signal.signal(signal.SIGINT, supervisor.request_stop)
    READY_MARKER.write_text("staged\n", encoding="utf-8")
    log(
        "credentials staged; forwards for "
        + ", ".join(f"{name}:{port}" for name, port in forwards)
        + " bind once the sandbox is Ready"
    )

    wait_for_sandbox()
    supervisor.start_all()
    while not supervisor.stopping:
        time.sleep(1)
        if supervisor.stopping:
            break
        # The kubelet rotates the projected token before it expires. Reload it
        # and restart the forwards ahead of expiry so the long-lived gRPC
        # streams never run on a stale credential.
        if int(time.time()) >= expires_at - TOKEN_REFRESH_MARGIN_SECONDS:
            new_expiry = None
            try:
                new_expiry = configure_cli_authentication()
            except SystemExit as error:
                log(f"token refresh not yet possible: {error}")
            if new_expiry and new_expiry != expires_at:
                expires_at = new_expiry
                supervisor.stop_all("credential rotation")
                wait_for_sandbox()
                supervisor.start_all()
                continue
        for name, port, status in supervisor.reap_exited():
            log(f"{name} forward on port {port} exited with status {status}; restarting")
            time.sleep(FORWARD_RESTART_DELAY_SECONDS)
            wait_for_sandbox()
            if not supervisor.stopping:
                supervisor.start(name, port)
    supervisor.stop_all("shutdown requested")
    return 0


def exec_in_sandbox(script: str, *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return run_cli(
        [
            "sandbox",
            "exec",
            "--name",
            os.environ["OPENSHELL_SANDBOX_NAME"],
            "--timeout",
            str(timeout),
            "--no-tty",
            "--",
            "sh",
            "-lc",
            script,
        ],
        timeout=timeout + 30,
    )


def gateway_token() -> int:
    """Print the Hermes API bearer key the same way ``nemohermes gateway-token`` does."""
    stage_client_tls()
    configure_cli_authentication()
    pattern = r"^[[:space:]]*(export[[:space:]]+)?API_SERVER_KEY="
    script = (
        "f=/sandbox/.hermes/.env; [ -f \"$f\" ] || exit 3; "
        f"grep -m1 -E '{pattern}' \"$f\" 2>/dev/null | sed -E 's/{pattern}//'"
    )
    result = exec_in_sandbox(script)
    if result.returncode == 3:
        print("Hermes has not minted its API key yet; retry after the sandbox finishes starting", file=sys.stderr)
        return 3
    if result.returncode != 0:
        print(result.stderr.strip() or "failed to read the Hermes API key", file=sys.stderr)
        return result.returncode or 1
    value = result.stdout.strip()
    if len(value) >= 2 and value[0] in {'"', "'"} and value[-1] == value[0]:
        value = value[1:-1]
    if not value:
        print("Hermes API key is empty; inspect the sandbox startup log", file=sys.stderr)
        return 1
    if "--quiet" not in sys.argv[2:]:
        print(
            "Warning: this bearer token grants access to the Hermes OpenAI-compatible API; do not share or log it.",
            file=sys.stderr,
        )
    print(value)
    return 0


def status() -> int:
    stage_client_tls()
    configure_cli_authentication()
    result = run_cli(["sandbox", "get", os.environ["OPENSHELL_SANDBOX_NAME"], "--output", "json"], timeout=60)
    if result.returncode != 0:
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
        return result.returncode or 1
    print(result.stdout, end="")
    return 0


COMMANDS = {
    "serve": serve,
    "gateway-token": gateway_token,
    "status": status,
}


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "serve"
    handler = COMMANDS.get(command)
    if handler is None:
        raise SystemExit(f"usage: {sys.argv[0]} [serve|gateway-token [--quiet]|status]")
    raise SystemExit(handler())


if __name__ == "__main__":
    main()
