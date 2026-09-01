# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Idempotently configure OpenShell and create the pinned Hermes sandbox."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse


CLI = "/tools/openshell"
CONFIG = json.loads(Path("/runtime/bootstrap-config.json").read_text(encoding="utf-8"))


def atomic_private_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(value)
    temporary.chmod(0o600)
    temporary.replace(path)


def atomic_private_json(path: Path, value: dict[str, object]) -> None:
    """Write CLI authentication state without leaving a partially written token."""
    atomic_private_bytes(path, (json.dumps(value, sort_keys=True) + "\n").encode())


def stage_client_tls() -> None:
    """Copy the three projected TLS files into the UID-writable CLI registry."""
    source = Path(os.environ["OPENSHELL_CLIENT_TLS_SOURCE"])
    source_root = source.resolve(strict=True)
    gateway_name = os.environ["OPENSHELL_GATEWAY"]
    destination = Path(os.environ["XDG_CONFIG_HOME"]) / "openshell" / "gateways" / gateway_name / "mtls"
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
    """Decode untrusted claims for local consistency checks; the gateway verifies the signature."""
    try:
        encoded = token.split(".", 2)[1]
        padded = encoded + "=" * (-len(encoded) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (IndexError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit("projected ServiceAccount token is not a valid JWT") from error
    if not isinstance(claims, dict):
        raise SystemExit("projected ServiceAccount JWT claims must be an object")
    return claims


def configure_cli_authentication() -> None:
    """Configure the released CLI for either OIDC bearer auth or operator mTLS."""
    mode = os.environ.get("OPENSHELL_BOOTSTRAP_AUTH_MODE", "clientTLS")
    if mode == "clientTLS":
        return
    if mode != "serviceAccountToken":
        raise SystemExit(f"unsupported OpenShell bootstrap authentication mode: {mode}")

    token_path = Path(os.environ["OPENSHELL_SERVICE_ACCOUNT_TOKEN"])
    token_root = token_path.parent.resolve(strict=True)
    try:
        resolved_token_path = token_path.resolve(strict=True)
        resolved_token_path.relative_to(token_root)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        raise SystemExit("projected ServiceAccount token escapes its mounted volume") from error
    if not resolved_token_path.is_file():
        raise SystemExit("projected ServiceAccount token path is invalid")
    token = resolved_token_path.read_text(encoding="utf-8").strip()
    if not token or len(token) > 1024 * 1024:
        raise SystemExit("projected ServiceAccount token has an invalid size")

    issuer = os.environ["OPENSHELL_OIDC_ISSUER"]
    audience = os.environ["OPENSHELL_OIDC_AUDIENCE"]
    namespace = os.environ["POD_NAMESPACE"]
    service_account = os.environ["POD_SERVICE_ACCOUNT"]
    claims = jwt_claims(token)
    token_audience = claims.get("aud", [])
    if isinstance(token_audience, str):
        token_audience = [token_audience]
    expected_subject = f"system:serviceaccount:{namespace}:{service_account}"
    if claims.get("iss") != issuer:
        raise SystemExit("projected ServiceAccount token issuer does not match openshell.server.oidc.issuer")
    if audience not in token_audience:
        raise SystemExit("projected ServiceAccount token audience does not match openshell.server.oidc.audience")
    if claims.get("sub") != expected_subject:
        raise SystemExit("projected ServiceAccount token subject does not match the lifecycle ServiceAccount")
    expires_at = claims.get("exp")
    if not isinstance(expires_at, int) or expires_at <= int(time.time()) + 60:
        raise SystemExit("projected ServiceAccount token is expired or too close to expiry")

    gateway_name = os.environ["OPENSHELL_GATEWAY"]
    endpoint = os.environ["OPENSHELL_GATEWAY_ENDPOINT"]
    gateway_directory = Path(os.environ["XDG_CONFIG_HOME"]) / "openshell" / "gateways" / gateway_name
    parsed = urlparse(endpoint)
    atomic_private_json(
        gateway_directory / "metadata.json",
        {
            "name": gateway_name,
            "gateway_endpoint": endpoint,
            "is_remote": False,
            "gateway_port": parsed.port or 443,
            "auth_mode": "oidc",
            "oidc_issuer": issuer,
            "oidc_client_id": "openshell-bootstrap",
            "oidc_audience": audience,
        },
    )
    atomic_private_json(
        gateway_directory / "oidc_token.json",
        {
            "access_token": token,
            "expires_at": expires_at,
            "issuer": issuer,
            "client_id": "openshell-bootstrap",
        },
    )


def run(arguments: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [CLI, *arguments],
        check=check,
        text=True,
        capture_output=capture,
        env=os.environ.copy(),
    )


def wait_for_gateway() -> None:
    deadline = time.monotonic() + 300
    last_error = ""
    while time.monotonic() < deadline:
        result = run(["provider", "list"], check=False, capture=True)
        if result.returncode == 0:
            return
        last_error = (result.stderr or result.stdout).strip()[-1000:]
        time.sleep(5)
    raise SystemExit(f"OpenShell gateway was not ready: {last_error}")


def reconcile_provider() -> None:
    name = CONFIG["model"]["providerName"]
    common = ["--credential", "OPENAI_API_KEY", "--config", f"OPENAI_BASE_URL={CONFIG['model']['baseUrl']}"]
    existing = run(["provider", "get", name], check=False, capture=True)
    if existing.returncode == 0:
        run(["provider", "update", name, *common])
    else:
        run(["provider", "create", "--name", name, "--type", CONFIG["model"]["providerType"], *common])

    inference = [
        "inference",
        "set",
        "--provider",
        name,
        "--model",
        CONFIG["model"]["name"],
        "--timeout",
        str(CONFIG["model"]["requestTimeoutSeconds"]),
    ]
    if not CONFIG["model"]["verifyEndpoint"]:
        inference.append("--no-verify")
    run(inference)


def verify_existing_sandbox() -> bool:
    result = run(["sandbox", "get", CONFIG["sandboxName"], "--output", "json"], check=False, capture=True)
    if result.returncode != 0:
        return False
    detail = json.loads(result.stdout)
    labels = detail.get("labels") or {}
    required = CONFIG["labels"]
    if any(labels.get(key) != value for key, value in required.items()):
        raise SystemExit(
            f"sandbox {CONFIG['sandboxName']} already exists but does not match this exact chart/image/security configuration; "
            "delete it explicitly after reviewing persisted state, then rerun the Helm upgrade"
        )
    if str(detail.get("phase", "")).lower() in {"failed", "deleted"}:
        raise SystemExit(f"owned sandbox {CONFIG['sandboxName']} is in terminal phase {detail.get('phase')}")
    print(f"owned sandbox {CONFIG['sandboxName']} already exists; leaving it unchanged")
    return True


def create_sandbox() -> None:
    sandbox = CONFIG["sandbox"]
    arguments = [
        "sandbox",
        "create",
        "--name",
        CONFIG["sandboxName"],
        "--from",
        CONFIG["agentImage"],
        "--policy",
        "/runtime/policy.yaml",
        "--driver-config-json",
        json.dumps(CONFIG["driverConfig"], separators=(",", ":"), sort_keys=True),
        "--cpu",
        str(sandbox["cpu"]),
        "--memory",
        str(sandbox["memory"]),
        "--approval-mode",
        "manual",
        "--no-auto-providers",
        "--detach",
        "--no-tty",
    ]
    # Inference credentials remain gateway-side. The provider is selected by
    # `openshell inference set` and reached through inference.local; attaching
    # it here would expose or withhold provider credentials as sandbox env.
    for key, value in sorted(CONFIG["labels"].items()):
        arguments.extend(["--label", f"{key}={value}"])

    runtime_env = {
        "NEMOCLAW_SANDBOX_NAME": CONFIG["sandboxName"],
        "NEMOCLAW_MODEL": CONFIG["model"]["name"],
        "NEMOCLAW_INFERENCE_PROVIDER_ID": "custom",
        "NEMOCLAW_UPSTREAM_PROVIDER": CONFIG["model"]["providerName"],
        "NEMOCLAW_INFERENCE_BASE_URL": "https://inference.local/v1",
        "NEMOCLAW_INFERENCE_API": CONFIG["model"]["api"],
        "NEMOCLAW_CONTEXT_WINDOW": str(CONFIG["model"]["contextWindow"]),
        **CONFIG["agentEnv"],
    }
    for key, value in sorted(runtime_env.items()):
        arguments.extend(["--env", f"{key}={value}"])
    # The managed image ships /sandbox and /sandbox/.hermes with set-id modes
    # for its root-separated container topology. OpenShell's injected-UID mode
    # chowns those paths but intentionally preserves mode bits; NemoClaw's own
    # boundary validator then rejects that mixed posture. Normalize only these
    # immutable image roots after refusing symlinks. `exec` is load-bearing:
    # nemoclaw-start must replace the transient shell and remain the
    # supervisor's exact direct child for its fail-closed process attestation.
    startup = (
        "set -eu; "
        "test -d /sandbox && test ! -L /sandbox && "
        "test -d /sandbox/.hermes && test ! -L /sandbox/.hermes && "
        "/usr/bin/chmod u=rwx,g=rwx,o=,g-s,o-t /sandbox && "
        "/usr/bin/chmod u=rwx,g=,o=,g-s,o-t /sandbox/.hermes && "
        "exec /usr/local/bin/nemoclaw-start"
    )
    arguments.extend(["--", "/bin/sh", "-c", startup])
    run(arguments)


def main() -> None:
    stage_client_tls()
    configure_cli_authentication()
    wait_for_gateway()
    existing_sandbox = verify_existing_sandbox()
    # Ownership is checked before provider mutation so an accidental explicit
    # name collision on a shared gateway fails without changing another
    # release's inference configuration.
    reconcile_provider()
    if not existing_sandbox:
        create_sandbox()
        print(f"created sandbox {CONFIG['sandboxName']} from immutable image {CONFIG['agentImage']}")


if __name__ == "__main__":
    main()
