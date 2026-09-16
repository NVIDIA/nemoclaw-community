#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Isolated lifecycle and ownership regressions. No OpenShell, Hermes, Docker,
# configured bot, host profile, or operator state is read or changed.
set -euo pipefail

SWARM_ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/swarm-lifecycle.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
export SWARM_ROOT SWARM_STATE="$TMP/state" HOME="$TMP/home"
mkdir -p "$HOME"

SANDBOX_PREFIX=test-
BOTS="base-a base-b"
API_PORT_BASE=18100
HOST_API_ADDR=127.0.0.1
TRACING=off
INFERENCE_MODEL=test-model
INFERENCE_BASE_URL=http://inference.invalid/v1
INFERENCE_KEY_FILE="$TMP/inference.key"
INFERENCE_MAX_TOKENS=128
INFERENCE_CONTEXT_LENGTH=1024
VSS_BASE_URL=""
HOST_GATEWAY=off
COLLECTOR_NAME=swarm-otel

# shellcheck disable=SC1091
source "$SWARM_ROOT/lib/common.sh"
source "$SWARM_ROOT/lib/sandbox.sh"
source "$SWARM_ROOT/lib/bot.sh"
source "$SWARM_ROOT/lib/extras.sh"
source "$SWARM_ROOT/lib/host.sh"
source "$SWARM_ROOT/lib/mesh.sh"
source "$SWARM_ROOT/lib/tracing.sh"

PASS=0
check() {
  local label="$1" got="$2" want="$3"
  if [[ "$got" != "$want" ]]; then
    printf 'FAIL  %s: got %q want %q\n' "$label" "$got" "$want"
    exit 1
  fi
  PASS=$((PASS + 1)); printf 'ok    %s\n' "$label"
}

state_init
owner=$(deployment_owner_token)
check "deployment token shape" "$(printf '%s' "$owner" | grep -Ec '^[0-9a-f]{64}$')" 1
state_init
check "deployment token persists" "$(deployment_owner_token)" "$owner"
check "deployment token is private" "$(file_mode "$SWARM_STATE/owner-token")" 600

# Forward cleanup must match the exact final sandbox argv, not a longer name
# owned by another deployment, and operator prefix punctuation stays literal.
forward_pattern=$(bot_forward_process_pattern 18100 'team.foo[1]')
check "forward pattern matches exact sandbox" \
  "$([[ 'openshell forward service --target-port 18100 --local 127.0.0.1:18100 team.foo[1]' =~ $forward_pattern ]] && echo yes || echo no)" yes
check "forward pattern rejects prefix-overlap sandbox" \
  "$([[ 'openshell forward service --target-port 18100 --local 127.0.0.1:18100 team.foo[1]bar' =~ $forward_pattern ]] && echo yes || echo no)" no

# Partial state and custom souls are part of inventory, while configured bots
# remain first and are de-duplicated for `swarm up`.
printf 'key\n' > "$(bot_key_file base-a)"
printf '18102\n' > "$(bot_port_file custom-port)"
printf '# custom\n' > "$(bot_state_soul_file custom-soul)"
check "partial state is inventoried" "$(bot_list | tr '\n' ' ')" "base-a custom-port custom-soul "
check "up inventory includes configured and tracked bots" "$(fleet_list | tr '\n' ' ')" "base-a base-b custom-port custom-soul "

printf 'CUSTOM ROLE SENTINEL\n' > "$TMP/source-soul.md"
saved=$(bot_persist_soul custom-role "$TMP/source-soul.md")
rm "$TMP/source-soul.md"
check "custom soul is a durable snapshot" "$(cat "$(bot_source_soul_file custom-role)")" "CUSTOM ROLE SENTINEL"
check "custom soul source is deployment state" "$saved" "$(bot_state_soul_file custom-role)"

# Name ownership is checked before a role snapshot or key/port can appear.
sandbox_exists() { [[ "$1" == test-collision ]]; }
sandbox_owned() { return 1; }
sandbox_adopt_legacy() { return 1; }
if (bot_prepare_soul collision role "must not persist" >/dev/null 2>&1); then collision=accepted; else collision=refused; fi
check "foreign name collision is refused" "$collision" refused
check "collision leaves no key" "$([[ -e "$(bot_key_file collision)" ]] && echo yes || echo no)" no
check "collision leaves no port" "$([[ -e "$(bot_port_file collision)" ]] && echo yes || echo no)" no
check "collision leaves no soul" "$([[ -e "$(bot_state_soul_file collision)" ]] && echo yes || echo no)" no
unset -f sandbox_exists sandbox_owned sandbox_adopt_legacy
source "$SWARM_ROOT/lib/sandbox.sh"

# The up loop restores configured and dynamically added tracked bots alike.
UP_EVENTS="$TMP/up-events"
fleet_list() { printf 'base-a\nadded\n'; }
sandbox_exists() { return 1; }
sandbox_phase() { return 0; }
host_profile_assert_available() { return 0; }
bot_exists() { return 0; }
bot_restore() { printf 'restore:%s\n' "$1" >> "$UP_EVENTS"; }
bot_create() { printf 'create:%s\n' "$1" >> "$UP_EVENTS"; }
bot_up_all >/dev/null
check "up restores configured bot" "$(grep -c '^restore:base-a$' "$UP_EVENTS")" 1
check "up restores tracked added bot" "$(grep -c '^restore:added$' "$UP_EVENTS")" 1
check "up does not recreate tracked bots" "$(grep -c '^create:' "$UP_EVENTS" || true)" 0
before_up_events=$(wc -l < "$UP_EVENTS" | tr -d ' ')
fleet_list() { printf 'base-a\nforeign\n'; }
sandbox_exists() { return 0; }
sandbox_phase() { printf 'Ready\n'; }
sandbox_owned() { [[ "$1" == test-base-a ]]; }
sandbox_adopt_legacy() { return 1; }
if (bot_up_all >/dev/null 2>&1); then up_foreign=mutated; else up_foreign=refused; fi
check "up preflight refuses foreign sandbox" "$up_foreign" refused
check "up preflight refuses before restoring anything" "$(wc -l < "$UP_EVENTS" | tr -d ' ')" "$before_up_events"
unset -f fleet_list sandbox_exists sandbox_phase sandbox_owned sandbox_adopt_legacy host_profile_assert_available bot_exists bot_restore bot_create
source "$SWARM_ROOT/lib/bot.sh"

# Add/rm/down all preflight the live tracked fleet before creating or deleting
# anything, including survivors outside the requested teardown scope.
MUTATION_EVENTS="$TMP/fleet-mutation-events"
bot_list() { printf 'survivor\nforeign\n'; }
sandbox_exists() { [[ "$1" == test-victim || "$1" == test-survivor || "$1" == test-foreign ]]; }
sandbox_owned() { [[ "$1" == test-victim || "$1" == test-survivor ]]; }
sandbox_adopt_legacy() { return 1; }
bot_port() { return 1; }
host_profile_assert_available() { return 0; }
bot_destroy() { printf 'delete:%s\n' "$1" >> "$MUTATION_EVENTS"; }
mesh_forget() { printf 'mesh:%s\n' "$1" >> "$MUTATION_EVENTS"; }
bot_reconcile_all() { printf 'reconcile\n' >> "$MUTATION_EVENTS"; }
if (bot_destroy_scope victim >/dev/null 2>&1); then teardown_foreign=mutated; else teardown_foreign=refused; fi
check "teardown refuses a foreign survivor" "$teardown_foreign" refused
check "teardown refusal occurs before any delete" "$([[ -e "$MUTATION_EVENTS" ]] && echo yes || echo no)" no

# If the one requested delete fails at runtime, unrelated survivors are not
# reconfigured and the scope still reports failure.
FAILED_REMOVE_EVENTS="$TMP/failed-remove-events"
bot_preflight_destroy_scope() { return 0; }
bot_destroy() { return 1; }
mesh_forget() { printf 'mesh\n' >> "$FAILED_REMOVE_EVENTS"; }
bot_reconcile_all() { printf 'reconcile\n' >> "$FAILED_REMOVE_EVENTS"; }
if (bot_destroy_scope victim >/dev/null 2>&1); then failed_remove=accepted; else failed_remove=refused; fi
check "failed single remove reports failure" "$failed_remove" refused
check "failed single remove leaves survivors untouched" "$([[ -e "$FAILED_REMOVE_EVENTS" ]] && echo yes || echo no)" no

if (bot_prepare_soul newcomer role "new role" >/dev/null 2>&1); then add_foreign=mutated; else add_foreign=refused; fi
check "add refuses a foreign tracked participant" "$add_foreign" refused
check "add fleet refusal leaves no soul" "$([[ -e "$(bot_state_soul_file newcomer)" ]] && echo yes || echo no)" no
check "add fleet refusal leaves no key" "$([[ -e "$(bot_key_file newcomer)" ]] && echo yes || echo no)" no
check "add fleet refusal leaves no port" "$([[ -e "$(bot_port_file newcomer)" ]] && echo yes || echo no)" no

unset -f bot_list sandbox_exists sandbox_owned sandbox_adopt_legacy bot_port \
  host_profile_assert_available bot_destroy mesh_forget bot_reconcile_all
source "$SWARM_ROOT/lib/sandbox.sh"
source "$SWARM_ROOT/lib/bot.sh"
source "$SWARM_ROOT/lib/mesh.sh"

NONREADY_EVENTS="$TMP/nonready-events"
bot_list() { printf 'paused-survivor\n'; }
bot_exists() { return 0; }
sandbox_phase() { printf 'Error\n'; }
bot_require_owned() { printf 'mutated\n' >> "$NONREADY_EVENTS"; }
bot_reconcile_all >/dev/null
check "reconcile skips a non-Ready survivor" "$([[ -e "$NONREADY_EVENTS" ]] && echo yes || echo no)" no

# Removing the last bot leaves no survivors. These helpers must remain no-ops
# under Bash 3.2 with nounset, where an empty array expansion aborts.
bot_list() { return 0; }
mesh_sync >/dev/null
mesh_forget removed >/dev/null
bot_reconcile_all >/dev/null
check "empty survivor reconciliation is safe" yes yes
unset -f bot_list bot_exists sandbox_phase bot_require_owned
source "$SWARM_ROOT/lib/sandbox.sh"
source "$SWARM_ROOT/lib/bot.sh"
source "$SWARM_ROOT/lib/mesh.sh"

# Exercise the real restore/reconcile orchestration with all external writes
# mocked. This proves tracing-off and saved custom roles survive both paths.
printf '18123\n' > "$(bot_port_file custom-role)"
(umask 077; printf 'key\n' > "$(bot_key_file custom-role)")
RESTORE_EVENTS="$TMP/restore-events"
bot_require_owned() { return 0; }
sandbox_phase() { printf 'Ready\n'; }
bot_configure_model() { :; }
bot_write_soul() { printf 'soul:%s:%s\n' "$1" "$2" >> "$RESTORE_EVENTS"; }
bot_policy_extras() { :; }
bot_env_extras() { :; }
bot_files_extras() { :; }
bot_toolset_extras() { :; }
bot_start() { :; }
host_profile_ensure() { :; }
tracing_enable_bot() { printf 'enable:%s\n' "$1" >> "$RESTORE_EVENTS"; }
tracing_disable_bot() { printf 'disable:%s\n' "$1" >> "$RESTORE_EVENTS"; }
bot_wait_api() { :; }
bot_restore custom-role >/dev/null
check "tracing off disables restored custom bot" "$(grep -c '^disable:custom-role$' "$RESTORE_EVENTS")" 1
check "restore uses saved custom role" "$(grep -c "^soul:custom-role:$(bot_state_soul_file custom-role)$" "$RESTORE_EVENTS")" 1

bot_list() { printf 'custom-role\n'; }
bot_exists() { return 0; }
bot_port() { printf '18123'; }
read_secret() { printf 'key'; }
bot_reconcile_all >/dev/null
check "reconcile preserves saved custom role" "$(grep -c "^soul:custom-role:$(bot_state_soul_file custom-role)$" "$RESTORE_EVENTS")" 2

unset -f bot_require_owned sandbox_phase bot_configure_model bot_write_soul bot_policy_extras \
  bot_env_extras bot_files_extras bot_toolset_extras bot_start host_profile_ensure \
  tracing_enable_bot tracing_disable_bot bot_wait_api bot_list bot_exists bot_port read_secret
source "$SWARM_ROOT/lib/common.sh"
source "$SWARM_ROOT/lib/sandbox.sh"
source "$SWARM_ROOT/lib/bot.sh"
source "$SWARM_ROOT/lib/extras.sh"
source "$SWARM_ROOT/lib/host.sh"
source "$SWARM_ROOT/lib/tracing.sh"

# Host markers are exact deployment identities, not mere marker existence.
mkdir -p "$HOME/.hermes/profiles/base-a"
printf '%s\n' "$owner" > "$HOME/.hermes/profiles/base-a/.swarm-owner"
check "matching host profile marker is owned" "$(host_profile_owned base-a && echo yes || echo no)" yes
printf '%s\n' foreign > "$HOME/.hermes/profiles/base-a/.swarm-owner"
check "foreign host profile marker is refused" "$(host_profile_owned base-a && echo yes || echo no)" no

# Collector ownership is deployment-scoped; the old config-label-only form is
# accepted only with this deployment's exact config mount.
DOCKER_OWNER="$owner"; DOCKER_CONFIG=hash; DOCKER_MOUNT="$(_collector_config)"
docker() {
  local fmt="${3:-}"
  [[ "${1:-}" == inspect && "${2:-}" == -f ]] || return 1
  case "$fmt" in
    *swarm.owner*) printf '%s\n' "$DOCKER_OWNER" ;;
    *swarm.config*) printf '%s\n' "$DOCKER_CONFIG" ;;
    *Mounts*) printf '%s\n' "$DOCKER_MOUNT" ;;
    *) return 1 ;;
  esac
}
check "matching collector owner is accepted" "$(collector_owned && echo yes || echo no)" yes
DOCKER_OWNER=another-deployment
check "foreign collector owner is refused" "$(collector_owned && echo yes || echo no)" no
check "foreign labeled collector cannot use legacy fallback" "$(collector_legacy_owned && echo yes || echo no)" no
DOCKER_OWNER=""
check "legacy collector needs exact state mount" "$(collector_legacy_owned && echo yes || echo no)" yes
DOCKER_MOUNT="$TMP/other-config.yaml"
check "legacy collector with another mount is refused" "$(collector_legacy_owned && echo yes || echo no)" no
unset -f docker

# A foreign mesh participant aborts before the first mutation.
MUTATIONS="$TMP/mutations"
bot_list() { printf 'good\nforeign\n'; }
sandbox_phase() { printf 'Ready\n'; }
bot_require_owned() { [[ "$1" == foreign ]] && exit 47; return 0; }
bot_key_file() { printf '%s/%s.key' "$TMP" "$1"; }
bot_port() { printf '18111'; }
printf key > "$TMP/good.key"; printf key > "$TMP/foreign.key"
_mesh_install_plugin() { printf touched >> "$MUTATIONS"; }
if (mesh_sync >/dev/null 2>&1); then mesh_result=mutated; else mesh_result=refused; fi
check "foreign mesh collision is refused" "$mesh_result" refused
check "mesh preflight writes nothing before refusal" "$([[ -e "$MUTATIONS" ]] && echo yes || echo no)" no

# Restore real helpers for stale teardown and profile-hook cleanup tests.
unset -f bot_list sandbox_phase bot_require_owned bot_key_file bot_port _mesh_install_plugin
source "$SWARM_ROOT/lib/common.sh"
source "$SWARM_ROOT/lib/sandbox.sh"
source "$SWARM_ROOT/lib/bot.sh"
source "$SWARM_ROOT/lib/mesh.sh"
printf key > "$(bot_key_file ghost)"
printf 18199 > "$(bot_port_file ghost)"
printf soul > "$(bot_state_soul_file ghost)"
sandbox_exists() { return 1; }
sandbox_delete() { return 0; }
host_profile_remove() { return 0; }
pkill_pattern() { return 0; }
bot_destroy ghost >/dev/null
check "absent sandbox teardown removes stale key" "$([[ -e "$(bot_key_file ghost)" ]] && echo yes || echo no)" no
check "absent sandbox teardown removes stale port" "$([[ -e "$(bot_port_file ghost)" ]] && echo yes || echo no)" no
check "absent sandbox teardown removes stale soul" "$([[ -e "$(bot_state_soul_file ghost)" ]] && echo yes || echo no)" no

unset -f host_profile_remove
source "$SWARM_ROOT/lib/host.sh"
name=shim
dir="$HOME/.hermes/profiles/$name"
mkdir -p "$dir/plugins/dropbox"
printf 'KEEP=1\nSWARM_VSS_SANDBOX=test-vss\n' > "$dir/.env"
GATEWAY_EVENTS="$TMP/gateway-events"
host_profile_state() { printf 'running\n'; }
host_gateway_stop() { printf 'stop\n' >> "$GATEWAY_EVENTS"; }
host_gateway_start() { printf 'start\n' >> "$GATEWAY_EVENTS"; }
hermes() { return 0; }
host_dropbox_remove "$name" >/dev/null
check "legacy dropbox plugin is removed" "$([[ -e "$dir/plugins/dropbox" ]] && echo yes || echo no)" no
check "legacy dropbox env is removed" "$(grep -c '^SWARM_VSS_SANDBOX=' "$dir/.env" || true)" 0
check "loaded host gateway is restarted after cleanup" "$(tr '\n' ' ' < "$GATEWAY_EVENTS")" "stop start "

# The live e2e suite must never invoke commands that create, delete, or
# reconfigure the operator's fleet.
live_mutations=$(grep -Ec '\$SWARM_ROOT/swarm" (up|down|add|rm)' "$SWARM_ROOT/tests/e2e.sh" || true)
check "live e2e has no fleet lifecycle mutation" "$live_mutations" 0

printf '\nPASS  %d isolated lifecycle checks\n' "$PASS"
