# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Idempotently configure OpenShell and create the pinned Hermes sandbox."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import ssl
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


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


def read_bounded_projected_token(path_value: str, description: str) -> str:
    """Read one kubelet-projected token without following it outside its volume."""
    token_path = Path(path_value)
    token_root = token_path.parent.resolve(strict=True)
    try:
        resolved_token_path = token_path.resolve(strict=True)
        resolved_token_path.relative_to(token_root)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        raise SystemExit(f"{description} escapes its mounted volume") from error
    if not resolved_token_path.is_file():
        raise SystemExit(f"{description} path is invalid")
    token = resolved_token_path.read_text(encoding="utf-8").strip()
    if not token or len(token) > 1024 * 1024:
        raise SystemExit(f"{description} has an invalid size")
    return token


def anonymous_json(url: str, context: ssl.SSLContext, description: str) -> dict[str, object]:
    """Fetch one JSON document exactly the way the OpenShell gateway does: with no credentials."""
    if not url.startswith("https://"):
        raise SystemExit(f"{description} URL must use https://: {url}")
    # No Accept header: the Kubernetes JWKS endpoint serves application/jwk-set+json
    # and answers 406 to an application/json-only Accept, while the gateway's
    # own client sends no Accept header either.
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=30, context=context) as response:  # noqa: S310 - operator-configured issuer.
            body = response.read(1024 * 1024 + 1)
    except HTTPError as error:
        if error.code in {401, 403}:
            raise SystemExit(
                f"{description} at {url} returned HTTP {error.code} to an unauthenticated request. "
                "The OpenShell gateway fetches this endpoint without credentials, so authentication "
                "cannot initialize. Grant anonymous read access with "
                "platform.serviceAccountIssuerDiscovery.createPublicBinding=true and "
                "dangerousAcknowledgement=I_ACKNOWLEDGE_PUBLIC_OIDC_DISCOVERY (values-kubernetes.yaml "
                "or values-openshift.yaml), or point openshell.server.oidc.issuer at an issuer that "
                "publishes discovery and JWKS publicly"
            ) from error
        raise SystemExit(f"{description} at {url} returned HTTP {error.code}") from error
    except URLError as error:
        raise SystemExit(f"{description} at {url} is unreachable from the cluster: {error.reason}") from error
    if len(body) > 1024 * 1024:
        raise SystemExit(f"{description} at {url} exceeds 1 MiB")
    try:
        document = json.loads(body)
    except json.JSONDecodeError as error:
        raise SystemExit(f"{description} at {url} is not valid JSON") from error
    if not isinstance(document, dict):
        raise SystemExit(f"{description} at {url} must be a JSON object")
    return document


def verify_issuer_discovery() -> None:
    """Prove the gateway's anonymous OIDC discovery path before creating anything.

    OpenShell 0.0.116 resolves ``<issuer>/.well-known/openid-configuration`` and
    the advertised ``jwks_uri`` with an anonymous HTTP client. Standard Kubernetes
    serves neither endpoint to unauthenticated callers, so this check turns a
    silent gateway start-up failure into an actionable bootstrap error.
    """
    if os.environ.get("OPENSHELL_BOOTSTRAP_AUTH_MODE", "clientTLS") != "serviceAccountToken":
        return
    issuer = os.environ["OPENSHELL_OIDC_ISSUER"].rstrip("/")
    # The gateway trusts the system bundle plus kube-root-ca.crt (SSL_CERT_DIR).
    # JWKS may live on the external API endpoint whose certificate chains to a
    # different authority than the in-cluster service, so trust both here too.
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=os.environ["KUBERNETES_API_CA"])
    discovery = anonymous_json(f"{issuer}/.well-known/openid-configuration", context, "OIDC discovery document")
    advertised = str(discovery.get("issuer", "")).rstrip("/")
    if advertised != issuer:
        raise SystemExit(
            f"OIDC discovery advertises issuer {advertised!r} but openshell.server.oidc.issuer is {issuer!r}; "
            "the gateway compares these byte for byte and exits with 'OIDC discovery issuer mismatch'. "
            "OpenShift publishes the short in-cluster form while a default kubeadm cluster publishes the "
            "fully qualified one. Reinstall with "
            f"--set openshell.server.oidc.issuer={advertised}"
        )
    jwks_uri = discovery.get("jwks_uri")
    if not isinstance(jwks_uri, str) or not jwks_uri:
        raise SystemExit("OIDC discovery document does not advertise a jwks_uri")
    jwks = anonymous_json(jwks_uri, context, "OIDC JWKS")
    keys = jwks.get("keys")
    if not isinstance(keys, list) or not keys:
        raise SystemExit(f"OIDC JWKS at {jwks_uri} contains no signing keys")
    print(f"verified anonymous OIDC discovery for {issuer} ({len(keys)} signing key(s) at {jwks_uri})")


def request_admin_token() -> str:
    """Mint a Pod-bound, multi-audience token for lifecycle-only admin work."""
    api_token = read_bounded_projected_token(
        os.environ["KUBERNETES_API_TOKEN"],
        "projected Kubernetes API token",
    )
    namespace = os.environ["POD_NAMESPACE"]
    service_account = os.environ["POD_SERVICE_ACCOUNT"]
    audience = os.environ["OPENSHELL_OIDC_AUDIENCE"]
    admin_role = os.environ["OPENSHELL_OIDC_ADMIN_ROLE"]
    if not admin_role or admin_role == audience:
        raise SystemExit("OpenShell admin role must be non-empty and distinct from the user audience")

    host = os.environ["KUBERNETES_SERVICE_HOST"]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
    endpoint = (
        f"https://{host}:{port}/api/v1/namespaces/{quote(namespace, safe='')}"
        f"/serviceaccounts/{quote(service_account, safe='')}/token"
    )
    payload = json.dumps(
        {
            "apiVersion": "authentication.k8s.io/v1",
            "kind": "TokenRequest",
            "spec": {
                "audiences": [audience, admin_role],
                "expirationSeconds": int(os.environ["OPENSHELL_ADMIN_TOKEN_EXPIRATION_SECONDS"]),
                "boundObjectRef": {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "name": os.environ["POD_NAME"],
                    "uid": os.environ["POD_UID"],
                },
            },
        },
        separators=(",", ":"),
    ).encode()
    request = Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        },
    )
    context = ssl.create_default_context(cafile=os.environ["KUBERNETES_API_CA"])
    try:
        with urlopen(request, timeout=30, context=context) as response:  # noqa: S310 - fixed in-cluster API endpoint.
            body = response.read(1024 * 1024 + 1)
    except HTTPError as error:
        raise SystemExit(f"Kubernetes TokenRequest failed with HTTP {error.code}") from error
    except URLError as error:
        raise SystemExit("Kubernetes TokenRequest could not reach the API server") from error
    if len(body) > 1024 * 1024:
        raise SystemExit("Kubernetes TokenRequest response exceeds 1 MiB")
    try:
        token = json.loads(body)["status"]["token"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise SystemExit("Kubernetes TokenRequest returned an invalid response") from error
    if not isinstance(token, str) or not token or len(token) > 1024 * 1024:
        raise SystemExit("Kubernetes TokenRequest returned an invalid token")
    return token


def configure_cli_authentication() -> None:
    """Configure the released CLI for either OIDC bearer auth or operator mTLS."""
    mode = os.environ.get("OPENSHELL_BOOTSTRAP_AUTH_MODE", "clientTLS")
    if mode == "clientTLS":
        return
    if mode != "serviceAccountToken":
        raise SystemExit(f"unsupported OpenShell bootstrap authentication mode: {mode}")

    token = request_admin_token()

    issuer = os.environ["OPENSHELL_OIDC_ISSUER"]
    audience = os.environ["OPENSHELL_OIDC_AUDIENCE"]
    admin_role = os.environ["OPENSHELL_OIDC_ADMIN_ROLE"]
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
    if admin_role not in token_audience:
        raise SystemExit("lifecycle ServiceAccount token does not contain the OpenShell admin role")
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


def reports_not_found(result: subprocess.CompletedProcess[str]) -> bool:
    """Recognize only explicit CLI not-found responses, never generic failures."""
    output = f"{result.stdout}\n{result.stderr}".lower()
    return any(
        marker in output
        for marker in ("not found", "not_found", "does not exist", "code: notfound")
    )


def inspect_provider(existing_sandbox: bool) -> bool:
    """Return provider existence only when this release can safely own it."""
    name = CONFIG["model"]["providerName"]
    existing = run(["provider", "get", name], check=False, capture=True)
    if existing.returncode == 0:
        if not existing_sandbox:
            # The chart-managed gateway serves exactly one release, so a
            # release-derived provider that outlived its sandbox (the documented
            # "delete the Sandbox through OpenShell, then upgrade" recovery) is
            # still this release's provider. Shared gateways keep failing closed
            # because another tenant could own the same name.
            if CONFIG.get("openshellMode") == "managed":
                print(f"provider {name} exists without a sandbox on the chart-managed gateway; reconciling it as release-owned")
                return True
            raise SystemExit(
                f"provider {name} already exists but this release has no owned sandbox; "
                "refusing to mutate a provider whose ownership cannot be proven; "
                "an interrupted first install may require an administrator to remove "
                "this exact orphaned provider before retrying"
            )
        return True
    if reports_not_found(existing):
        return False
    output = f"{existing.stdout}\n{existing.stderr}".strip()
    raise SystemExit(f"failed to determine provider ownership safely: {output[-1000:]}")


def reconcile_provider(provider_exists: bool) -> None:
    name = CONFIG["model"]["providerName"]
    common = ["--credential", "OPENAI_API_KEY", "--config", f"OPENAI_BASE_URL={CONFIG['model']['baseUrl']}"]
    if provider_exists:
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


# Chart-managed in-cluster identities that hold only the OpenShell user role.
# Each entry is reconciled as a workspace member: added while its feature is
# enabled and removed when the feature is turned off.
WORKSPACE_MEMBER_KEYS = ("operatorClient", "accessRelay")


def reconcile_workspace_member(purpose: str, member: dict[str, object]) -> None:
    """Grant or revoke one user-role workspace membership, never admin."""
    arguments = [
        "workspace",
        "member",
        "add" if member.get("enabled") else "remove",
        "--workspace",
        str(member["workspace"]),
        "--subject",
        str(member["subject"]),
    ]
    if member.get("enabled"):
        arguments.extend(["--role", "user"])
    result = run(arguments, check=False, capture=True)
    output = f"{result.stdout}\n{result.stderr}".strip()
    if result.returncode == 0:
        action = "granted" if member.get("enabled") else "removed"
        print(f"{action} OpenShell workspace-user access for {member['subject']}")
        return
    lowered = output.lower()
    if member.get("enabled"):
        if "already exists" in lowered or "already_exists" in lowered:
            print(f"OpenShell workspace membership already exists for {member['subject']}")
            return
    elif "not found" in lowered or "not_found" in lowered or "does not exist" in lowered:
        print(f"OpenShell workspace membership is already absent for {member['subject']}")
        return
    raise SystemExit(f"failed to reconcile {purpose} workspace membership: {output[-1000:]}")


def reconcile_operator_client_member() -> None:
    """Reconcile the terminal and access relay identities' workspace-user access."""
    if CONFIG.get("openshellMode") != "managed":
        return
    for key in WORKSPACE_MEMBER_KEYS:
        member = CONFIG.get(key)
        if member:
            reconcile_workspace_member(key, member)


def verify_existing_sandbox() -> bool:
    result = run(["sandbox", "get", CONFIG["sandboxName"], "--output", "json"], check=False, capture=True)
    if result.returncode != 0:
        if reports_not_found(result):
            return False
        output = f"{result.stdout}\n{result.stderr}".strip()
        raise SystemExit(f"failed to determine sandbox ownership safely: {output[-1000:]}")
    detail = json.loads(result.stdout)
    labels = detail.get("labels") or {}
    required = CONFIG["labels"]
    if any(labels.get(key) != value for key, value in required.items()):
        raise SystemExit(
            f"sandbox {CONFIG['sandboxName']} already exists but does not match this exact chart/image/security configuration; "
            "delete it explicitly after reviewing persisted state, then rerun the Helm upgrade"
        )
    if str(detail.get("phase", "")).lower() in {"failed", "deleted", "error"}:
        raise SystemExit(
            f"owned sandbox {CONFIG['sandboxName']} is in terminal phase {detail.get('phase')}; "
            "inspect its Pod log, delete it through OpenShell, then rerun the Helm upgrade"
        )
    print(f"owned sandbox {CONFIG['sandboxName']} already exists; leaving it unchanged")
    return True


def release_identity_labels() -> dict[str, str]:
    """Labels that identify this release's sandbox regardless of its configuration identity."""
    return {
        key: value
        for key, value in CONFIG["labels"].items()
        if key != "nemoclaw.nvidia.com/config-id"
    }


def delete_sandbox() -> None:
    """Delete this release's sandbox through the authenticated gateway and verify it is gone.

    This is the executable teardown path: it needs no local OpenShell binary
    because the bootstrap Job already authenticates with its projected admin
    token. Only a sandbox carrying this release's identity labels is deleted;
    a same-named sandbox owned by anything else is left untouched.
    """
    name = CONFIG["sandboxName"]
    result = run(["sandbox", "get", name, "--output", "json"], check=False, capture=True)
    if result.returncode != 0:
        if reports_not_found(result):
            print(f"sandbox {name} is already absent")
            return
        output = f"{result.stdout}\n{result.stderr}".strip()
        raise SystemExit(f"failed to inspect sandbox {name} before deletion: {output[-1000:]}")
    detail = json.loads(result.stdout)
    labels = detail.get("labels") or {}
    required = release_identity_labels()
    mismatched = sorted(key for key, value in required.items() if labels.get(key) != value)
    if mismatched:
        raise SystemExit(
            f"refusing to delete sandbox {name}: it does not carry this release's identity labels "
            f"({', '.join(mismatched)}); inspect it with the OpenShell CLI before removing it manually"
        )
    run(["sandbox", "delete", name])
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        probe = run(["sandbox", "get", name, "--output", "json"], check=False, capture=True)
        if probe.returncode != 0 and reports_not_found(probe):
            print(f"deleted sandbox {name} and verified it is gone")
            return
        time.sleep(5)
    raise SystemExit(f"sandbox {name} still exists 300 seconds after the delete request; inspect the gateway before retrying")


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
    # Fail with a precise diagnosis before waiting on a gateway whose OIDC
    # initialization would otherwise time out silently.
    verify_issuer_discovery()
    configure_cli_authentication()
    wait_for_gateway()
    if CONFIG.get("sandboxDesiredState", "present") == "absent":
        # Reviewed teardown: remove only this release's sandbox and stop. The
        # provider and workspace memberships stay so a later `present` revision
        # recreates the sandbox without re-registering anything.
        delete_sandbox()
        return
    existing_sandbox = verify_existing_sandbox()
    # Ownership is checked before provider mutation so an accidental explicit
    # name collision on a shared gateway fails without changing another
    # release's inference configuration.
    provider_exists = inspect_provider(existing_sandbox)
    # Reconcile the release-scoped provider before creating a missing Sandbox.
    # If another tenant creates the provider after inspection, the create
    # command fails before this release has created a Sandbox. If Sandbox
    # creation later fails, retries deliberately stop on the orphaned provider
    # and require explicit administrator cleanup rather than claiming it based
    # only on the presence of a same-named Sandbox.
    reconcile_provider(provider_exists)
    if not existing_sandbox:
        create_sandbox()
        print(f"created sandbox {CONFIG['sandboxName']} from immutable image {CONFIG['agentImage']}")
    reconcile_operator_client_member()


if __name__ == "__main__":
    main()
