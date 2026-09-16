#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/run_conference_research_with_phoenix.sh [--model-profile PATH]

Without an option, the runner reuses NVIDIA_API_KEY and the NVIDIA Build model
configuration from config/smoke.env. Use --model-profile to repeat the same
task with a compatible model endpoint configured in a local profile file.
EOF
}

profile="nemotron"
model_profile_path=""
if [[ $# -gt 0 ]]; then
  if [[ $# -eq 1 && "$1" == "--help" ]]; then
    usage
    exit 0
  fi
  if [[ $# -ne 2 || "$1" != "--model-profile" ]]; then
    usage >&2
    exit 2
  fi
  model_profile_path="$2"
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tutorial_runtime_root="${TUTORIAL_RUNTIME_ROOT:-$repo_root/.tutorial-runtime}"
artifact_root="${RUNTIME_ROOT:-$repo_root/artifacts}"
run_root=""
input_directory=""
output_directory=""
hermes_home="$(mktemp -d "${TMPDIR:-/tmp}/nemo-relay-hermes-conference.XXXXXX")"
plugins_path="$hermes_home/plugins.toml"
trace_path=""
verification_path=""
run_succeeded=false

cleanup_hermes_home() {
  rm -rf -- "$hermes_home"
  if [[ "$run_succeeded" != true && -n "$run_root" && -d "$run_root" ]]; then
    printf '\nArtifacts: %s\n' "$run_root" >&2
  fi
}

trap cleanup_hermes_home EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

# shellcheck disable=SC1091
source "$repo_root/config/smoke.env"
# shellcheck disable=SC1091
source "$repo_root/config/phoenix.env"
# shellcheck disable=SC1091
source "$repo_root/config/conference_research.env"

model="$SMOKE_MODEL"
base_url="$NVIDIA_BASE_URL"
api_mode="$NVIDIA_API_MODE"
llm_span="openai.chat_completions"
provider_key="nvidia"
provider_name="NVIDIA Build"
api_key_name="NVIDIA_API_KEY"

read_profile_value() {
  local key="$1"
  local file="$2"
  local line
  line="$(grep -E "^${key}=" "$file" | tail -n 1 || true)"
  line="${line%$'\r'}"
  printf '%s' "${line#*=}"
}

if [[ -n "$model_profile_path" ]]; then
  if [[ ! -f "$model_profile_path" ]]; then
    echo "Model profile not found: $model_profile_path" >&2
    exit 1
  fi

  profile="$(read_profile_value MODEL_PROFILE_NAME "$model_profile_path")"
  model="$(read_profile_value MODEL_PROFILE_MODEL "$model_profile_path")"
  base_url="$(read_profile_value MODEL_PROFILE_BASE_URL "$model_profile_path")"
  api_mode="$(read_profile_value MODEL_PROFILE_API_MODE "$model_profile_path")"
  api_key_name="$(read_profile_value MODEL_PROFILE_API_KEY_ENV "$model_profile_path")"
  provider_key="comparison"
  provider_name="Comparison model"

  if [[ ! "$profile" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "MODEL_PROFILE_NAME must contain only letters, numbers, dots, underscores, or hyphens." >&2
    exit 1
  fi
  for value_name in model base_url api_mode api_key_name; do
    if [[ -z "${!value_name}" ]]; then
      echo "Model profile is missing a required value: $value_name" >&2
      exit 1
    fi
  done
  if [[ ! "$model" =~ ^[A-Za-z0-9._:/@+-]+$ ]]; then
    echo "MODEL_PROFILE_MODEL contains unsupported characters." >&2
    exit 1
  fi
  if [[ ! "$base_url" =~ ^https?://[^[:space:]\"\\]+$ ]]; then
    echo "MODEL_PROFILE_BASE_URL must use http:// or https://." >&2
    exit 1
  fi
  case "$api_mode" in
    chat_completions) llm_span="openai.chat_completions" ;;
    anthropic_messages) llm_span="anthropic.messages" ;;
    codex_responses) llm_span="openai.responses" ;;
    *)
      echo "MODEL_PROFILE_API_MODE must be chat_completions, anthropic_messages, or codex_responses." >&2
      exit 1
      ;;
  esac
  if [[ ! "$api_key_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "MODEL_PROFILE_API_KEY_ENV must be a valid environment-variable name." >&2
    exit 1
  fi
fi

run_root="$artifact_root/conference-research/$profile/$(date -u +%Y%m%dT%H%M%SZ)-$$"
input_directory="$run_root/input"
output_directory="$run_root/output"
trace_path="$run_root/atof/run.jsonl"
verification_path="$output_directory/conference-verification.md"

selected_api_key="${!api_key_name:-}"
if [[ -z "$selected_api_key" && -f "$repo_root/keys.env" ]]; then
  # shellcheck disable=SC1090,SC1091
  source "$repo_root/keys.env"
  selected_api_key="${!api_key_name:-}"
fi
if [[ -z "$selected_api_key" ]]; then
  echo "Set $api_key_name in keys.env or the current shell for the $profile profile." >&2
  exit 1
fi
export NVIDIA_API_KEY="$selected_api_key"
unset selected_api_key

"$repo_root/scripts/check_environment.sh"
hermes_python="$tutorial_runtime_root/venv/bin/python"

docker_image="$SMOKE_DOCKER_IMAGE"
command -v docker >/dev/null || {
  echo "Docker is required because the file tools run in an isolated container." >&2
  exit 1
}
docker image inspect "$docker_image" >/dev/null 2>&1 || {
  echo "Tutorial image $docker_image is not available. Run ./scripts/build_tutorial_image.sh first." >&2
  exit 1
}

"$repo_root/scripts/start_phoenix.sh"
project_name="$PHOENIX_PROJECT_PREFIX-conference-$profile-$(date -u +%Y%m%dT%H%M%SZ)-$$"

mkdir -p "$input_directory" "$output_directory"
cp "$repo_root/conference-task/travel-plan.md" "$input_directory/travel-plan.md"
"$hermes_python" "$repo_root/scripts/render_relay_config.py" \
  --output "$plugins_path" \
  --output-directory "$run_root" \
  --model-name "$model" \
  --openinference-endpoint "$PHOENIX_OTLP_ENDPOINT" \
  --openinference-project "$project_name" >/dev/null

export HERMES_HOME="$hermes_home"
export HERMES_NEMO_RELAY_PLUGINS_TOML="$plugins_path"
export NVIDIA_BASE_URL="$base_url"

cat >"$hermes_home/config.yaml" <<YAML
model:
  provider: "$provider_key"
  default: "$model"
  base_url: "$base_url"
  api_mode: "$api_mode"

providers:
  $provider_key:
    name: "$provider_name"
    base_url: "$base_url"
    key_env: "NVIDIA_API_KEY"
    api_mode: "$api_mode"
    default_model: "$model"

display:
  show_reasoning: false
web:
  keyless_fallback: true
YAML

# Keep web research on Hermes' built-in keyless fallback even when the parent
# shell has a paid search provider configured.
unset EXA_API_KEY PARALLEL_API_KEY TAVILY_API_KEY TAVILY_BASE_URL
unset FIRECRAWL_API_KEY FIRECRAWL_API_URL FIRECRAWL_GATEWAY_URL
unset SEARXNG_URL BRAVE_SEARCH_API_KEY TOOL_GATEWAY_DOMAIN

# File tools use the same constrained Docker backend as Example 1.
# Mount the fixed input read-only, mount a separate output directory read/write,
# and prevent file-tool writes anywhere else.
# shellcheck disable=SC1091
source "$repo_root/scripts/configure_tutorial_terminal.sh"
configure_tutorial_terminal "$docker_image" "/output"
export TERMINAL_DOCKER_VOLUMES
TERMINAL_DOCKER_VOLUMES="$(
  "$hermes_python" -c \
    'import json, sys; print(json.dumps([f"{sys.argv[1]}:/input:ro", f"{sys.argv[2]}:/output:rw"]))' \
    "$input_directory" \
    "$output_directory"
)"
export HERMES_WRITE_SAFE_ROOT=/output

output_path="$run_root/hermes-output.txt"
"$hermes_python" -m hermes_cli.main chat \
  --provider "$provider_key" \
  --model "$model" \
  --toolsets web,file \
  --query "$CONFERENCE_RESEARCH_QUERY" \
  --max-turns "$CONFERENCE_RESEARCH_MAX_TURNS" \
  --run-budget "$CONFERENCE_RESEARCH_RUN_BUDGET_SECONDS" \
  --accept-hooks \
  --ignore-rules \
  --quiet 2>&1 | tee "$output_path"

if grep -Eq 'No reply:|maximum tool-iteration|Reached maximum iterations' "$output_path"; then
  echo "Hermes did not return a final response." >&2
  exit 1
fi

cmp -s "$repo_root/conference-task/travel-plan.md" "$input_directory/travel-plan.md" || {
  echo "The read-only task input changed unexpectedly." >&2
  exit 1
}
test -s "$trace_path"
test -s "$verification_path"
trajectory_path="$(find "$run_root/atif" -type f -name 'trajectory-*.json' -size +0c -print -quit)"
test -n "$trajectory_path"

"$hermes_python" "$repo_root/scripts/verify_conference_research.py" \
  "$output_path" \
  "$verification_path" \
  "$trace_path" \
  --expected-name "$CONFERENCE_RESEARCH_EXPECTED_NAME" \
  --expected-source-prefix "$CONFERENCE_RESEARCH_EXPECTED_SOURCE_PREFIX" \
  --expected-read-path /input/travel-plan.md \
  --expected-write-path /output/conference-verification.md

printf '\nATOF summary:\n'
"$hermes_python" "$repo_root/scripts/summarize_atof.py" \
  "$trace_path" \
  --require-completed-llm-scope \
  --require-tool-call \
  --require-no-tool-errors \
  --require-tool-name read_file \
  --require-tool-name web_search \
  --require-tool-name web_extract \
  --require-tool-name write_file
printf '\nATIF summary:\n'
"$hermes_python" "$repo_root/scripts/summarize_atif.py" "$trajectory_path"

phoenix_requirements=(
  --require-span-name hermes.session
  --require-span-name "$llm_span"
  --require-span-name read_file
  --require-span-name web_search
  --require-span-name web_extract
  --require-span-name write_file
)
"$hermes_python" "$repo_root/scripts/verify_phoenix.py" \
  --graphql-url "$PHOENIX_UI_URL/graphql" \
  --api-url "$PHOENIX_UI_URL" \
  --project-name "$project_name" \
  "${phoenix_requirements[@]}" \
  --require-positive-token-total \
  --timeout-seconds 30

run_succeeded=true
printf '\nConference-research task verified: %s\n' "$CONFERENCE_RESEARCH_EXPECTED_NAME"
printf 'Model profile: %s (%s)\n' "$profile" "$model"
printf 'Verification report: %s\n' "$verification_path"
printf 'Artifacts: %s\n' "$run_root"
printf 'Open Phoenix: %s/projects\n' "$PHOENIX_UI_URL"
if [[ "$PHOENIX_UI_PORT" == "6006" ]]; then
  printf 'When finished, run: ./scripts/stop_phoenix.sh\n'
else
  printf 'When finished, run: PHOENIX_UI_PORT=%s ./scripts/stop_phoenix.sh\n' "$PHOENIX_UI_PORT"
fi
