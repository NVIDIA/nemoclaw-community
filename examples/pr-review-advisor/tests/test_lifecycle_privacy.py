# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Static and shell-level privacy contracts for the trusted host lifecycle."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import json
import http.server
import threading
from pathlib import Path

_EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
_LIB = _EXAMPLE_ROOT / "scripts" / "_lib.sh"
_REVIEW = _EXAMPLE_ROOT / "scripts" / "review.sh"
_MEMORY = _EXAMPLE_ROOT / "scripts" / "memory.sh"
_BRING_UP = _EXAMPLE_ROOT / "scripts" / "bring-up.sh"
_SANDBOX = _EXAMPLE_ROOT / "scripts" / "03-sandbox.sh"
_TEAR_DOWN = _EXAMPLE_ROOT / "scripts" / "tear-down.sh"
_VERIFY = _EXAMPLE_ROOT / "scripts" / "verify.sh"


def _installed_lib(tmp_path: Path, env_text: str, mode: int) -> tuple[Path, Path]:
    install = tmp_path / "repo" / ".nemoclaw" / "review-advisor"
    runtime = install / "runtime"
    shutil.copytree(
        _EXAMPLE_ROOT,
        runtime,
        ignore=shutil.ignore_patterns(
            ".pytest_cache",
            "__pycache__",
            "*.pyc",
            ".Dockerfile.staged*",
        ),
    )
    scripts = runtime / "scripts"
    copied = scripts / "_lib.sh"
    (install / "config.yaml").write_text(
        'schema_version: 1\nrepository: "example/project"\n',
        encoding="utf-8",
    )
    env_file = install / ".env"
    if "OPENSHELL_GATEWAY_ENDPOINT=" not in env_text:
        env_text += "OPENSHELL_GATEWAY_ENDPOINT=https://127.0.0.1:17670\n"
    env_file.write_text(env_text, encoding="utf-8")
    env_file.chmod(mode)
    return copied, env_file


def _source(lib: Path, home: Path, command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'source "$1"; {command}', "bash", str(lib)],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
    )


def test_load_env_rejects_group_or_other_permissions(tmp_path: Path) -> None:
    lib, _env_file = _installed_lib(
        tmp_path,
        "NEMOCLAW_MODEL=private-model\n",
        0o640,
    )

    result = _source(lib, tmp_path / "home", "load_env")

    assert result.returncode != 0
    assert "mode 0600 or stricter" in result.stderr


def test_load_env_rejects_symlink(tmp_path: Path) -> None:
    lib, env_file = _installed_lib(
        tmp_path,
        "NEMOCLAW_MODEL=private-model\n",
        0o600,
    )
    target = env_file.with_name("private.env")
    env_file.replace(target)
    env_file.symlink_to(target.name)

    result = _source(lib, tmp_path / "home", "load_env")

    assert result.returncode != 0
    assert "regular non-symlink" in result.stderr


def test_load_env_rejects_unknown_duplicate_and_shell_syntax(tmp_path: Path) -> None:
    cases = (
        ("UNKNOWN_KEY=value\n", "unknown key"),
        (
            "NEMOCLAW_MODEL=one\nNEMOCLAW_MODEL=two\n",
            "duplicate key",
        ),
        ("NEMOCLAW_MODEL=$(id)\n", "forbidden shell syntax"),
    )
    for index, (env_text, expected) in enumerate(cases):
        lib, _env_file = _installed_lib(tmp_path / str(index), env_text, 0o600)
        result = _source(lib, tmp_path / f"home-{index}", "load_env")
        assert result.returncode != 0
        assert expected in result.stderr


def test_default_load_env_never_returns_provider_credential_values(
    tmp_path: Path,
) -> None:
    lib, _env_file = _installed_lib(
        tmp_path,
        "NVIDIA_INFERENCE_API_KEY=provider-secret-canary\n",
        0o600,
    )

    default = _source(
        lib,
        tmp_path / "home",
        (
            "load_env; "
            'test -z "${NVIDIA_INFERENCE_API_KEY:-}"; '
            'printf "%s\\n" "$REVIEW_ADVISOR_ENV_KEYS"'
        ),
    )
    provider = _source(
        lib,
        tmp_path / "home",
        (
            "load_env --provider-credentials; "
            'printf "%s\\n" "$NVIDIA_INFERENCE_API_KEY"'
        ),
    )

    assert default.returncode == 0, default.stderr
    assert "provider-secret-canary" not in default.stdout + default.stderr
    assert "|NVIDIA_INFERENCE_API_KEY|" in default.stdout
    assert provider.returncode == 0, provider.stderr
    assert provider.stdout.strip() == "provider-secret-canary"
    for script_name in (
        "review.sh",
        "feedback.sh",
        "snapshot.sh",
        "restore.sh",
        "memory.sh",
        "verify.sh",
        "tear-down.sh",
    ):
        source = (_EXAMPLE_ROOT / "scripts" / script_name).read_text(encoding="utf-8")
        assert "load_env --provider-credentials" not in source


def test_load_env_derives_install_identity_and_ignores_direct_state_overrides(
    tmp_path: Path,
) -> None:
    lib, _env_file = _installed_lib(
        tmp_path,
        f"REVIEW_ADVISOR_STATE_ROOT={tmp_path / 'state'}\n",
        0o600,
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            (
                'source "$1"; load_env; '
                'printf "%s\\n%s\\n%s\\n%s\\n%s\\n" '
                '"$REVIEW_ADVISOR_INSTALL_ID" "$REVIEW_ADVISOR_REPOSITORY" '
                '"$STATE_DIR" "$NEMOCLAW_SANDBOX_NAME" "$HERMES_FORWARD_PORT"; '
                'if env | grep -q "^OPENSHELL_GATEWAY_ENDPOINT="; then exit 9; fi'
            ),
            "bash",
            str(lib),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "REVIEW_ADVISOR_STATE_DIR": "/tmp/ambient-state-override",
            "REVIEW_ADVISOR_SNAPSHOT_DIR": "/tmp/ambient-snapshot-override",
            "OPENSHELL_GATEWAY_ENDPOINT": "https://127.0.0.1:19999",
        },
    )

    assert result.returncode == 0, result.stderr
    install_id, repository, state_dir, sandbox, port = result.stdout.splitlines()
    assert len(install_id) == 16
    assert repository == "example/project"
    assert state_dir == str(tmp_path / "state" / install_id / "runtime")
    assert sandbox == f"pr-review-{install_id}"
    assert 20000 <= int(port) < 40000
    assert "ambient-state-override" not in result.stdout


def test_openshell_preflight_requires_exact_0_0_85(tmp_path: Path) -> None:
    lib, _env_file = _installed_lib(tmp_path, "", 0o600)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "openshell"
    fake.write_text("#!/usr/bin/env bash\nprintf 'openshell 0.0.84\\n'\n", encoding="utf-8")
    fake.chmod(0o755)

    result = subprocess.run(
        ["bash", "-c", 'source "$1"; load_env; openshell_preflight', "bash", str(lib)],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert result.returncode != 0
    assert "requires exactly openshell 0.0.85" in result.stderr


def test_runtime_fingerprint_mismatch_fails_closed(tmp_path: Path) -> None:
    lib, _env_file = _installed_lib(tmp_path, "", 0o600)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "openshell"
    fake.write_text(
        """#!/usr/bin/env bash
if [[ "$1" == "-V" ]]; then
  printf 'openshell 0.0.85\\n'
else
  printf '%064d\\n' 0
fi
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; load_env; assert_runtime_fingerprint',
            "bash",
            str(lib),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert result.returncode != 0
    assert "runtime fingerprint does not match" in result.stderr


def test_forward_mapping_requires_exact_loopback_port_and_sandbox(
    tmp_path: Path,
) -> None:
    lib, _env_file = _installed_lib(
        tmp_path,
        "NEMOCLAW_SANDBOX_NAME=expected-sandbox\nHERMES_FORWARD_PORT=28642\n",
        0o600,
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "openshell"
    fake.write_text(
        """#!/usr/bin/env bash
if [[ "$1" == "-V" ]]; then
  printf 'openshell 0.0.85\\n'
else
  printf 'SANDBOX BIND PORT PID STATUS\\n'
  printf '%s 127.0.0.1 28642 123 running\\n' "$FAKE_FORWARD_SANDBOX"
fi
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    base_env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    }
    exact = subprocess.run(
        ["bash", "-c", 'source "$1"; load_env; assert_forward_mapping', "bash", str(lib)],
        check=False,
        capture_output=True,
        text=True,
        env={**base_env, "FAKE_FORWARD_SANDBOX": "expected-sandbox"},
    )
    wrong = subprocess.run(
        ["bash", "-c", 'source "$1"; load_env; assert_forward_mapping', "bash", str(lib)],
        check=False,
        capture_output=True,
        text=True,
        env={**base_env, "FAKE_FORWARD_SANDBOX": "other-sandbox"},
    )

    assert exact.returncode == 0, exact.stderr
    assert wrong.returncode != 0
    assert "does not map the exact loopback port" in wrong.stderr


def test_hermes_surface_requires_auth_model_and_exact_eight_tools(
    tmp_path: Path,
) -> None:
    tools = [
        "review_begin",
        "review_status",
        "review_repo_read",
        "review_repo_list",
        "review_repo_search",
        "review_diff",
        "review_commit_stage",
        "review_finalize",
    ]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.headers.get("Authorization") is None:
                payload = b'{"error":"unauthorized"}'
                self.send_response(401)
            elif self.path == "/v1/capabilities":
                payload = json.dumps(
                    {
                        "object": "hermes.api_server.capabilities",
                        "platform": "hermes-agent",
                        "model": "nvidia/nvidia/nemotron-3-ultra",
                        "auth": {"type": "bearer", "required": True},
                        "runtime": {
                            "mode": "server_agent",
                            "tool_execution": "server",
                            "split_runtime": False,
                        },
                        "endpoints": {
                            "chat_completions": {
                                "method": "POST",
                                "path": "/v1/chat/completions",
                            },
                            "session_delete": {
                                "method": "DELETE",
                                "path": "/api/sessions/{session_id}",
                            },
                        },
                    }
                ).encode()
                self.send_response(200)
            elif self.path == "/v1/toolsets":
                payload = json.dumps(
                    {
                        "object": "list",
                        "platform": "api_server",
                        "data": [
                            {
                                "name": "review-advisor",
                                "enabled": True,
                                "configured": True,
                                "tools": tools,
                            },
                            {
                                "name": "terminal",
                                "enabled": False,
                                "configured": False,
                                "tools": ["terminal"],
                            },
                        ],
                    }
                ).encode()
                self.send_response(200)
            else:
                payload = b'{"error":"not found"}'
                self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        lib, _env_file = _installed_lib(
            tmp_path,
            f"HERMES_FORWARD_PORT={server.server_address[1]}\n",
            0o600,
        )
        result = _source(
            lib,
            tmp_path / "home",
            "load_env; assert_hermes_api_surface",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert result.returncode == 0, result.stderr


def test_api_key_is_private_and_not_exported(tmp_path: Path) -> None:
    lib, _env_file = _installed_lib(
        tmp_path,
        "REVIEW_ADVISOR_STATE_ROOT="
        + str(tmp_path / "state")
        + "\nNVIDIA_INFERENCE_API_KEY=provider-secret\n",
        0o600,
    )

    result = _source(
        lib,
        tmp_path / "home",
        (
            "load_env; ensure_api_key; "
            'test -n "$REVIEW_ADVISOR_API_KEY"; '
            'if env | grep -q "^REVIEW_ADVISOR_API_KEY="; then exit 9; fi; '
            'scrub_external_secrets; '
            'if env | grep -q "^NVIDIA_INFERENCE_API_KEY="; then exit 10; fi; '
            'printf "%s\\n" "$STATE_DIR/api-key"'
        ),
    )

    assert result.returncode == 0, result.stderr
    key_file = Path(result.stdout.strip())
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


def test_memory_export_creates_private_directory_and_files(tmp_path: Path) -> None:
    lib, env_file = _installed_lib(
        tmp_path,
        "NEMOCLAW_SANDBOX_NAME=test-review-sandbox\n",
        0o600,
    )
    scripts = lib.parent
    memory = scripts / "memory.sh"
    assert memory.is_file()
    identity = _source(
        lib,
        tmp_path / "home",
        (
            "load_env; compute_runtime_fingerprint; "
            'printf "%s\\n%s\\n" "$OPENSHELL_GATEWAY" '
            '"$REVIEW_ADVISOR_RUNTIME_FINGERPRINT"'
        ),
    )
    assert identity.returncode == 0, identity.stderr
    gateway_name, runtime_fingerprint = identity.stdout.splitlines()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    openshell = fake_bin / "openshell"
    openshell.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-V" ]]; then
  printf 'openshell 0.0.85\\n'
  exit 0
fi
gateway=""
if [[ "${1:-}" == "-g" ]]; then
  gateway="$2"
  shift 2
fi
if [[ "$1 $2" == "gateway list" ]]; then
  printf '[{"name":"%s","endpoint":"https://127.0.0.1:17670"}]\\n' "$FAKE_GATEWAY_NAME"
elif [[ "$1 $2" == "gateway info" ]]; then
  printf '{"gateway":"%s","server":"https://127.0.0.1:17670"}\\n' "$gateway"
elif [[ "$1 $2" == "sandbox list" ]]; then
  printf '[{"name":"test-review-sandbox","phase":"Ready"}]\\n'
elif [[ "$1 $2" == "sandbox exec" ]]; then
  printf '%s\\n' "$FAKE_RUNTIME_FINGERPRINT"
elif [[ "$1 $2" == "sandbox download" ]]; then
  mkdir -p "$5/memories"
  printf 'private lesson\\n' >"$5/memories/MEMORY.md"
  chmod 755 "$5/memories"
  chmod 644 "$5/memories/MEMORY.md"
else
  echo "unexpected openshell command: $*" >&2
  exit 1
fi
""",
        encoding="utf-8",
    )
    openshell.chmod(0o755)
    destination = tmp_path / "memory-export"
    result = subprocess.run(
        ["bash", str(memory), "export", str(destination)],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_GATEWAY_NAME": gateway_name,
            "FAKE_RUNTIME_FINGERPRINT": runtime_fingerprint,
        },
    )

    assert result.returncode == 0, result.stderr
    assert env_file.stat().st_mode & 0o777 == 0o600
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    assert stat.S_IMODE((destination / "memories").stat().st_mode) == 0o700
    assert stat.S_IMODE(
        (destination / "memories" / "MEMORY.md").stat().st_mode
    ) == 0o600


def test_bring_up_confines_ambient_provider_secret_to_provider_phase(
    tmp_path: Path,
) -> None:
    lib, _env_file = _installed_lib(
        tmp_path,
        "REVIEW_ADVISOR_PROVIDER_MODE=nvidia\n",
        0o600,
    )
    scripts = lib.parent
    with lib.open("a", encoding="utf-8") as stream:
        stream.write(
            """
assert_sandbox_ready() { :; }
start_forward() {
  if env | grep -Eq '^(NVIDIA_INFERENCE_API_KEY|COMPATIBLE_API_KEY)='; then
    echo "provider secret reached forward phase" >&2
    return 1
  fi
  : >"$FAKE_FORWARD_MARKER"
}
"""
        )
    (scripts / "01-gateway.sh").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if env | grep -Eq '^(NVIDIA_INFERENCE_API_KEY|COMPATIBLE_API_KEY)='; then
  echo "provider secret reached gateway phase" >&2
  exit 1
fi
test -d "$REVIEW_ADVISOR_LOCK_DIR"
: >"$FAKE_GATEWAY_MARKER"
""",
        encoding="utf-8",
    )
    (scripts / "02-provider.sh").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
test -d "$REVIEW_ADVISOR_LOCK_DIR"
test -n "${NVIDIA_INFERENCE_API_KEY:-}"
test -z "${COMPATIBLE_API_KEY:-}"
printf '%s' "$NVIDIA_INFERENCE_API_KEY" >"$FAKE_PROVIDER_CAPTURE"
""",
        encoding="utf-8",
    )
    (scripts / "03-sandbox.sh").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if env | grep -Eq '^(NVIDIA_INFERENCE_API_KEY|COMPATIBLE_API_KEY)='; then
  echo "provider secret reached sandbox phase" >&2
  exit 1
fi
test -d "$REVIEW_ADVISOR_LOCK_DIR"
: >"$FAKE_SANDBOX_MARKER"
""",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_openshell = fake_bin / "openshell"
    fake_openshell.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_openshell.chmod(0o755)
    provider_capture = tmp_path / "provider-secret"
    gateway_marker = tmp_path / "gateway"
    sandbox_marker = tmp_path / "sandbox"
    forward_marker = tmp_path / "forward"

    result = subprocess.run(
        ["bash", str(scripts / "bring-up.sh")],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "NVIDIA_INFERENCE_API_KEY": "ci-provider-secret-canary",
            "FAKE_PROVIDER_CAPTURE": str(provider_capture),
            "FAKE_GATEWAY_MARKER": str(gateway_marker),
            "FAKE_SANDBOX_MARKER": str(sandbox_marker),
            "FAKE_FORWARD_MARKER": str(forward_marker),
        },
    )

    assert result.returncode == 0, result.stderr
    assert provider_capture.read_text() == "ci-provider-secret-canary"
    assert gateway_marker.is_file()
    assert sandbox_marker.is_file()
    assert forward_marker.is_file()
    assert "ci-provider-secret-canary" not in result.stdout + result.stderr


def test_provider_modes_use_fixed_openshell_profiles_and_env_credentials(
    tmp_path: Path,
) -> None:
    cases = (
        (
            "nvidia",
            "NVIDIA_INFERENCE_API_KEY",
            "nvidia-secret-canary",
            "nvidia",
            "NVIDIA_API_KEY",
            "NVIDIA_BASE_URL",
            "https://integrate.api.nvidia.com/v1",
            "nvidia/nvidia/nemotron-3-ultra",
        ),
        (
            "openai-compatible",
            "COMPATIBLE_API_KEY",
            "compatible-secret-canary",
            "openai",
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "https://models.example.test/v1",
            "owner/ultra-compatible",
        ),
    )
    for index, (
        mode,
        ambient_key,
        secret,
        provider_type,
        credential_key,
        config_key,
        endpoint,
        model,
    ) in enumerate(cases):
        case_root = tmp_path / str(index)
        env_text = (
            f"REVIEW_ADVISOR_PROVIDER_MODE={mode}\n"
            f"NEMOCLAW_ENDPOINT_URL={endpoint}\n"
            f"NEMOCLAW_MODEL={model}\n"
        )
        lib, _env_file = _installed_lib(case_root, env_text, 0o600)
        scripts = lib.parent
        identity = _source(
            lib,
            case_root / "home",
            'load_env; printf "%s\\n" "$OPENSHELL_GATEWAY"',
        )
        assert identity.returncode == 0, identity.stderr
        gateway_name = identity.stdout.strip()
        fake_bin = case_root / "bin"
        fake_bin.mkdir()
        state_path = case_root / "provider-state.json"
        fake = fake_bin / "openshell"
        fake.write_text(
            """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

args = sys.argv[1:]
if args == ["-V"]:
    print("openshell 0.0.85")
    raise SystemExit
gateway = ""
if args[:1] == ["-g"]:
    gateway = args[1]
    args = args[2:]
state_path = pathlib.Path(os.environ["FAKE_PROVIDER_STATE"])
if args[:2] == ["gateway", "list"]:
    print(json.dumps([{
        "name": os.environ["FAKE_GATEWAY_NAME"],
        "endpoint": "https://127.0.0.1:17670",
    }]))
elif args[:2] == ["gateway", "info"]:
    print(json.dumps({
        "gateway": gateway,
        "server": "https://127.0.0.1:17670",
    }))
elif args[:3] == ["settings", "get", "--global"]:
    print(json.dumps({
        "scope": "global",
        "settings_revision": 1,
        "settings": {"providers_v2_enabled": "true"},
    }))
elif args[:2] == ["provider", "list"]:
    if not state_path.exists():
        print("[]")
    else:
        state = json.loads(state_path.read_text())
        print(json.dumps([{
            "id": "provider-object-id",
            "name": state["name"],
            "type": state["type"],
            "credential_keys": [state["credential"]],
            "config_keys": [state["config_key"]],
            "resource_version": 1,
        }]))
elif args[:2] == ["provider", "create"]:
    name = args[args.index("--name") + 1]
    provider_type = args[args.index("--type") + 1]
    credential = args[args.index("--credential") + 1]
    config = args[args.index("--config") + 1]
    if "=" in credential:
        raise SystemExit("credential value appeared in argv")
    config_key, config_value = config.split("=", 1)
    state_path.write_text(json.dumps({
        "name": name,
        "type": provider_type,
        "credential": credential,
        "config_key": config_key,
        "config_value": config_value,
        "secret": os.environ.get(credential),
        "source_secret_visible": any(
            os.environ.get(key)
            for key in ("NVIDIA_INFERENCE_API_KEY", "COMPATIBLE_API_KEY")
        ),
    }))
elif args[:2] == ["inference", "set"]:
    state = json.loads(state_path.read_text())
    state["no_verify"] = "--no-verify" in args
    state["route_provider"] = args[args.index("--provider") + 1]
    state["route_model"] = args[args.index("--model") + 1]
    state_path.write_text(json.dumps(state))
elif args[:2] == ["inference", "get"]:
    state = json.loads(state_path.read_text())
    print("Gateway inference:")
    print()
    print("  Provider: " + state["route_provider"])
    print("  Model: " + state["route_model"])
    print("  Version: 1")
    print()
    print("System inference:")
    print()
    print("  Not configured")
else:
    raise SystemExit(f"unexpected openshell arguments: {args!r}")
""",
            encoding="utf-8",
        )
        fake.chmod(0o755)

        result = subprocess.run(
            ["bash", str(scripts / "02-provider.sh")],
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "HOME": str(case_root / "home"),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "FAKE_PROVIDER_STATE": str(state_path),
                "FAKE_GATEWAY_NAME": gateway_name,
                ambient_key: secret,
            },
        )

        assert result.returncode == 0, result.stderr
        state = json.loads(state_path.read_text())
        assert state["type"] == provider_type
        assert state["credential"] == credential_key
        assert state["config_key"] == config_key
        assert state["config_value"] == endpoint
        assert state["secret"] == secret
        assert state["source_secret_visible"] is False
        assert state["no_verify"] is False
        assert state["route_model"] == model


def test_existing_mode_rejects_non_inference_generic_provider_type(
    tmp_path: Path,
) -> None:
    lib, _env_file = _installed_lib(
        tmp_path,
        (
            "REVIEW_ADVISOR_PROVIDER_MODE=existing\n"
            "INFERENCE_PROVIDER_NAME=existing-provider\n"
            "REVIEW_ADVISOR_EXISTING_PROVIDER_TYPE=generic\n"
            "NEMOCLAW_MODEL=owner/model\n"
        ),
        0o600,
    )
    scripts = lib.parent
    identity = _source(
        lib,
        tmp_path / "home",
        'load_env; printf "%s\\n" "$OPENSHELL_GATEWAY"',
    )
    assert identity.returncode == 0, identity.stderr
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "openshell"
    fake.write_text(
        """#!/usr/bin/env bash
set -eu
if [[ "$1" == "-V" ]]; then printf 'openshell 0.0.85\\n'; exit 0; fi
gateway=""
if [[ "$1" == "-g" ]]; then gateway="$2"; shift 2; fi
case "$1 $2" in
  "gateway list") printf '[{"name":"%s","endpoint":"https://127.0.0.1:17670"}]\\n' "$FAKE_GATEWAY_NAME" ;;
  "gateway info") printf '{"gateway":"%s","server":"https://127.0.0.1:17670"}\\n' "$gateway" ;;
  "settings get") printf '{"scope":"global","settings_revision":1,"settings":{"providers_v2_enabled":"true"}}\\n' ;;
  *) echo "unexpected command: $*" >&2; exit 2 ;;
esac
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    result = subprocess.run(
        ["bash", str(scripts / "02-provider.sh")],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_GATEWAY_NAME": identity.stdout.strip(),
        },
    )

    assert result.returncode != 0
    assert "supports only reviewed inference provider types" in result.stderr


def test_review_stages_then_cleans_before_atomic_publication() -> None:
    source = _REVIEW.read_text(encoding="utf-8")

    assert source.index("acquire_review_lock") < source.index(
        'rm -f -- "$artifact_path"'
    )
    assert '--output "$work/canonical"' in source
    assert 'cp "$work/request.json" "$output/request.json"' not in source
    cleanup_call = source.rindex("\nprivacy_cleanup\n")
    publication = source.index('names = ("request.json", "review.json"')
    assert cleanup_call < publication
    assert "PRAGMA wal_checkpoint(TRUNCATE)" in source
    assert 'connection.execute("VACUUM")' in source
    assert "/sandbox/review-input" in source
    assert "request_dump_${session}_*.json" in source
    assert "/tmp/hermes.log /tmp/socat.log" in source
    assert "destination.chmod(0o600)" in source
    assert "output.chmod(0o700)" in source
    assert "hermes-response.json" in source  # legacy output is removed
    assert "hermes-response.json" not in source[publication:]
    assert '--max-checkout-files "$REVIEW_ADVISOR_MAX_CHECKOUT_FILES"' in source
    assert '--max-checkout-bytes "$REVIEW_ADVISOR_MAX_CHECKOUT_BYTES"' in source
    assert source.index("start_forward") < source.index("assert_inference_route")
    assert source.index("assert_inference_route") < source.index("call-hermes.py")


def test_verify_uses_a_hard_bounded_sessionless_inference_probe() -> None:
    source = _VERIFY.read_text(encoding="utf-8")

    assert 'sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" --timeout 45 --' in source
    assert "/opt/hermes/.venv/bin/python /opt/review-advisor/probe-inference.py" in source
    assert source.index("assert_inference_route") < source.index("probe-inference.py")
    assert source.index("probe-inference.py") < source.index("start_forward")


def test_mutating_lifecycle_commands_share_the_review_lock() -> None:
    bring_up = _BRING_UP.read_text(encoding="utf-8")
    sandbox = _SANDBOX.read_text(encoding="utf-8")
    tear_down = _TEAR_DOWN.read_text(encoding="utf-8")

    assert "acquire_review_lock" in bring_up
    assert 'bash "$DIR/01-gateway.sh" --lock-held' in bring_up
    assert 'bash "$DIR/02-provider.sh" --lock-held' in bring_up
    assert 'bash "$DIR/03-sandbox.sh" --lock-held' in bring_up
    assert "acquire_review_lock" in sandbox
    assert "--lock-held requires the inherited lifecycle lock" in sandbox
    assert "assert_runtime_fingerprint" in sandbox
    assert "acquire_review_lock" in tear_down
