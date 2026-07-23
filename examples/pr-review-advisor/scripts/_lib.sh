#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
if [[ "$(basename "$RUNTIME_DIR")" == "runtime" && -f "$RUNTIME_DIR/../config.yaml" ]]; then
  INSTALL_DIR="$(cd "$RUNTIME_DIR/.." && pwd)"
else
  INSTALL_DIR="$RUNTIME_DIR"
fi
# shellcheck disable=SC2034
EXAMPLE_DIR="$RUNTIME_DIR"
STATE_DIR=""
# shellcheck disable=SC2034
SNAPSHOT_DIR=""
REVIEW_ADVISOR_ENV_KEYS="|"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    return 1
  }
}

validate_name() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$ ]] || {
    echo "Unsafe name: $1" >&2
    return 1
  }
}

validate_port() {
  if [[ ! "$1" =~ ^[0-9]+$ ]] || ((10#$1 < 1024 || 10#$1 > 65535)); then
    echo "Port must be an integer from 1024 through 65535: $1" >&2
    return 1
  fi
}

validate_integer_range() {
  local value="$1"
  local minimum="$2"
  local maximum="$3"
  local label="$4"
  if [[ ! "$value" =~ ^[0-9]+$ ]] \
      || ((10#$value < minimum || 10#$value > maximum)); then
    echo "$label must be an integer from $minimum through $maximum: $value" >&2
    return 1
  fi
}

validate_sha() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]] || {
    echo "Expected a lowercase full Git commit SHA, got: $1" >&2
    return 1
  }
}

env_file_has() {
  [[ "$REVIEW_ADVISOR_ENV_KEYS" == *"|$1|"* ]]
}

load_env() {
  local load_provider_credentials=0
  if [[ "${1:-}" == "--provider-credentials" ]]; then
    load_provider_credentials=1
    shift
  fi
  [[ $# -eq 0 ]] || {
    echo "load_env accepts only --provider-credentials" >&2
    return 2
  }
  require_command python3
  local env_file="${INSTALL_DIR}/.env"
  local config_file="${INSTALL_DIR}/config.yaml"
  local parsed key value identity

  # Never honor ambient values for advisor configuration or the direct-endpoint
  # OpenShell escape hatch. The only credential exception is captured explicitly
  # by 02-provider.sh before this function scrubs the process environment.
  unset \
    REVIEW_ADVISOR_PROVIDER_MODE REVIEW_ADVISOR_EXISTING_PROVIDER_TYPE \
    NVIDIA_INFERENCE_API_KEY COMPATIBLE_API_KEY \
    NEMOCLAW_ENDPOINT_URL NEMOCLAW_MODEL NEMOCLAW_SANDBOX_NAME \
    INFERENCE_PROVIDER_NAME HERMES_FORWARD_PORT \
    OPENSHELL_GATEWAY OPENSHELL_GATEWAY_ENDPOINT OPENSHELL_GATEWAY_INSECURE \
    REVIEW_ADVISOR_STATE_ROOT REVIEW_ADVISOR_STATE_DIR \
    REVIEW_ADVISOR_SNAPSHOT_DIR REVIEW_ADVISOR_MAX_FILES \
    REVIEW_ADVISOR_MAX_CONTEXT_BYTES REVIEW_ADVISOR_MAX_CHECKOUT_FILES \
    REVIEW_ADVISOR_MAX_CHECKOUT_BYTES REVIEW_ADVISOR_INSTALL_ID \
    REVIEW_ADVISOR_REPOSITORY REVIEW_ADVISOR_RUNTIME_FINGERPRINT

  [[ -e "$env_file" || -L "$env_file" ]] || {
    echo "Review advisor requires a private configuration file: $env_file" >&2
    return 1
  }
  parsed="$(
    python3 - "$env_file" "$load_provider_credentials" <<'PY'
import os
import re
import stat
import sys

path = sys.argv[1]
load_provider_credentials = sys.argv[2] == "1"
secret_keys = {"NVIDIA_INFERENCE_API_KEY", "COMPATIBLE_API_KEY"}
allowed = {
    "REVIEW_ADVISOR_PROVIDER_MODE",
    "REVIEW_ADVISOR_EXISTING_PROVIDER_TYPE",
    "NVIDIA_INFERENCE_API_KEY",
    "COMPATIBLE_API_KEY",
    "NEMOCLAW_ENDPOINT_URL",
    "NEMOCLAW_MODEL",
    "NEMOCLAW_SANDBOX_NAME",
    "INFERENCE_PROVIDER_NAME",
    "HERMES_FORWARD_PORT",
    "OPENSHELL_GATEWAY",
    "OPENSHELL_GATEWAY_ENDPOINT",
    "REVIEW_ADVISOR_STATE_ROOT",
    "REVIEW_ADVISOR_MAX_FILES",
    "REVIEW_ADVISOR_MAX_CONTEXT_BYTES",
    "REVIEW_ADVISOR_MAX_CHECKOUT_FILES",
    "REVIEW_ADVISOR_MAX_CHECKOUT_BYTES",
}
info = os.lstat(path)
if not stat.S_ISREG(info.st_mode):
    raise SystemExit(f"Review advisor .env must be a regular non-symlink file: {path}")
if info.st_uid != os.geteuid():
    raise SystemExit(f"Review advisor .env must be owned by uid {os.geteuid()}: {path}")
if stat.S_IMODE(info.st_mode) & 0o077:
    raise SystemExit(f"Review advisor .env must have mode 0600 or stricter: {path}")
if info.st_size > 65_536:
    raise SystemExit("Review advisor .env exceeds 65536 bytes")
raw = open(path, "rb").read(65_537)
if len(raw) > 65_536:
    raise SystemExit("Review advisor .env exceeds 65536 bytes")
if b"\r" in raw or any(byte < 0x20 and byte not in (0x0A,) for byte in raw):
    raise SystemExit("Review advisor .env contains a control character")
try:
    text = raw.decode("utf-8")
except UnicodeDecodeError as error:
    raise SystemExit("Review advisor .env must be UTF-8") from error

seen = set()
for line_number, line in enumerate(text.splitlines(), 1):
    if len(line.encode("utf-8")) > 4096:
        raise SystemExit(f"Review advisor .env line {line_number} exceeds 4096 bytes")
    if not line or line.startswith("#"):
        continue
    match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=(.*)", line)
    if not match:
        raise SystemExit(
            f"Review advisor .env line {line_number} must be an exact KEY=value assignment"
        )
    key, value = match.groups()
    if key not in allowed:
        raise SystemExit(f"Review advisor .env contains unknown key: {key}")
    if key in seen:
        raise SystemExit(f"Review advisor .env contains duplicate key: {key}")
    if value != value.strip():
        raise SystemExit(f"Review advisor .env value has surrounding whitespace: {key}")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise SystemExit(f"Review advisor .env contains a control character: {key}")
    if any(character in value for character in ("$", "`", ";", "&", "|", "<", ">", "\\", "'", '"')):
        raise SystemExit(f"Review advisor .env contains forbidden shell syntax: {key}")
    seen.add(key)
    if key in secret_keys and not load_provider_credentials:
        # Every non-provider lifecycle process learns only that the allowlisted
        # key was present; its value remains confined to this short parser.
        value = ""
    print(f"{key}\t{value}")
PY
  )"

  REVIEW_ADVISOR_ENV_KEYS="|"
  while IFS=$'\t' read -r key value; do
    [[ -n "$key" ]] || continue
    printf -v "$key" '%s' "$value"
    REVIEW_ADVISOR_ENV_KEYS+="${key}|"
  done <<<"$parsed"

  identity="$(
    python3 - "$config_file" "$INSTALL_DIR" <<'PY'
import hashlib
import json
import os
import re
import stat
import sys

path, install = sys.argv[1:]
info = os.lstat(path)
if not stat.S_ISREG(info.st_mode):
    raise SystemExit(f"Review advisor config must be a regular non-symlink file: {path}")
if info.st_size > 65_536:
    raise SystemExit("Review advisor config exceeds 65536 bytes")
raw = open(path, "rb").read(65_537)
if len(raw) > 65_536:
    raise SystemExit("Review advisor config exceeds 65536 bytes")
try:
    text = raw.decode("utf-8")
except UnicodeDecodeError as error:
    raise SystemExit("Review advisor config must be UTF-8") from error
matches = re.findall(r"^repository:[ \t]*(.+?)[ \t]*$", text, re.MULTILINE)
if len(matches) != 1:
    raise SystemExit("Review advisor config must contain exactly one repository identity")
try:
    repository = json.loads(matches[0])
except json.JSONDecodeError as error:
    raise SystemExit("Review advisor repository identity must be a JSON-quoted YAML scalar") from error
if not isinstance(repository, str) or not re.fullmatch(
    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
):
    raise SystemExit("Review advisor config contains an invalid repository identity")
install_id = hashlib.sha256(
    os.path.realpath(install).encode("utf-8") + b"\0" + repository.encode("utf-8")
).hexdigest()[:16]
print(f"{install_id}\t{repository}")
PY
  )"
  IFS=$'\t' read -r REVIEW_ADVISOR_INSTALL_ID REVIEW_ADVISOR_REPOSITORY <<<"$identity"
  [[ "$REVIEW_ADVISOR_INSTALL_ID" =~ ^[0-9a-f]{16}$ ]] || {
    echo "Could not derive the review advisor install identity" >&2
    return 1
  }
  export REVIEW_ADVISOR_INSTALL_ID REVIEW_ADVISOR_REPOSITORY

  local state_root default_port
  state_root="${REVIEW_ADVISOR_STATE_ROOT:-${XDG_STATE_HOME:-${HOME}/.local/state}/nemoclaw-review-advisor}"
  [[ "$state_root" == /* ]] || {
    echo "REVIEW_ADVISOR_STATE_ROOT must be absolute" >&2
    return 1
  }
  STATE_DIR="${state_root}/${REVIEW_ADVISOR_INSTALL_ID}/runtime"
  SNAPSHOT_DIR="${state_root}/${REVIEW_ADVISOR_INSTALL_ID}/snapshots"
  export STATE_DIR SNAPSHOT_DIR

  default_port="$((20000 + 16#${REVIEW_ADVISOR_INSTALL_ID:0:4} % 20000))"
  NEMOCLAW_SANDBOX_NAME="${NEMOCLAW_SANDBOX_NAME:-pr-review-${REVIEW_ADVISOR_INSTALL_ID}}"
  INFERENCE_PROVIDER_NAME="${INFERENCE_PROVIDER_NAME:-pr-review-inference-${REVIEW_ADVISOR_INSTALL_ID}}"
  OPENSHELL_GATEWAY="${OPENSHELL_GATEWAY:-pr-review-gateway-${REVIEW_ADVISOR_INSTALL_ID}}"
  HERMES_FORWARD_PORT="${HERMES_FORWARD_PORT:-$default_port}"
  REVIEW_ADVISOR_PROVIDER_MODE="${REVIEW_ADVISOR_PROVIDER_MODE:-nvidia}"
  REVIEW_ADVISOR_MAX_FILES="${REVIEW_ADVISOR_MAX_FILES:-512}"
  REVIEW_ADVISOR_MAX_CONTEXT_BYTES="${REVIEW_ADVISOR_MAX_CONTEXT_BYTES:-33554432}"
  REVIEW_ADVISOR_MAX_CHECKOUT_FILES="${REVIEW_ADVISOR_MAX_CHECKOUT_FILES:-50000}"
  REVIEW_ADVISOR_MAX_CHECKOUT_BYTES="${REVIEW_ADVISOR_MAX_CHECKOUT_BYTES:-536870912}"

  [[ -n "${OPENSHELL_GATEWAY_ENDPOINT:-}" ]] || {
    echo "Set a dedicated OPENSHELL_GATEWAY_ENDPOINT in $env_file" >&2
    return 1
  }
  OPENSHELL_GATEWAY_ENDPOINT="$(
    python3 - "$OPENSHELL_GATEWAY_ENDPOINT" <<'PY'
import ipaddress
import sys
import urllib.parse

value = sys.argv[1]
parsed = urllib.parse.urlsplit(value)
try:
    address = ipaddress.ip_address(parsed.hostname or "")
    port = parsed.port
except ValueError as error:
    raise SystemExit(
        "OPENSHELL_GATEWAY_ENDPOINT must use a literal loopback IP and explicit port"
    ) from error
if (
    parsed.scheme != "https"
    or not address.is_loopback
    or port is None
    or not 1024 <= port <= 65535
    or parsed.username is not None
    or parsed.password is not None
    or parsed.query
    or parsed.fragment
    or parsed.path not in ("", "/")
):
    raise SystemExit(
        "OPENSHELL_GATEWAY_ENDPOINT must be a dedicated HTTPS loopback origin"
    )
host = f"[{address}]" if address.version == 6 else str(address)
print(f"https://{host}:{port}")
PY
  )"
  export -n OPENSHELL_GATEWAY_ENDPOINT 2>/dev/null || true

  case "$REVIEW_ADVISOR_PROVIDER_MODE" in
    nvidia)
      NEMOCLAW_ENDPOINT_URL="${NEMOCLAW_ENDPOINT_URL:-https://integrate.api.nvidia.com/v1}"
      NEMOCLAW_MODEL="${NEMOCLAW_MODEL:-nvidia/nvidia/nemotron-3-ultra}"
      ;;
    openai-compatible)
      [[ -n "${NEMOCLAW_ENDPOINT_URL:-}" && -n "${NEMOCLAW_MODEL:-}" ]] || {
        echo "openai-compatible mode requires NEMOCLAW_ENDPOINT_URL and NEMOCLAW_MODEL" >&2
        return 1
      }
      ;;
    existing)
      [[ -n "${INFERENCE_PROVIDER_NAME:-}" \
          && -n "${REVIEW_ADVISOR_EXISTING_PROVIDER_TYPE:-}" \
          && -n "${NEMOCLAW_MODEL:-}" ]] || {
        echo "existing mode requires INFERENCE_PROVIDER_NAME, REVIEW_ADVISOR_EXISTING_PROVIDER_TYPE, and NEMOCLAW_MODEL" >&2
        return 1
      }
      if [[ -n "${NEMOCLAW_ENDPOINT_URL:-}" ]]; then
        echo "existing mode forbids NEMOCLAW_ENDPOINT_URL" >&2
        return 1
      fi
      ;;
    *)
      echo "REVIEW_ADVISOR_PROVIDER_MODE must be nvidia, openai-compatible, or existing" >&2
      return 1
      ;;
  esac

  validate_name "$NEMOCLAW_SANDBOX_NAME"
  validate_name "$INFERENCE_PROVIDER_NAME"
  validate_name "$OPENSHELL_GATEWAY"
  if [[ -n "${REVIEW_ADVISOR_EXISTING_PROVIDER_TYPE:-}" ]]; then
    validate_name "$REVIEW_ADVISOR_EXISTING_PROVIDER_TYPE"
  fi
  validate_port "$HERMES_FORWARD_PORT"
  validate_integer_range "$REVIEW_ADVISOR_MAX_FILES" 1 10000 REVIEW_ADVISOR_MAX_FILES
  validate_integer_range \
    "$REVIEW_ADVISOR_MAX_CONTEXT_BYTES" 1 268435456 REVIEW_ADVISOR_MAX_CONTEXT_BYTES
  validate_integer_range \
    "$REVIEW_ADVISOR_MAX_CHECKOUT_FILES" 1 1000000 REVIEW_ADVISOR_MAX_CHECKOUT_FILES
  validate_integer_range \
    "$REVIEW_ADVISOR_MAX_CHECKOUT_BYTES" 1 8589934592 REVIEW_ADVISOR_MAX_CHECKOUT_BYTES
  [[ "$NEMOCLAW_MODEL" =~ ^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$ ]] || {
    echo "NEMOCLAW_MODEL contains unsafe characters" >&2
    return 1
  }
  if [[ -n "${NEMOCLAW_ENDPOINT_URL:-}" ]]; then
    python3 - "$NEMOCLAW_ENDPOINT_URL" <<'PY'
import ipaddress
import sys
import urllib.parse

value = sys.argv[1]
parsed = urllib.parse.urlsplit(value)
if (
    parsed.scheme not in ("http", "https")
    or not parsed.hostname
    or parsed.username is not None
    or parsed.password is not None
    or parsed.query
    or parsed.fragment
):
    raise SystemExit("NEMOCLAW_ENDPOINT_URL must be an uncredentialed HTTP(S) URL")
if parsed.scheme == "http":
    if parsed.hostname == "host.openshell.internal":
        pass
    else:
        try:
            if not ipaddress.ip_address(parsed.hostname).is_loopback:
                raise SystemExit(
                    "plaintext NEMOCLAW_ENDPOINT_URL is allowed only on "
                    "host.openshell.internal or a literal loopback IP"
                )
        except ValueError as error:
            raise SystemExit(
                "plaintext NEMOCLAW_ENDPOINT_URL is allowed only on "
                "host.openshell.internal or a literal loopback IP"
            ) from error
PY
  fi
}

scrub_external_secrets() {
  unset \
    NEMOCLAW_GITHUB_TOKEN GH_TOKEN GITHUB_TOKEN GITHUB_PAT \
    NVIDIA_INFERENCE_API_KEY NVIDIA_API_KEY NGC_API_KEY COMPATIBLE_API_KEY \
    OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY TOGETHER_API_KEY \
    GROQ_API_KEY MISTRAL_API_KEY COHERE_API_KEY GOOGLE_API_KEY GEMINI_API_KEY \
    AZURE_OPENAI_API_KEY AZURE_API_KEY DEEPINFRA_API_KEY \
    HF_TOKEN HUGGING_FACE_HUB_TOKEN \
    AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
}

openshell_preflight() {
  require_command openshell
  local version
  version="$(command openshell -V 2>/dev/null)" || {
    echo "Could not determine the OpenShell version" >&2
    return 1
  }
  [[ "$version" == "openshell 0.0.85" ]] || {
    echo "Review advisor requires exactly openshell 0.0.85 (found: $version)" >&2
    return 1
  }
}

run_openshell_unbound() {
  openshell_preflight
  (
    unset OPENSHELL_GATEWAY OPENSHELL_GATEWAY_ENDPOINT OPENSHELL_GATEWAY_INSECURE
    command openshell "$@"
  )
}

run_openshell() {
  openshell_preflight
  local gateway_name="$OPENSHELL_GATEWAY"
  (
    unset OPENSHELL_GATEWAY OPENSHELL_GATEWAY_ENDPOINT OPENSHELL_GATEWAY_INSECURE
    command openshell -g "$gateway_name" "$@"
  )
}

run_openshell_detached() {
  openshell_preflight
  local gateway_name="$OPENSHELL_GATEWAY"
  (
    unset OPENSHELL_GATEWAY OPENSHELL_GATEWAY_ENDPOINT OPENSHELL_GATEWAY_INSECURE
    exec setsid openshell -g "$gateway_name" "$@"
  )
}

gateway_registration_exists() {
  local registrations
  registrations="$(run_openshell_unbound gateway list -o json)"
  (( ${#registrations} <= 65536 )) || {
    echo "OpenShell gateway list output exceeded 65536 bytes" >&2
    return 1
  }
  python3 - "$OPENSHELL_GATEWAY" "$registrations" <<'PY'
import json
import sys

name, raw = sys.argv[1:]
try:
    value = json.loads(raw)
except json.JSONDecodeError as error:
    print(f"OpenShell gateway list returned invalid JSON: {error}", file=sys.stderr)
    raise SystemExit(2)
if not isinstance(value, list):
    print("OpenShell gateway list did not return a JSON array", file=sys.stderr)
    raise SystemExit(2)
matches = [item for item in value if isinstance(item, dict) and item.get("name") == name]
if len(matches) > 1:
    print("OpenShell gateway name is ambiguous", file=sys.stderr)
    raise SystemExit(2)
raise SystemExit(0 if matches else 1)
PY
}

assert_gateway_identity() {
  local info registrations
  info="$(run_openshell gateway info -o json)"
  registrations="$(run_openshell_unbound gateway list -o json)"
  (( ${#info} <= 65536 && ${#registrations} <= 65536 )) || {
    echo "OpenShell gateway metadata exceeded 65536 bytes" >&2
    return 1
  }
  python3 - \
    "$OPENSHELL_GATEWAY" "$OPENSHELL_GATEWAY_ENDPOINT" "$info" "$registrations" <<'PY'
import json
import sys

name, endpoint, info_raw, registrations_raw = sys.argv[1:]
info = json.loads(info_raw)
registrations = json.loads(registrations_raw)
if not isinstance(info, dict) or not isinstance(registrations, list):
    raise SystemExit("OpenShell gateway metadata has an invalid JSON shape")
if info.get("gateway") != name or info.get("server") != endpoint:
    raise SystemExit("OpenShell gateway name does not resolve to the dedicated endpoint")
matches = [
    item
    for item in registrations
    if isinstance(item, dict)
    and item.get("name") == name
    and item.get("endpoint") == endpoint
]
if len(matches) != 1:
    raise SystemExit("OpenShell gateway registration is missing or ambiguous")
collisions = [
    item.get("name")
    for item in registrations
    if isinstance(item, dict)
    and item.get("endpoint") == endpoint
    and item.get("name") != name
]
if collisions:
    raise SystemExit(
        "Dedicated OpenShell gateway endpoint is registered under another name: "
        + ", ".join(str(value) for value in collisions)
    )
PY
}

provider_metadata_json() {
  local providers
  providers="$(run_openshell provider list --limit 1001 -o json)"
  (( ${#providers} <= 262144 )) || {
    echo "OpenShell provider list output exceeded 262144 bytes" >&2
    return 1
  }
  printf '%s' "$providers"
}

provider_exists() {
  local providers
  providers="$(provider_metadata_json)"
  python3 - "$INFERENCE_PROVIDER_NAME" "$providers" <<'PY'
import json
import sys

name, raw = sys.argv[1:]
try:
    providers = json.loads(raw)
except json.JSONDecodeError as error:
    print(f"OpenShell provider list returned invalid JSON: {error}", file=sys.stderr)
    raise SystemExit(2)
if not isinstance(providers, list):
    print("OpenShell provider list did not return a JSON array", file=sys.stderr)
    raise SystemExit(2)
if len(providers) >= 1001:
    print("OpenShell provider registry is too large to validate exactly", file=sys.stderr)
    raise SystemExit(2)
matches = [item for item in providers if isinstance(item, dict) and item.get("name") == name]
if len(matches) > 1:
    print("OpenShell provider name is ambiguous", file=sys.stderr)
    raise SystemExit(2)
raise SystemExit(0 if matches else 1)
PY
}

assert_provider_metadata() {
  local expected_type="$1"
  local expected_credential_key="${2:-}"
  local expected_config_key="${3:-}"
  local providers
  providers="$(provider_metadata_json)"
  python3 - \
    "$INFERENCE_PROVIDER_NAME" "$expected_type" \
    "$expected_credential_key" "$expected_config_key" "$providers" <<'PY'
import json
import sys

name, expected_type, credential_key, config_key, raw = sys.argv[1:]
providers = json.loads(raw)
if not isinstance(providers, list):
    raise SystemExit("OpenShell provider list did not return a JSON array")
if len(providers) >= 1001:
    raise SystemExit("OpenShell provider registry is too large to validate exactly")
matches = [item for item in providers if isinstance(item, dict) and item.get("name") == name]
if len(matches) != 1:
    raise SystemExit("OpenShell provider metadata is missing or ambiguous")
provider = matches[0]
if provider.get("type") != expected_type:
    raise SystemExit(
        f"OpenShell provider type mismatch: expected {expected_type}, "
        f"got {provider.get('type')}"
    )
if not isinstance(provider.get("id"), str) or not provider["id"]:
    raise SystemExit("OpenShell provider metadata is missing its object id")
if not isinstance(provider.get("resource_version"), int) or provider["resource_version"] < 1:
    raise SystemExit("OpenShell provider metadata has no resource version")
credentials = provider.get("credential_keys", [])
configs = provider.get("config_keys", [])
if credential_key and credentials != [credential_key]:
    raise SystemExit("OpenShell provider credential-key metadata does not match")
if config_key and configs != [config_key]:
    raise SystemExit("OpenShell provider config-key metadata does not match")
PY
}

assert_inference_route() {
  # OpenShell's user-facing inference route is gateway-wide. The advisor
  # therefore binds every operation to one explicitly dedicated gateway.
  local route
  route="$(run_openshell inference get)"
  (( ${#route} <= 32768 )) || {
    echo "OpenShell inference output exceeded 32768 bytes" >&2
    return 1
  }
  python3 - "$INFERENCE_PROVIDER_NAME" "$NEMOCLAW_MODEL" "$route" <<'PY'
import re
import sys

provider, model, raw = sys.argv[1:]
raw = re.sub(r"\x1b\[[0-9;]*m", "", raw)
match = re.search(
    r"(?ms)^Gateway inference:\s*$"
    r"(?P<body>.*?)(?=^System inference:\s*$|\Z)",
    raw,
)
if match is None:
    raise SystemExit("OpenShell inference output has no Gateway inference section")
body = match.group("body")
providers = re.findall(r"(?m)^\s*Provider:\s*(\S+)\s*$", body)
models = re.findall(r"(?m)^\s*Model:\s*(\S+)\s*$", body)
if providers != [provider] or models != [model]:
    raise SystemExit(
        "OpenShell gateway inference route mismatch: "
        f"expected provider={provider} model={model}"
    )
PY
}

sandbox_phase() {
  local name="${1:-$NEMOCLAW_SANDBOX_NAME}"
  local sandboxes
  scrub_external_secrets
  sandboxes="$(run_openshell sandbox list --limit 1001 -o json)"
  (( ${#sandboxes} <= 262144 )) || {
    echo "OpenShell sandbox list output exceeded 262144 bytes" >&2
    return 1
  }
  python3 - "$name" "$sandboxes" <<'PY'
import json
import sys

name, raw = sys.argv[1:]
value = json.loads(raw)
if not isinstance(value, list):
    raise SystemExit("OpenShell sandbox list did not return a JSON array")
if len(value) >= 1001:
    raise SystemExit("OpenShell sandbox registry is too large to validate exactly")
matches = [item for item in value if isinstance(item, dict) and item.get("name") == name]
if not matches:
    print("Missing")
elif len(matches) != 1 or not isinstance(matches[0].get("phase"), str):
    raise SystemExit("OpenShell sandbox identity is ambiguous")
else:
    print(matches[0]["phase"])
PY
}

compute_runtime_fingerprint() {
  local fingerprint
  fingerprint="$(
    python3 - "$EXAMPLE_DIR" "$REVIEW_ADVISOR_INSTALL_ID" \
      "$REVIEW_ADVISOR_REPOSITORY" "$NEMOCLAW_MODEL" <<'PY'
import hashlib
import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
install_id, repository, model = sys.argv[2:]
single_files = (
    "agents/hermes/Dockerfile",
    "agents/hermes/generate-config.ts",
    "agents/hermes/start.sh",
    "agents/hermes/probe-inference.py",
    "agents/hermes/record-feedback.py",
    "agents/hermes/SOUL.md",
)
trees = (
    "agents/hermes/plugins/review-advisor",
    "skills/pr-review",
    "schemas",
    "review-profiles",
)
paths = [root / relative for relative in single_files]
for relative in trees:
    base = root / relative
    info = os.lstat(base)
    if not stat.S_ISDIR(info.st_mode):
        raise SystemExit(f"runtime fingerprint root is not a directory: {base}")
    for parent, directory_names, file_names in os.walk(base, followlinks=False):
        directory_names[:] = sorted(
            name for name in directory_names if name != "__pycache__"
        )
        for directory_name in directory_names:
            directory = Path(parent) / directory_name
            if directory.is_symlink():
                raise SystemExit(f"runtime fingerprint rejects symlink: {directory}")
        for file_name in sorted(file_names):
            if file_name.endswith((".pyc", ".pyo")):
                continue
            paths.append(Path(parent) / file_name)

digest = hashlib.sha256()
for label, value in (
    ("install_id", install_id),
    ("repository", repository),
    ("model", model),
):
    encoded = value.encode("utf-8")
    digest.update(label.encode("ascii") + b"\0")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)
for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise SystemExit(f"runtime fingerprint rejects non-regular file: {path}")
    relative = path.relative_to(root).as_posix().encode("utf-8")
    digest.update(b"file\0")
    digest.update(len(relative).to_bytes(8, "big"))
    digest.update(relative)
    digest.update(info.st_size.to_bytes(8, "big"))
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
print(digest.hexdigest())
PY
  )"
  [[ "$fingerprint" =~ ^[0-9a-f]{64}$ ]] || {
    echo "Could not compute the review advisor runtime fingerprint" >&2
    return 1
  }
  REVIEW_ADVISOR_RUNTIME_FINGERPRINT="$fingerprint"
  export REVIEW_ADVISOR_RUNTIME_FINGERPRINT
}

assert_runtime_fingerprint() {
  compute_runtime_fingerprint
  local observed
  observed="$(
    run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
      cat /opt/review-advisor/runtime-fingerprint
  )"
  [[ "$observed" == "$REVIEW_ADVISOR_RUNTIME_FINGERPRINT" ]] || {
    echo "Sandbox runtime fingerprint does not match this installation; refusing to reuse it" >&2
    echo "Snapshot memory and explicitly destroy/recreate the sandbox if replacement is intended." >&2
    return 1
  }
}

assert_sandbox_ready() {
  local phase
  assert_gateway_identity
  phase="$(sandbox_phase)"
  [[ "${phase,,}" == "ready" ]] || {
    echo "Sandbox $NEMOCLAW_SANDBOX_NAME is not ready (phase: $phase)" >&2
    echo "Run: bash ${SCRIPT_DIR}/bring-up.sh" >&2
    return 1
  }
  assert_runtime_fingerprint
}

ensure_api_key() {
  local key_file="${STATE_DIR}/api-key"
  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR"
  if [[ ! -f "$key_file" ]]; then
    (
      umask 077
      python3 - <<'PY' >"$key_file"
import secrets
print(secrets.token_urlsafe(36))
PY
    )
  fi
  chmod 600 "$key_file"
  REVIEW_ADVISOR_API_KEY="$(<"$key_file")"
  [[ "$REVIEW_ADVISOR_API_KEY" =~ ^[A-Za-z0-9_-]{32,128}$ ]] || {
    echo "Invalid local Hermes API key file: $key_file" >&2
    return 1
  }
  export -n REVIEW_ADVISOR_API_KEY 2>/dev/null || true
}

assert_forward_mapping() {
  local forwards
  forwards="$(run_openshell forward list 2>&1)"
  (( ${#forwards} <= 65536 )) || {
    echo "OpenShell forward list output exceeded 65536 bytes" >&2
    return 1
  }
  python3 - "$NEMOCLAW_SANDBOX_NAME" "$HERMES_FORWARD_PORT" "$forwards" <<'PY'
import re
import sys

sandbox, port, raw = sys.argv[1:]
raw = re.sub(r"\x1b\[[0-9;]*m", "", raw)
matches = []
for line in raw.splitlines():
    fields = line.split()
    if len(fields) == 5 and fields[2] == port:
        matches.append(fields)
if len(matches) != 1:
    raise SystemExit("OpenShell forward port is missing or ambiguously mapped")
row = matches[0]
if row[0] != sandbox or row[1] != "127.0.0.1" or row[4].lower() != "running":
    raise SystemExit(
        "OpenShell forward does not map the exact loopback port to the advisor sandbox"
    )
PY
}

assert_hermes_api_surface() {
  ensure_api_key
  python3 - \
    "http://127.0.0.1:${HERMES_FORWARD_PORT}" \
    "$STATE_DIR/api-key" "$NEMOCLAW_MODEL" <<'PY'
import json
import os
import stat
import sys
import time
import urllib.error
import urllib.request

base_url, key_path, expected_model = sys.argv[1:]
flags = os.O_RDONLY
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
descriptor = os.open(key_path, flags)
try:
    info = os.fstat(descriptor)
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) & 0o077
        or info.st_size > 256
    ):
        raise SystemExit("Hermes API key file is not a bounded private regular file")
    raw_key = os.read(descriptor, 257)
    if len(raw_key) > 256:
        raise SystemExit("Hermes API key file exceeds 256 bytes")
finally:
    os.close(descriptor)
try:
    api_key = raw_key.decode("ascii").strip()
except UnicodeDecodeError as error:
    raise SystemExit("Hermes API key must be ASCII") from error


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def read_bounded(response, maximum):
    raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise RuntimeError(f"Hermes control response exceeds {maximum} bytes")
    return raw


def request_json(path, authenticated):
    headers = {"Accept": "application/json"}
    if authenticated:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(base_url + path, headers=headers)
    with opener.open(request, timeout=2) as response:
        return json.loads(read_bounded(response, 262_144))


deadline = time.monotonic() + 60
while True:
    try:
        capabilities = request_json("/v1/capabilities", True)
        break
    except urllib.error.HTTPError as error:
        read_bounded(error, 16_384)
        raise SystemExit(
            f"Hermes authenticated capabilities returned HTTP {error.code}"
        ) from error
    except (OSError, urllib.error.URLError):
        if time.monotonic() >= deadline:
            raise SystemExit("Hermes authenticated capabilities endpoint did not become ready")
        time.sleep(1)

try:
    request_json("/v1/capabilities", False)
except urllib.error.HTTPError as error:
    read_bounded(error, 16_384)
    if error.code != 401:
        raise SystemExit(f"Hermes unauthenticated capabilities returned HTTP {error.code}")
else:
    raise SystemExit("Hermes capabilities endpoint did not require authentication")

if (
    not isinstance(capabilities, dict)
    or capabilities.get("object") != "hermes.api_server.capabilities"
    or capabilities.get("platform") != "hermes-agent"
    or capabilities.get("model") != expected_model
    or capabilities.get("auth") != {"type": "bearer", "required": True}
    or capabilities.get("runtime", {}).get("mode") != "server_agent"
    or capabilities.get("runtime", {}).get("tool_execution") != "server"
    or capabilities.get("runtime", {}).get("split_runtime") is not False
    or capabilities.get("endpoints", {}).get("chat_completions")
       != {"method": "POST", "path": "/v1/chat/completions"}
    or capabilities.get("endpoints", {}).get("session_delete")
       != {"method": "DELETE", "path": "/api/sessions/{session_id}"}
):
    raise SystemExit("Hermes capabilities do not match the review advisor contract")

toolsets = request_json("/v1/toolsets", True)
if (
    not isinstance(toolsets, dict)
    or toolsets.get("object") != "list"
    or toolsets.get("platform") != "api_server"
    or not isinstance(toolsets.get("data"), list)
):
    raise SystemExit("Hermes toolset response has an invalid shape")
enabled = [
    item
    for item in toolsets["data"]
    if isinstance(item, dict) and item.get("enabled") is True
]
expected_tools = {
    "review_begin",
    "review_status",
    "review_repo_read",
    "review_repo_list",
    "review_repo_search",
    "review_diff",
    "review_commit_stage",
    "review_finalize",
}
if (
    len(enabled) != 1
    or enabled[0].get("name") != "review-advisor"
    or enabled[0].get("configured") is not True
    or not isinstance(enabled[0].get("tools"), list)
    or len(enabled[0]["tools"]) != len(expected_tools)
    or set(enabled[0]["tools"]) != expected_tools
):
    raise SystemExit("Hermes API exposes an unexpected enabled toolset or tool surface")
PY
}

start_forward() {
  local log="${STATE_DIR}/hermes-forward.log"
  scrub_external_secrets
  assert_gateway_identity
  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR"
  run_openshell forward start --background "127.0.0.1:${HERMES_FORWARD_PORT}" \
    "$NEMOCLAW_SANDBOX_NAME" >"$log" 2>&1 || true
  chmod 600 "$log" 2>/dev/null || true
  local mapping_ready=0
  for _ in $(seq 1 20); do
    if assert_forward_mapping >/dev/null 2>&1; then
      mapping_ready=1
      break
    fi
    sleep 0.25
  done
  if [[ "$mapping_ready" != 1 ]]; then
    assert_forward_mapping || true
    echo "Could not prove the exact OpenShell forward mapping" >&2
    cat "$log" >&2 2>/dev/null || true
    return 1
  fi
  assert_hermes_api_surface
}

sha256_file() {
  python3 - "$1" <<'PY'
import hashlib
import os
import stat
import sys

path = sys.argv[1]
info = os.lstat(path)
if not stat.S_ISREG(info.st_mode):
    raise SystemExit(f"not a regular file: {path}")
digest = hashlib.sha256()
with open(path, "rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
}

acquire_review_lock() {
  local lock="${STATE_DIR}/review.lock"
  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR"
  if ! mkdir "$lock" 2>/dev/null; then
    echo "Another review lifecycle operation is active: $lock" >&2
    return 1
  fi
  REVIEW_ADVISOR_LOCK_DIR="$lock"
  export REVIEW_ADVISOR_LOCK_DIR
}

release_review_lock() {
  if [[ -n "${REVIEW_ADVISOR_LOCK_DIR:-}" && -d "$REVIEW_ADVISOR_LOCK_DIR" ]]; then
    rmdir "$REVIEW_ADVISOR_LOCK_DIR" 2>/dev/null || true
  fi
}
