#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_contains() {
  local haystack="$1" needle="$2" message="$3"
  [[ "$haystack" == *"$needle"* ]] || fail "$message (missing: $needle)"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_EXAMPLE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT
EXAMPLE_DIR="$TEST_ROOT/example"
COMMAND_LOG="$TEST_ROOT/commands.log"
export COMMAND_LOG

# Exercise an isolated copy so a developer's ignored .env cannot affect the
# command contract test or expose real credentials to the test process.
mkdir -p "$EXAMPLE_DIR/scripts" "$EXAMPLE_DIR/skills/market-analysis" \
  "$EXAMPLE_DIR/providers" "$EXAMPLE_DIR/policies"
cp "$SOURCE_EXAMPLE_DIR/scripts/_lib.sh" \
  "$SOURCE_EXAMPLE_DIR/scripts/onboard.sh" \
  "$SOURCE_EXAMPLE_DIR/scripts/install.sh" \
  "$SOURCE_EXAMPLE_DIR/scripts/start.sh" \
  "$SOURCE_EXAMPLE_DIR/scripts/stop.sh" \
  "$EXAMPLE_DIR/scripts/"

cp "$SOURCE_EXAMPLE_DIR/providers/auto-ontology.yaml" "$SOURCE_EXAMPLE_DIR/providers/nvidia-ai-api.yaml" "$EXAMPLE_DIR/providers/"

nemoclaw() {
  {
    printf 'sandbox=%q agent=%q args=' "${NEMOCLAW_SANDBOX_NAME:-}" "${NEMOCLAW_AGENT:-}"
    printf '%q ' "$@"
    printf '\n'
  } >>"$COMMAND_LOG"
  # A sandbox onboarded with the other harness keeps skills elsewhere: the placement check finds nothing.
  [[ "${FAKE_SKILL_MISSING:-0}" != "1" || "$*" != *"exec -- test -d"* ]]
}
export -f nemoclaw

openshell() {
  {
    printf 'openshell args='
    printf '%q ' "$@"
    printf 'key_in_env=%s\n' "${NVIDIA_AI_API_KEY:+yes}"
  } >>"$COMMAND_LOG"
  if [[ "$*" == "sandbox list --names" && "${FAKE_SANDBOX_EXISTS:-0}" == "1" ]]; then
    printf '%s\n' "${NEMOCLAW_SANDBOX_NAME:-market-analysis}"
  fi
  # A fresh gateway: no provider exists yet, and the profile import succeeds.
  if [[ -n "${FAKE_STATE_DIR:-}" ]]; then
    fake_gateway "$@"
    return
  fi
  [[ "$1 $2" != "provider get" && "$1 $2 $3" != "provider profile export" ]] || return 1
  return 0
}

# A gateway that remembers providers, profiles and attachments, with OpenShell's rule that a profile still used by a
# provider cannot be deleted. Used when FAKE_STATE_DIR is set.
fake_gateway() {
  local d="$FAKE_STATE_DIR" n
  case "$1 $2" in
    "provider get")
      [[ -f "$d/provider/$3" ]] || return 1
      printf 'Provider:\n\n  Name: %s\n  Type: %s\n  Resource version: 1\n' "$3" "$(cat "$d/provider/$3")" ;;
    "provider create")
      n="$4"
      [[ ! -f "$d/provider/$n" ]] || return 1
      [[ -f "$d/profile/$6" ]] || return 1
      printf '%s' "$6" >"$d/provider/$n" ;;
    "provider update") [[ -f "$d/provider/$3" ]] || return 1 ;;
    "provider delete")
      rm -f "$d/provider/$3"
      rm -f "$d"/attached/*/"$3" ;;
    "provider profile")
      case "$3" in
        export) [[ -f "$d/profile/$4" ]] && cat "$d/profile/$4" ;;
        import) n="$(sed -n 's/^id: //p' "$5")"; cp "$5" "$d/profile/$n" ;;
        delete)
          if grep -qxF "$4" "$d"/provider/* 2>/dev/null; then
            echo "profile $4 is still used by a provider" >&2
            return 1
          fi
          rm -f "$d/profile/$4" ;;
      esac ;;
    "sandbox provider")
      case "$3" in
        list) ls "$d/attached/$4" 2>/dev/null || true ;;
        attach) mkdir -p "$d/attached/$4"; : >"$d/attached/$4/$5" ;;
        detach) rm -f "$d/attached/$4/$5" ;;
      esac ;;
  esac
}
export -f openshell fake_gateway

export NEMOCLAW_SANDBOX_NAME=market-analysis

: >"$COMMAND_LOG"
NVIDIA_INFERENCE_API_KEY=test-key bash "$EXAMPLE_DIR/scripts/onboard.sh" >/dev/null
assert_contains "$(cat "$COMMAND_LOG")" "agent=openclaw" \
  "onboard did not select the OpenClaw harness"
assert_contains "$(cat "$COMMAND_LOG")" "args=onboard --non-interactive --yes --name market-analysis --no-sandbox-gpu" \
  "onboard did not create the named sandbox non-interactively"
assert_contains "$(cat "$COMMAND_LOG")" "--agent openclaw" \
  "onboard did not pass the harness to nemoclaw onboard"

# the Hermes harness
: >"$COMMAND_LOG"
NEMOCLAW_AGENT=hermes NVIDIA_INFERENCE_API_KEY=test-key bash "$EXAMPLE_DIR/scripts/onboard.sh" >/dev/null
assert_contains "$(cat "$COMMAND_LOG")" "--agent hermes" "onboard did not select the Hermes harness"
assert_contains "$(cat "$COMMAND_LOG")" "agent=hermes" "onboard did not export the Hermes harness"

# an unknown harness is rejected before anything is run
: >"$COMMAND_LOG"
if NEMOCLAW_AGENT=other NVIDIA_INFERENCE_API_KEY=test-key bash "$EXAMPLE_DIR/scripts/onboard.sh" >/dev/null 2>&1; then
  fail "onboard accepted an unknown NEMOCLAW_AGENT"
fi
[[ ! -s "$COMMAND_LOG" ]] || fail "onboard ran commands before rejecting an unknown harness"

# opt-in GPU sandbox for the CUDA-X path
: >"$COMMAND_LOG"
NEMOCLAW_SANDBOX_GPU=1 NEMOCLAW_SANDBOX_GPU_DEVICE=nvidia.com/gpu=0 NVIDIA_INFERENCE_API_KEY=test-key \
  bash "$EXAMPLE_DIR/scripts/onboard.sh" >/dev/null
assert_contains "$(cat "$COMMAND_LOG")" "--sandbox-gpu --sandbox-gpu-device nvidia.com/gpu=0" \
  "onboard did not enable the sandbox GPU when asked"
if grep -q -- '--no-sandbox-gpu' "$COMMAND_LOG"; then
  fail "onboard disabled the sandbox GPU although NEMOCLAW_SANDBOX_GPU=1"
fi

: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=1 bash "$EXAMPLE_DIR/scripts/start.sh" >/dev/null
assert_contains "$(cat "$COMMAND_LOG")" \
  "args=market-analysis recover" \
  "start did not use the sandbox-scoped recover command"

: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=1 bash "$EXAMPLE_DIR/scripts/stop.sh" >/dev/null
assert_contains "$(cat "$COMMAND_LOG")" "args=tunnel stop" \
  "stop did not stop the gateway through tunnel stop"

# a variable set in the environment beats the same name in .env
printf 'NEMOCLAW_SANDBOX_NAME=from-env\n' >"$EXAMPLE_DIR/.env"
: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=1 bash "$EXAMPLE_DIR/scripts/start.sh" >/dev/null
assert_contains "$(cat "$COMMAND_LOG")" "args=market-analysis recover" \
  "a value from .env overrode the environment"
rm -f "$EXAMPLE_DIR/.env"

# install with a build.nvidia.com key: hosted retrieval is enabled, then the skill is installed
: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=1 NEMOCLAW_PROVIDER=build NVIDIA_INFERENCE_API_KEY=test-key \
  bash "$EXAMPLE_DIR/scripts/install.sh" >/dev/null
log="$(cat "$COMMAND_LOG")"
assert_contains "$log" \
  "openshell args=provider profile import --file $EXAMPLE_DIR/providers/nvidia-ai-api.yaml" \
  "install did not import the provider profile"
assert_contains "$log" \
  "openshell args=provider create --name market-analysis-ai-api --type market-analysis-nvidia-ai-api --credential NVIDIA_AI_API_KEY key_in_env=yes" \
  "install did not create the second provider from the environment key"
assert_contains "$log" \
  "openshell args=sandbox provider attach market-analysis market-analysis-ai-api" \
  "install did not attach the provider to the sandbox"
assert_contains "$log" \
  "args=market-analysis policy-add --from-dir $EXAMPLE_DIR/policies --yes" \
  "install did not apply the egress policy directory"
assert_contains "$log" \
  "args=market-analysis skill install $EXAMPLE_DIR/skills/market-analysis" \
  "install did not deploy the skill"
assert_contains "$log" "args=market-analysis policy-add pypi --yes" \
  "install did not add the temporary pypi preset for the analysis environment"
assert_contains "$log" "args=market-analysis exec --timeout 900 -- bash -c" \
  "install did not build the analysis environment inside the sandbox"
assert_contains "$log" "requirements.txt" \
  "the analysis environment build did not use the pinned requirements"
assert_contains "$log" "args=market-analysis policy-remove pypi --yes" \
  "install did not remove the temporary pypi preset"
assert_contains "$log" "args=market-analysis stop" \
  "install did not stop the sandbox after attaching a new provider"
assert_contains "$log" "args=market-analysis start" \
  "install did not start the sandbox after attaching a new provider"
if grep -q 'test-key' "$COMMAND_LOG"; then
  fail "the key value appeared in a command line"
fi
if grep -q 'requirements-gpu' "$COMMAND_LOG"; then
  fail "install built the CUDA-X environment without NEMOCLAW_SANDBOX_GPU=1"
fi

# install on a GPU sandbox: the CUDA-X environment is built from its own requirements file
: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=1 NEMOCLAW_SANDBOX_GPU=1 NEMOCLAW_PROVIDER=build NVIDIA_INFERENCE_API_KEY=test-key \
  bash "$EXAMPLE_DIR/scripts/install.sh" >/dev/null
log="$(cat "$COMMAND_LOG")"
assert_contains "$log" "args=market-analysis exec --timeout 1800 -- bash -c" \
  "install did not build the CUDA-X environment on a GPU sandbox"
assert_contains "$log" "requirements-gpu.txt" "the CUDA-X build did not use its requirements file"

# install with an Auto Ontology token and a non-default port: a rendered profile, a provider from the
# environment, an attach, a URL file for the skill, and no token in any command line
: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=1 NEMOCLAW_PROVIDER=build NVIDIA_INFERENCE_API_KEY=test-key \
  AUTO_ONTOLOGY_API_TOKEN=ontology-secret AUTO_ONTOLOGY_PORT=5000 \
  bash "$EXAMPLE_DIR/scripts/install.sh" >/dev/null
log="$(cat "$COMMAND_LOG")"
assert_contains "$log" "openshell args=provider profile import --file " \
  "install did not import a rendered Auto Ontology profile"
assert_contains "$log" \
  "openshell args=provider create --name market-analysis-ontology --type market-analysis-auto-ontology-5000 --credential AUTO_ONTOLOGY_API_TOKEN" \
  "install did not create the Auto Ontology provider from the environment token"
assert_contains "$log" \
  "openshell args=sandbox provider attach market-analysis market-analysis-ontology" \
  "install did not attach the Auto Ontology provider"
assert_contains "$log" "host.openshell.internal:5000" \
  "install did not tell the skill the Auto Ontology URL"
if grep -q 'ontology-secret' "$COMMAND_LOG"; then
  fail "the Auto Ontology token appeared in a command line"
fi

# Credential rotation and port changes against a gateway that remembers state, with two sandboxes on one profile.
export FAKE_STATE_DIR="$TEST_ROOT/gateway"
reset_gateway() { rm -rf "$FAKE_STATE_DIR"; mkdir -p "$FAKE_STATE_DIR"/{provider,profile,attached}; }
install_box() {  # install_box SANDBOX PORT TOKEN [KEY]
  NEMOCLAW_SANDBOX_NAME="$1" FAKE_SANDBOX_EXISTS=1 NEMOCLAW_PROVIDER=build NVIDIA_INFERENCE_API_KEY="${4:-}" \
    AUTO_ONTOLOGY_API_TOKEN="$3" AUTO_ONTOLOGY_PORT="$2" bash "$EXAMPLE_DIR/scripts/install.sh" >/dev/null
}
reset_gateway
install_box box-a 4000 first-token
install_box box-b 4000 first-token

# rotating the token of an already attached provider updates it and restarts the agent
: >"$COMMAND_LOG"
install_box box-a 4000 second-token
log="$(cat "$COMMAND_LOG")"
assert_contains "$log" "openshell args=provider update box-a-ontology --credential AUTO_ONTOLOGY_API_TOKEN" \
  "rotating the token did not update the provider"
assert_contains "$log" "args=box-a stop" "rotating the token did not stop the sandbox"
assert_contains "$log" "args=box-a start" "rotating the token did not start the sandbox again"
if grep -q 'second-token' "$COMMAND_LOG"; then
  fail "the rotated token appeared in a command line"
fi

# rotating the build.nvidia.com key of an already attached provider also restarts the agent
install_box box-a 4000 second-token first-key
: >"$COMMAND_LOG"
install_box box-a 4000 second-token second-key
log="$(cat "$COMMAND_LOG")"
assert_contains "$log" "openshell args=provider update box-a-ai-api --credential NVIDIA_AI_API_KEY" \
  "rotating the key did not update the provider"
assert_contains "$log" "args=box-a start" "rotating the key did not restart the sandbox"

# moving one sandbox to another port keeps the other sandbox's provider and profile
: >"$COMMAND_LOG"
install_box box-a 5000 second-token
[[ "$(cat "$FAKE_STATE_DIR/provider/box-a-ontology")" == "market-analysis-auto-ontology-5000" ]] \
  || fail "the moved sandbox does not use the profile for its new port"
[[ "$(cat "$FAKE_STATE_DIR/provider/box-b-ontology")" == "market-analysis-auto-ontology-4000" ]] \
  || fail "moving one sandbox changed the other sandbox's provider"
[[ -f "$FAKE_STATE_DIR/profile/market-analysis-auto-ontology-4000" ]] \
  || fail "moving one sandbox deleted a profile the other sandbox still uses"
[[ -f "$FAKE_STATE_DIR/attached/box-b/box-b-ontology" ]] || fail "moving one sandbox detached the other"
[[ -f "$FAKE_STATE_DIR/attached/box-a/box-a-ontology" ]] || fail "the moved sandbox lost its provider"

# once the last user of an old profile moves away, the old profile goes too
install_box box-b 5000 second-token
[[ ! -f "$FAKE_STATE_DIR/profile/market-analysis-auto-ontology-4000" ]] \
  || fail "the old port's profile was left behind after its last user moved"
unset FAKE_STATE_DIR

# a malformed Auto Ontology port is rejected before anything is run
: >"$COMMAND_LOG"
if FAKE_SANDBOX_EXISTS=1 NEMOCLAW_PROVIDER=build NVIDIA_INFERENCE_API_KEY=test-key \
  AUTO_ONTOLOGY_API_TOKEN=ontology-secret AUTO_ONTOLOGY_PORT='4000/e' \
  bash "$EXAMPLE_DIR/scripts/install.sh" >/dev/null 2>&1; then
  fail "install accepted a malformed AUTO_ONTOLOGY_PORT"
fi
if grep -qE 'provider|policy-add|skill install' "$COMMAND_LOG"; then
  fail "install changed the gateway or sandbox before rejecting a malformed port"
fi

# install without a key: the skill and the Python environments are installed; no hosted-model egress or provider is created
: >"$COMMAND_LOG"
FAKE_SANDBOX_EXISTS=1 NEMOCLAW_PROVIDER=build NVIDIA_INFERENCE_API_KEY= \
  bash "$EXAMPLE_DIR/scripts/install.sh" >/dev/null 2>&1
log="$(cat "$COMMAND_LOG")"
assert_contains "$log" \
  "args=market-analysis skill install $EXAMPLE_DIR/skills/market-analysis" \
  "install without a key did not deploy the skill"
if grep -qE 'provider create|provider profile import|args=market-analysis (stop|start)' "$COMMAND_LOG"; then
  fail "install without a key created a provider or restarted the sandbox"
fi
if grep -q 'policy-add' "$COMMAND_LOG" && ! grep -q 'policy-remove pypi' "$COMMAND_LOG"; then
  fail "install without a key left the pypi egress open"
fi

# Hermes: the Python environments are built from the Hermes skill directory
: >"$COMMAND_LOG"
NEMOCLAW_AGENT=hermes FAKE_SANDBOX_EXISTS=1 NEMOCLAW_PROVIDER=build NVIDIA_INFERENCE_API_KEY=test-key \
  bash "$EXAMPLE_DIR/scripts/install.sh" >/dev/null
log="$(cat "$COMMAND_LOG")"
assert_contains "$log" "/sandbox/.hermes/skills/market-analysis/utilities/requirements.txt" \
  "Hermes install did not build the analysis environment from the Hermes skill directory"
if grep -q '\.openclaw' "$COMMAND_LOG"; then
  fail "Hermes install used an OpenClaw path"
fi
assert_contains "$log" "args=market-analysis skill remove market-analysis" \
  "Hermes install did not clear an earlier copy of the skill"

# a harness that does not match the sandbox stops the install before any environment is built
: >"$COMMAND_LOG"
if FAKE_SKILL_MISSING=1 NEMOCLAW_AGENT=hermes FAKE_SANDBOX_EXISTS=1 NEMOCLAW_PROVIDER=build NVIDIA_INFERENCE_API_KEY=test-key \
  bash "$EXAMPLE_DIR/scripts/install.sh" >/dev/null 2>&1; then
  fail "install carried on although the skill was not where the harness keeps skills"
fi
if grep -q 'exec --timeout' "$COMMAND_LOG"; then
  fail "install built a Python environment although the skill was missing"
fi

echo "ok"
