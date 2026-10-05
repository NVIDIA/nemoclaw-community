#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -Eeuo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SANDBOX_NAME="${NEMOCLAW_SANDBOX_NAME:-ask-nemoclaw}"
NEMOCLAW_SOURCE="${NEMOCLAW_SOURCE:-}"

# The Brev launchable may retain older system binaries after the maintained
# installer places current binaries under ~/.local/bin. Prefer the current
# user-local installation explicitly instead of depending on shell PATH order.
NEMOHERMES_BIN="${NEMOHERMES_BIN:-$HOME/.local/bin/nemohermes}"
OPENSHELL_BIN="${OPENSHELL_BIN:-$HOME/.local/bin/openshell}"
[[ -x "$NEMOHERMES_BIN" ]] || NEMOHERMES_BIN="$(command -v nemohermes || true)"
[[ -x "$OPENSHELL_BIN" ]] || OPENSHELL_BIN="$(command -v openshell || true)"

# Current NemoClaw requires a version-matched OpenShell gateway for provider
# and inference-route configuration. After prepare-brev-gateway.sh performs
# the explicit lifecycle handoff, select NemoClaw-managed mode. NemoClaw then
# uses the native gateway when it is compatible with the host and requires an
# explicit opt-in before using its compatibility-container mode.
GATEWAY_WILL_START=0
if [[ -r /etc/nemoclaw/gateway-management.env ]]; then
  if [[ "$(systemctl is-active openshell-gateway.service 2>/dev/null || true)" == active ]]; then
    cat >&2 <<'EOF'
The legacy Brev OpenShell gateway is still active. Run
`bash scripts/prepare-brev-gateway.sh` before onboarding so the current
NemoClaw installation can own a version-matched gateway.
EOF
    exit 1
  fi
  export NEMOCLAW_GATEWAY_MANAGEMENT="$ROOT/deploy/brev/nemoclaw-managed-gateway.json"
  # The launchable's interactive shell exports these paths for its retired
  # externally supervised gateway. They must not override the current managed
  # gateway's user-owned state and generated TLS bundle.
  unset NEMOCLAW_OPENSHELL_GATEWAY_STATE_DIR
  unset OPENSHELL_LOCAL_TLS_DIR
  GATEWAY_WILL_START=1
elif [[ -n "${NEMOCLAW_GATEWAY_MANAGEMENT:-}" \
        && -r "$NEMOCLAW_GATEWAY_MANAGEMENT" ]] \
     && grep -Eq '"mode"[[:space:]]*:[[:space:]]*"nemoclaw-managed"' \
        "$NEMOCLAW_GATEWAY_MANAGEMENT"; then
  GATEWAY_WILL_START=1
fi

for required_command in docker python3; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    printf 'Required command is unavailable: %s\n' "$required_command" >&2
    exit 1
  fi
done
for required_path in "$NEMOHERMES_BIN" "$OPENSHELL_BIN"; do
  if [[ -z "$required_path" || ! -x "$required_path" ]]; then
    printf 'Required NemoClaw command is unavailable: %s\n' "$required_path" >&2
    exit 1
  fi
done

DOCKER_DRIVER_STATUS="$(docker info --format '{{json .DriverStatus}}')"
if [[ "$DOCKER_DRIVER_STATUS" == *'io.containerd.snapshotter.v1'* ]]; then
  cat >&2 <<'EOF'
Docker is using the containerd snapshotter, which cannot provide the nested
overlay mounts required by this OpenShell sandbox. Configure Docker to use the
classic overlay2 driver, restart Docker, and rerun this script. See the Brev
host preparation section in README.md for the tested fresh-instance procedure.
EOF
  exit 1
fi

if ((GATEWAY_WILL_START == 0)) && ! "$OPENSHELL_BIN" sandbox list >/dev/null; then
  cat >&2 <<'EOF'
The selected OpenShell gateway is unavailable. Start or register the gateway
owned by the deployment, verify that `openshell sandbox list` succeeds, and
rerun this script.
EOF
  exit 1
fi

if [[ -z "$NEMOCLAW_SOURCE" ]]; then
  if [[ -d "$HOME/.nemoclaw/source/.git" ]]; then
    NEMOCLAW_SOURCE="$HOME/.nemoclaw/source"
  else
    NEMOHERMES_REAL_BIN="$(readlink -f "$NEMOHERMES_BIN")"
    NEMOCLAW_SOURCE="$(CDPATH= cd -- "$(dirname -- "$NEMOHERMES_REAL_BIN")/.." && pwd)"
  fi
fi

python3 "$ROOT/scripts/prepare-hermes-image.py" --nemoclaw-source "$NEMOCLAW_SOURCE"

HERMES_DOCKERFILE="$NEMOCLAW_SOURCE/agents/hermes/Dockerfile"
if [[ ! -r "$HERMES_DOCKERFILE" ]]; then
  printf 'Prepared Hermes Dockerfile is unavailable: %s\n' "$HERMES_DOCKERFILE" >&2
  exit 1
fi
RECREATE_REQUESTED=0
RESUME_REQUESTED=0
FRESH_REQUESTED=0
ONBOARD_ARGS=()
for argument in "$@"; do
  case "$argument" in
    --from|--from=*)
      printf 'Do not pass --from; this recipe selects its prepared Hermes Dockerfile.\n' >&2
      exit 2
      ;;
    --recreate-sandbox)
      RECREATE_REQUESTED=1
      ;;
    --resume)
      RESUME_REQUESTED=1
      ONBOARD_ARGS+=("$argument")
      ;;
    --fresh)
      FRESH_REQUESTED=1
      ONBOARD_ARGS+=("$argument")
      ;;
    *)
      ONBOARD_ARGS+=("$argument")
      ;;
  esac
done

if ((RECREATE_REQUESTED == 1 && RESUME_REQUESTED == 1)); then
  printf '%s\n' '--recreate-sandbox starts a clean onboarding session; do not combine it with --resume.' >&2
  exit 2
fi

printf 'Sandbox name: %s\n' "$SANDBOX_NAME"
printf 'NemoClaw source: %s\n' "$NEMOCLAW_SOURCE"
printf 'NemoHermes command: %s\n' "$NEMOHERMES_BIN"

# Recreating a Hermes sandbox is an explicitly destructive clean replacement
# for this example. Retire orphaned host-side service forwards before removing
# the sandbox so the new instance can bind the same ports. Match the resolved
# OpenShell executable, exact sandbox argument, and loopback endpoints before
# signalling a process. Ordinary onboarding never does this.
if ((RECREATE_REQUESTED == 1)); then
  mapfile -t STALE_FORWARD_PIDS < <(python3 - "$SANDBOX_NAME" "$OPENSHELL_BIN" <<'PY'
import os
from pathlib import Path
import sys

sandbox_name = sys.argv[1]
expected_executable = os.path.realpath(sys.argv[2])
for process in Path("/proc").glob("[0-9]*"):
    try:
        executable = os.path.realpath(process / "exe")
        arguments = [
            value.decode("utf-8", "surrogateescape")
            for value in (process / "cmdline").read_bytes().split(b"\0")
            if value
        ]
    except (OSError, PermissionError):
        continue
    if executable != expected_executable or len(arguments) < 4:
        continue
    try:
        forward_index = arguments.index("forward")
        local_index = arguments.index("--local")
        target_host_index = arguments.index("--target-host")
    except ValueError:
        continue
    if arguments[forward_index : forward_index + 3] != ["forward", "service", sandbox_name]:
        continue
    if local_index + 1 >= len(arguments) or target_host_index + 1 >= len(arguments):
        continue
    local_endpoint = arguments[local_index + 1]
    target_host = arguments[target_host_index + 1]
    if target_host not in {"127.0.0.1", "localhost", "::1"}:
        continue
    if not local_endpoint.startswith(("127.0.0.1:", "localhost:", "[::1]:")):
        continue
    print(process.name)
PY
  )
  if ((${#STALE_FORWARD_PIDS[@]} > 0)); then
    printf 'Releasing %d existing Ask NemoClaw host forward(s) before recreation...\n' \
      "${#STALE_FORWARD_PIDS[@]}"
    kill "${STALE_FORWARD_PIDS[@]}"
    for _ in {1..50}; do
      REMAINING_FORWARD_PIDS=()
      for process_id in "${STALE_FORWARD_PIDS[@]}"; do
        kill -0 "$process_id" 2>/dev/null && REMAINING_FORWARD_PIDS+=("$process_id")
      done
      ((${#REMAINING_FORWARD_PIDS[@]} == 0)) && break
      sleep 0.1
    done
    if ((${#REMAINING_FORWARD_PIDS[@]} > 0)); then
      printf 'OpenShell host forwards did not stop; refusing to recreate the sandbox.\n' >&2
      exit 1
    fi
  fi

  REGISTRY_HAS_SANDBOX="$(python3 - "$HOME/.nemoclaw/sandboxes.json" "$SANDBOX_NAME" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
name = sys.argv[2]
try:
    document = json.loads(path.read_text(encoding="utf-8"))
except (FileNotFoundError, json.JSONDecodeError, OSError):
    print("0")
else:
    print("1" if name in document.get("sandboxes", {}) else "0")
PY
  )"
  LIVE_SANDBOX=0
  if "$OPENSHELL_BIN" sandbox get "$SANDBOX_NAME" >/dev/null 2>&1; then
    LIVE_SANDBOX=1
  fi
  if [[ "$REGISTRY_HAS_SANDBOX" == 1 || "$LIVE_SANDBOX" == 1 ]]; then
    printf "Removing existing example sandbox '%s' for a clean replacement...\n" \
      "$SANDBOX_NAME"
    "$NEMOHERMES_BIN" "$SANDBOX_NAME" destroy -y
  fi
  if ((FRESH_REQUESTED == 0)); then
    ONBOARD_ARGS+=(--fresh)
  fi
fi

# This exact repository-owned path is recognized as the trusted Hermes
# Dockerfile. NemoClaw stages the complete repository root and selects the
# generated-image BuildKit path. Omitting --from selects the stock managed
# Hermes image, which cannot contain this recipe's plugin layer.
"$NEMOHERMES_BIN" onboard \
  --name "$SANDBOX_NAME" \
  --from "$HERMES_DOCKERFILE" \
  "${ONBOARD_ARGS[@]}"
