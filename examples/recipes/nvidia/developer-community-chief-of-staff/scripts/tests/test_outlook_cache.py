# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

RECIPE_DIR = Path(__file__).resolve().parents[2]
PROVIDERS_SCRIPT = RECIPE_DIR / "scripts/02-providers.sh"
CACHE_HELPER = RECIPE_DIR / "scripts/lib/outlook_cache.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_cache_helper():
    return load_module(
        "outlook_cache",
        RECIPE_DIR / "scripts/lib/outlook_cache.py",
    )


def load_login_helper():
    return load_module(
        "login_ms_graph",
        RECIPE_DIR / "scripts/login-ms-graph.py",
    )


def count_from(path: Path) -> int:
    if not path.exists():
        return 0
    return int(path.read_text(encoding="utf-8"))


def run_provider_phase(tmp_path: Path, scenario: str, mode: str = "1"):
    recipe_dir = tmp_path / "recipe"
    scripts_dir = recipe_dir / "scripts"
    lib_dir = scripts_dir / "lib"
    providers_dir = recipe_dir / "providers"
    fake_bin = tmp_path / "bin"
    for directory in (lib_dir, providers_dir, fake_bin):
        directory.mkdir(parents=True, exist_ok=True)

    providers_copy = scripts_dir / "02-providers.sh"
    shutil.copy2(PROVIDERS_SCRIPT, providers_copy)
    shutil.copy2(CACHE_HELPER, lib_dir / "outlook_cache.py")
    (scripts_dir / "_lib.sh").write_text(
        """#!/usr/bin/env bash
EXAMPLE_DIR="${TEST_RECIPE_DIR:?}"
SANDBOX_NAME="test-sandbox"
ATIF_RELAY_HOST="127.0.0.1"
ATIF_RELAY_PORT="8080"
ATIF_RELAY_TOKEN_CACHE="$EXAMPLE_DIR/.bootstrap/cache/atif-token"
load_env() { :; }
assert_messaging_config() { :; }
provider_type_matches() { return 0; }
atif_remote_enabled() { return 1; }
upsert_cred() { :; }
""",
        encoding="utf-8",
    )
    for profile in (
        "outlook-email.yaml",
        "slack.yaml",
        "github.yaml",
        "atif-export-relay.yaml",
    ):
        (providers_dir / profile).write_text("id: test\n", encoding="utf-8")

    now_ms = int(time.time() * 1000)
    cache_path = recipe_dir / ".bootstrap/cache/ms-graph-token.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        json.dumps(
            {
                "access_token": "old-access-token",
                "refresh_token": "old-refresh-token",
                "expires_at_ms": 1,
                "refresh_expires_at_ms": now_ms + 86_400_000,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cache_path.chmod(0o600)
    original_bytes = cache_path.read_bytes()
    original_mtime_ns = cache_path.stat().st_mtime_ns
    original_mode = stat.S_IMODE(cache_path.stat().st_mode)

    rotate_count = tmp_path / "rotate-count"
    login_count = tmp_path / "login-count"
    fake_openshell = fake_bin / "openshell"
    fake_openshell.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-} ${2:-}" == "settings get" ]]; then
  echo "providers_v2_enabled = true"
  exit 0
fi
if [[ "${1:-} ${2:-}" == "provider get" ]]; then
  exit 1
fi
if [[ "${1:-} ${2:-} ${3:-}" == "provider refresh rotate" ]]; then
  count=0
  [[ ! -f "$ROTATE_COUNT_FILE" ]] || read -r count < "$ROTATE_COUNT_FILE"
  count=$((count + 1))
  printf '%s\n' "$count" > "$ROTATE_COUNT_FILE"
  case "$OUTLOOK_TEST_SCENARIO" in
    success)
      exit 0
      ;;
    http_400)
      if [[ "$count" -eq 1 ]]; then
        echo "rotation failed" >&2
        exit 1
      fi
      exit 0
      ;;
    http_400_retry_failure)
      echo "rotation unavailable" >&2
      exit 1
      ;;
    *)
      echo "rotation unavailable" >&2
      exit 1
      ;;
  esac
fi
if [[ "${1:-} ${2:-} ${3:-}" == "provider refresh status" ]]; then
  case "$OUTLOOK_TEST_SCENARIO" in
    http_400|http_400_retry_failure)
      echo "token endpoint returned HTTP 400 Bad Request"
      exit 0
      ;;
    http_503)
      echo "token endpoint returned HTTP 503 Service Unavailable"
      exit 0
      ;;
    tls_failure)
      echo "token endpoint request failed: certificate verify failed"
      exit 0
      ;;
    gateway_unavailable)
      echo "gateway unavailable" >&2
      exit 1
      ;;
  esac
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_openshell.chmod(0o755)

    fake_python = fake_bin / "python3"
    fake_python.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == *"/login-ms-graph.py" ]]; then
  count=0
  [[ ! -f "$LOGIN_COUNT_FILE" ]] || read -r count < "$LOGIN_COUNT_FILE"
  printf '%s\n' "$((count + 1))" > "$LOGIN_COUNT_FILE"
  printf '%s\n' "$FRESH_LOGIN_JSON"
  exit 0
fi
exec "$REAL_PYTHON" "$@"
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    fresh_login = json.dumps(
        {
            "access_token": "fresh-access-token",
            "refresh_token": "fresh-refresh-token",
            "expires_at_ms": now_ms + 3_600_000,
            "refresh_expires_at_ms": now_ms + 86_400_000,
        }
    )
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "REAL_PYTHON": sys.executable,
        "TEST_RECIPE_DIR": str(recipe_dir),
        "ROTATE_COUNT_FILE": str(rotate_count),
        "LOGIN_COUNT_FILE": str(login_count),
        "OUTLOOK_TEST_SCENARIO": scenario,
        "FRESH_LOGIN_JSON": fresh_login,
        "OUTLOOK_CLIENT_ID": "test-client",
        "OUTLOOK_TENANT_ID": "test-tenant",
        "OUTLOOK_TARGET_MAILBOX": "agent@example.test",
        "OUTLOOK_LOGIN_CACHE": mode,
        "ATIF_EXPORT_MODE": "local",
        "NEMOCLAW_INFERENCE_PREFLIGHT": "0",
    }
    for name in (
        "OPENAI_API_KEY",
        "COMPATIBLE_API_KEY",
        "GITHUB_TOKEN",
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
        "MS_GRAPH_ACCESS_TOKEN",
        "ATIF_RELAY_AUTH_TOKEN",
    ):
        environment.pop(name, None)

    result = subprocess.run(
        ["bash", str(providers_copy)],
        cwd=recipe_dir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "result": result,
        "cache": cache_path,
        "original_bytes": original_bytes,
        "original_mtime_ns": original_mtime_ns,
        "original_mode": original_mode,
        "rotate_count": count_from(rotate_count),
        "login_count": count_from(login_count),
    }


def assert_tokens_not_logged(run) -> None:
    output = run["result"].stdout + run["result"].stderr
    assert "old-refresh-token" not in output
    assert "fresh-refresh-token" not in output


def assert_original_cache_preserved(run) -> None:
    cache = run["cache"]
    assert cache.read_bytes() == run["original_bytes"]
    assert cache.stat().st_mtime_ns == run["original_mtime_ns"]
    assert stat.S_IMODE(cache.stat().st_mode) == run["original_mode"]
    assert_tokens_not_logged(run)


def test_explicit_refresh_expiry_wins(tmp_path):
    helper = load_cache_helper()
    cache = tmp_path / "token.json"
    cache.write_text(
        json.dumps(
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_at_ms": 1_000,
                "refresh_expires_at_ms": 9_000,
            }
        ),
        encoding="utf-8",
    )

    assert helper.refresh_expires_at_ms(cache) == 9_000


def test_expired_refresh_horizon_is_not_replaced_by_legacy_default(tmp_path):
    helper = load_cache_helper()
    cache = tmp_path / "token.json"
    cache.write_text(
        json.dumps(
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_at_ms": 1_000,
                "refresh_expires_at_ms": 1,
            }
        ),
        encoding="utf-8",
    )

    assert helper.refresh_expires_at_ms(cache) == 1


def test_legacy_cache_uses_mtime_not_access_expiry(tmp_path):
    helper = load_cache_helper()
    cache = tmp_path / "token.json"
    cache.write_text(
        json.dumps(
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_at_ms": 1_000,
            }
        ),
        encoding="utf-8",
    )

    expected = int(cache.stat().st_mtime * 1000) + helper.DEFAULT_REFRESH_LIFETIME_MS
    assert helper.refresh_expires_at_ms(cache) == expected


def test_missing_refresh_token_is_stale(tmp_path):
    helper = load_cache_helper()
    cache = tmp_path / "token.json"
    cache.write_text(
        json.dumps({"access_token": "access", "expires_at_ms": 1_000}),
        encoding="utf-8",
    )

    assert helper.refresh_expires_at_ms(cache) == 0


def test_malformed_or_non_object_cache_is_stale(tmp_path):
    helper = load_cache_helper()
    malformed = tmp_path / "malformed.json"
    malformed.write_text("not-json", encoding="utf-8")
    non_object = tmp_path / "list.json"
    non_object.write_text("[]", encoding="utf-8")

    assert helper.refresh_expires_at_ms(malformed) == 0
    assert helper.refresh_expires_at_ms(non_object) == 0


def test_refresh_lifetime_uses_response_or_conservative_default():
    login = load_login_helper()

    assert (
        login.refresh_token_lifetime_seconds({"refresh_token_expires_in": 86_400})
        == 86_400
    )
    assert login.refresh_token_lifetime_seconds({}) == (
        login.DEFAULT_REFRESH_TOKEN_LIFETIME_SECONDS
    )
    assert (
        login.refresh_token_lifetime_seconds({"refresh_token_expires_in": "invalid"})
        == login.DEFAULT_REFRESH_TOKEN_LIFETIME_SECONDS
    )


def test_expired_access_token_reuses_fresh_refresh_cache(tmp_path):
    run = run_provider_phase(tmp_path, "success")

    assert run["result"].returncode == 0, run["result"].stderr
    assert run["rotate_count"] == 1
    assert run["login_count"] == 0
    assert_original_cache_preserved(run)


def test_http_400_reauthenticates_and_replaces_cache_after_success(tmp_path):
    run = run_provider_phase(tmp_path, "http_400")

    assert run["result"].returncode == 0, run["result"].stderr
    assert run["rotate_count"] == 2
    assert run["login_count"] == 1
    cache = run["cache"]
    assert json.loads(cache.read_text(encoding="utf-8"))["refresh_token"] == (
        "fresh-refresh-token"
    )
    assert stat.S_IMODE(cache.stat().st_mode) == 0o600
    assert_tokens_not_logged(run)


def test_http_503_preserves_cache_without_login(tmp_path):
    run = run_provider_phase(tmp_path, "http_503")

    assert run["result"].returncode != 0
    assert run["rotate_count"] == 1
    assert run["login_count"] == 0
    assert_original_cache_preserved(run)


def test_token_endpoint_tls_failure_preserves_cache_without_login(tmp_path):
    run = run_provider_phase(tmp_path, "tls_failure")

    assert run["result"].returncode != 0
    assert run["rotate_count"] == 1
    assert run["login_count"] == 0
    assert_original_cache_preserved(run)


def test_gateway_unavailable_preserves_cache_without_login(tmp_path):
    run = run_provider_phase(tmp_path, "gateway_unavailable")

    assert run["result"].returncode != 0
    assert run["rotate_count"] == 1
    assert run["login_count"] == 0
    assert_original_cache_preserved(run)


def test_unrecognized_status_preserves_cache_without_login(tmp_path):
    run = run_provider_phase(tmp_path, "unknown_status")

    assert run["result"].returncode != 0
    assert run["rotate_count"] == 1
    assert run["login_count"] == 0
    assert_original_cache_preserved(run)


def test_reauth_retry_failure_preserves_original_cache(tmp_path):
    run = run_provider_phase(tmp_path, "http_400_retry_failure")

    assert run["result"].returncode != 0
    assert run["rotate_count"] == 2
    assert run["login_count"] == 1
    assert_original_cache_preserved(run)


def test_forced_login_rotation_failure_preserves_original_cache(tmp_path):
    run = run_provider_phase(tmp_path, "tls_failure", mode="2")

    assert run["result"].returncode != 0
    assert run["rotate_count"] == 1
    assert run["login_count"] == 1
    assert_original_cache_preserved(run)
