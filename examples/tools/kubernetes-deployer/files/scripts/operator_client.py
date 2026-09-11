#!/usr/local/bin/python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run an attach-only Hermes terminal through OpenShell's authenticated exec API."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlparse


CLI = "/tools/openshell"


def atomic_private_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(value)
    temporary.chmod(0o600)
    temporary.replace(path)


def atomic_private_json(path: Path, value: dict[str, object]) -> None:
    atomic_private_bytes(path, (json.dumps(value, sort_keys=True) + "\n").encode())


def stage_client_tls() -> None:
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
        raise SystemExit("projected operator client token is not a valid JWT") from error
    if not isinstance(claims, dict):
        raise SystemExit("projected operator client JWT claims must be an object")
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
        raise SystemExit("projected operator client token audiences are invalid")
    if admin_role in token_audience:
        raise SystemExit("operator client token must not contain the OpenShell admin role")
    if set(token_audience) != {audience}:
        raise SystemExit("operator client token must contain only the OpenShell user audience")
    if claims.get("iss") != issuer:
        raise SystemExit("operator client token issuer does not match the configured OIDC issuer")
    if claims.get("sub") != subject:
        raise SystemExit("operator client token subject does not match its ServiceAccount")
    expires_at = claims.get("exp")
    if not isinstance(expires_at, int) or expires_at <= int(time.time()) + 60:
        raise SystemExit("operator client token is expired or too close to expiry")
    return expires_at


def configure_cli_authentication() -> None:
    token_path = Path(os.environ["OPENSHELL_SERVICE_ACCOUNT_TOKEN"])
    token_root = token_path.parent.resolve(strict=True)
    try:
        resolved = token_path.resolve(strict=True)
        resolved.relative_to(token_root)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        raise SystemExit("projected operator client token escapes its mounted volume") from error
    token = resolved.read_text(encoding="utf-8").strip()
    if not token or len(token) > 1024 * 1024:
        raise SystemExit("projected operator client token has an invalid size")

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
            "oidc_client_id": "openshell-operator-client",
            "oidc_audience": audience,
        },
    )
    atomic_private_json(
        directory / "oidc_token.json",
        {
            "access_token": token,
            "expires_at": expires_at,
            "issuer": issuer,
            "client_id": "openshell-operator-client",
        },
    )


def hermes_command(arguments: list[str]) -> list[str]:
    command = [
        CLI,
        "sandbox",
        "exec",
        "--name",
        os.environ["OPENSHELL_SANDBOX_NAME"],
        "--workdir",
        "/sandbox/workspace",
        "--timeout",
        "0",
        "--no-tty" if "--oneshot" in arguments else "--tty",
        "--",
        "hermes",
    ]
    for skill in filter(None, (item.strip() for item in os.environ.get("HERMES_SKILLS", "").split(","))):
        command.extend(["--skills", skill])
    command.extend(arguments)
    return command


def wait_for_sandbox() -> None:
    while True:
        result = subprocess.run(
            [CLI, "sandbox", "get", os.environ["OPENSHELL_SANDBOX_NAME"], "--output", "json"],
            check=False,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        if result.returncode == 0:
            try:
                phase = str(json.loads(result.stdout).get("phase", "")).lower()
            except json.JSONDecodeError:
                phase = ""
            if phase in {"ready", "running"}:
                return
        print("waiting for the OpenShell-managed Hermes sandbox", flush=True)
        time.sleep(5)


def run_session(arguments: list[str]) -> int:
    stage_client_tls()
    configure_cli_authentication()
    wait_for_sandbox()
    return subprocess.run(hermes_command(arguments), check=False, env=os.environ.copy()).returncode


def main() -> None:
    arguments = sys.argv[1:]
    if arguments:
        raise SystemExit(run_session(arguments))
    while True:
        result = run_session([])
        print(f"Hermes session ended with status {result}; starting a fresh session", flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
