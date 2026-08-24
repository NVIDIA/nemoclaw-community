#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 Linespotting AB
# SPDX-License-Identifier: Apache-2.0
#
# Layered checks. Local/static always runs. Host Bot API runs when gbr-agent
# is listening. Sandbox attach runs when nemoclaw/openshell and the named
# sandbox exist.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(dirname "$SCRIPT_DIR")"
SANDBOX_NAME="${SANDBOX_NAME:-gbr-pair}"
POLICY_PATH="$EXAMPLE_DIR/policy.yaml"
SKILL_PATH="$EXAMPLE_DIR/skills/gbr-remote-operator/SKILL.md"
PING_PATH="$EXAMPLE_DIR/skills/gbr-remote-operator/scripts/operator-ping.sh"
BOT="http://127.0.0.1:8788"
RELAY="https://gbr-relay.ekobrott.workers.dev"

if [[ -f "$EXAMPLE_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$EXAMPLE_DIR/.env"
  set +a
fi

pass=0
skip=0
fail=0

ok() { echo "  PASS  $*"; pass=$((pass + 1)); }
ko() { echo "  FAIL  $*"; fail=$((fail + 1)); }
sk() { echo "  SKIP  $*"; skip=$((skip + 1)); }

echo "== local/static =="

for f in "$POLICY_PATH" "$SKILL_PATH" "$PING_PATH" \
  "$EXAMPLE_DIR/agents.yaml" \
  "$SCRIPT_DIR/onboard.sh" \
  "$SCRIPT_DIR/install.sh" \
  "$SCRIPT_DIR/install-gbr-agent.sh" \
  "$SCRIPT_DIR/teardown.sh"; do
  if [[ -f "$f" ]]; then
    ok "present $(basename "$f")"
  else
    ko "missing $f"
  fi
done

if grep -q "host.openshell.internal" "$POLICY_PATH" && grep -q "port: 8788" "$POLICY_PATH"; then
  ok "policy allows host.openshell.internal:8788"
else
  ko "policy missing host Bot API endpoint"
fi

if grep -v '^#' "$POLICY_PATH" | grep -Eq "gbr-relay|ekobrott"; then
  ko "policy must not allow the vendor relay"
else
  ok "policy has no vendor-relay endpoint"
fi

if grep -q "method: POST" "$POLICY_PATH"; then
  ko "policy must not allow POST (inject stays on the host)"
else
  ok "policy is GET-only"
fi

if grep -q '^name: gbr-remote-operator' "$SKILL_PATH" || grep -q 'name: gbr-remote-operator' "$SKILL_PATH"; then
  ok "skill frontmatter"
else
  ko "skill frontmatter missing name"
fi

if command -v bash >/dev/null 2>&1; then
  bash -n "$PING_PATH" && ok "operator-ping.sh syntax"
  bash -n "$SCRIPT_DIR/onboard.sh" && ok "onboard.sh syntax"
  bash -n "$SCRIPT_DIR/install.sh" && ok "install.sh syntax"
  bash -n "$SCRIPT_DIR/install-gbr-agent.sh" && ok "install-gbr-agent.sh syntax"
  bash -n "$SCRIPT_DIR/teardown.sh" && ok "teardown.sh syntax"
fi

echo "== host Bot API =="
if curl -fsS --max-time 5 "$BOT/health" >/dev/null 2>&1; then
  health="$(curl -fsS --max-time 5 "$BOT/health")"
  echo "$health" | grep -q '"ok":true' && ok "GET /health ok" || ko "GET /health not ok"
  echo "$health" | grep -q '"version":"v0.6.0"' && ok "agent version v0.6.0" || sk "running agent is not v0.6.0"
  sessions="$(curl -fsS --max-time 5 "$BOT/v1/sessions" || true)"
  if echo "$sessions" | grep -q "session_id"; then
    ok "GET /v1/sessions discovered at least one TTY"
  else
    ko "GET /v1/sessions returned no session_id"
  fi
else
  sk "gbr-agent not listening on 127.0.0.1:8788"
fi

echo "== vendor relay =="
if curl -fsS --max-time 15 "$RELAY/v1/bot" >/dev/null 2>&1; then
  disc="$(curl -fsS --max-time 15 "$RELAY/v1/bot")"
  echo "$disc" | grep -q "gbr-relay-bot" && ok "GET /v1/bot discovery (no key)" || ko "unexpected relay discovery"
else
  sk "relay discovery unreachable"
fi
poll_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$RELAY/v1/mb/gbr-example/poll" || true)"
if [[ "$poll_code" == "401" || "$poll_code" == "403" ]]; then
  ok "GET /v1/mb/gbr-example/poll without key -> $poll_code"
else
  sk "poll without key returned HTTP ${poll_code:-none}"
fi

echo "== NemoClaw / OpenShell sandbox =="
if command -v nemoclaw >/dev/null 2>&1 && command -v openshell >/dev/null 2>&1; then
  if openshell sandbox list 2>/dev/null | grep -qE "^[[:space:]]*${SANDBOX_NAME}[[:space:]]"; then
    if openshell sandbox exec --name "$SANDBOX_NAME" -- test -x /sandbox/bin/gbr-operator-ping; then
      ok "sandbox has /sandbox/bin/gbr-operator-ping"
      if openshell sandbox exec --name "$SANDBOX_NAME" -- /sandbox/bin/gbr-operator-ping >/tmp/gbr-pair-ping.out 2>&1; then
        if grep -q "GBR_OPERATOR_PING" /tmp/gbr-pair-ping.out; then
          ok "sandbox operator-ping reached host Bot API"
        else
          ko "sandbox operator-ping missing GBR_OPERATOR_PING"
        fi
      else
        ko "sandbox operator-ping failed"
      fi
    else
      sk "skill not installed; run bash scripts/onboard.sh"
    fi
  else
    sk "sandbox ${SANDBOX_NAME} not found; run bash scripts/onboard.sh"
  fi
else
  sk "nemoclaw/openshell not on PATH; sandbox attach not run"
fi

echo
echo "PASS=$pass SKIP=$skip FAIL=$fail"
if (( fail > 0 )); then
  echo "FAIL: gbr-pair verification"
  exit 1
fi
echo "PASS: gbr-pair verification"
exit 0
