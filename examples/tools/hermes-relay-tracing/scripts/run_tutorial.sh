#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tutorial_runtime_root="${TUTORIAL_RUNTIME_ROOT:-$repo_root/.tutorial-runtime}"
artifact_root="${RUNTIME_ROOT:-$repo_root/artifacts}"
run_root="$artifact_root/runs/$(date -u +%Y%m%dT%H%M%SZ)-$$"
hermes_home="$(mktemp -d "${TMPDIR:-/tmp}/nemo-relay-hermes-tutorial.XXXXXX")"
plugins_path="$hermes_home/plugins.toml"
trace_path="$run_root/atof/run.jsonl"
run_succeeded=false

cleanup_hermes_home() {
  rm -rf -- "$hermes_home"
  if [[ "$run_succeeded" != true && -d "$run_root" ]]; then
    printf '\nArtifacts: %s\n' "$run_root" >&2
  fi
}

trap cleanup_hermes_home EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

if [[ -z "${NVIDIA_API_KEY:-}" && -f "$repo_root/keys.env" ]]; then
  # shellcheck disable=SC1090
  source "$repo_root/keys.env"
fi

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
  echo "Set NVIDIA_API_KEY to a key generated on NVIDIA Build." >&2
  exit 1
fi
unset NVIDIA_INFERENCE_API_KEY
export NVIDIA_API_KEY

"$repo_root/scripts/check_environment.sh"
hermes_python="$tutorial_runtime_root/venv/bin/python"

# shellcheck disable=SC1090
source "$repo_root/config/smoke.env"
model="$SMOKE_MODEL"
docker_image="$SMOKE_DOCKER_IMAGE"
terminal_cwd="$SMOKE_TERMINAL_CWD"

command -v docker >/dev/null || {
  echo "Docker is required because this tutorial runs terminal commands in an isolated container." >&2
  exit 1
}
docker image inspect "$docker_image" >/dev/null 2>&1 || {
  echo "Tutorial image $docker_image is not available. Run ./scripts/build_tutorial_image.sh first." >&2
  exit 1
}

mkdir -p "$run_root"
"$hermes_python" "$repo_root/scripts/render_relay_config.py" \
  --output "$plugins_path" \
  --output-directory "$run_root" \
  --model-name "$model" >/dev/null

export HERMES_HOME="$hermes_home"
export HERMES_NEMO_RELAY_PLUGINS_TOML="$plugins_path"
export NVIDIA_BASE_URL

cat >"$hermes_home/config.yaml" <<YAML
model:
  provider: "nvidia"
  default: "$model"
  base_url: "$NVIDIA_BASE_URL"
  api_mode: "$NVIDIA_API_MODE"

providers:
  nvidia:
    name: "NVIDIA Build"
    base_url: "$NVIDIA_BASE_URL"
    key_env: "NVIDIA_API_KEY"
    api_mode: "$NVIDIA_API_MODE"
    default_model: "$model"
YAML

# The tutorial task is intentionally fixed and runs in an ephemeral container.
# Do not inherit a host-terminal or Docker configuration from the caller.
# shellcheck disable=SC1090
source "$repo_root/scripts/configure_tutorial_terminal.sh"
configure_tutorial_terminal "$docker_image" "$terminal_cwd"

# Keep the task prompt and success check in the public smoke contract so a
# reader can adapt the fixture without editing the runner.
query="$SMOKE_QUERY"
output_path="$run_root/hermes-output.txt"

"$hermes_python" -m hermes_cli.main chat \
  --provider nvidia \
  --model "$model" \
  --toolsets terminal \
  --query "$query" \
  --max-turns "$SMOKE_MAX_TURNS" \
  --run-budget "$SMOKE_RUN_BUDGET_SECONDS" \
  --accept-hooks \
  --quiet | tee "$output_path"

if grep -Eq 'No reply:|maximum tool-iteration' "$output_path"; then
  echo "Hermes did not return a final response." >&2
  exit 1
fi
grep -qxF "$SMOKE_EXPECTED_OUTPUT" "$output_path"
test -s "$trace_path"
trajectory_path="$(find "$run_root/atif" -type f -name 'trajectory-*.json' -size +0c -print -quit)"
test -n "$trajectory_path"

printf 'ATOF summary:\n'
"$hermes_python" "$repo_root/scripts/summarize_atof.py" \
  "$trace_path" \
  --require-completed-llm-scope \
  --require-token-usage \
  --require-tool-call \
  --require-no-tool-errors \
  --require-tool-command "$SMOKE_REQUIRED_TOOL_COMMAND"
printf '\nATIF summary:\n'
"$hermes_python" "$repo_root/scripts/summarize_atif.py" "$trajectory_path"
run_succeeded=true
printf '\nTask verified: %s\n' "$SMOKE_EXPECTED_OUTPUT"
printf '\nArtifacts: %s\n' "$run_root"
