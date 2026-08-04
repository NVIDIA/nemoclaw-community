#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Offline behavioral tests for the operator scripts, using a PATH-stubbed
# docker. Covers: fail-closed container selection, transactional skill
# staging (order, scoping, failure isolation), and the secrets.env merge.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
OPS="$HERE/../skills/setup-workshop-nemoclaw-operator/scripts"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  PASS  $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL  $1"; }
check(){ if eval "$2"; then ok "$1"; else bad "$1"; fi; }

# ---- docker stub: behavior driven by env, calls logged ----------------------
mkdir -p "$WORK/bin"
cat > "$WORK/bin/docker" <<'STUB'
#!/usr/bin/env bash
echo "docker $*" >> "$DOCKER_LOG"
case "$1" in
  ps)   printf '%s' "$STUB_PS_OUTPUT"; [ -n "$STUB_PS_OUTPUT" ] && echo ;;
  cp)   [ "${STUB_FAIL_CP_FOR:-}" ] && [[ "$*" == *"$STUB_FAIL_CP_FOR"* ]] && exit 1; exit 0 ;;
  exec) exit 0 ;;
  *)    exit 0 ;;
esac
STUB
chmod +x "$WORK/bin/docker"
export PATH="$WORK/bin:$PATH"
export DOCKER_LOG="$WORK/docker.log"

echo "== container selection (lib.sh resolve_sandbox_container) =="
. "$OPS/lib.sh"
: > "$DOCKER_LOG"
STUB_PS_OUTPUT="" \
  check "zero matches -> fails closed" '! resolve_sandbox_container demo 2>/dev/null'
STUB_PS_OUTPUT="openshell-default--demo-1111" \
  check "one match -> resolves" '[ "$(resolve_sandbox_container demo)" = "openshell-default--demo-1111" ]'
STUB_PS_OUTPUT="$(printf 'openshell-default--demo-1111\nopenshell-default--demo-2-2222')" \
  check "two matches -> fails closed" '! resolve_sandbox_container demo 2>/dev/null'

echo "== transactional staging (stage-skills.sh) =="
EX="$WORK/example"
mkdir -p "$EX/skills/alpha" "$EX/skills/beta" "$EX/skills/setup-workshop-nemoclaw-operator"
: > "$DOCKER_LOG"
STUB_PS_OUTPUT="openshell-default--demo-1111" SANDBOX=demo EXAMPLE="$EX" \
  bash "$OPS/stage-skills.sh" > "$WORK/stage.out" 2>&1
check "operator skill excluded from staging" \
  '! grep -q "setup-workshop-nemoclaw-operator" "$DOCKER_LOG"'
check "copies land in hidden temp dirs" \
  'grep -q "docker cp $EX/skills/alpha/ .*:.*/.stage-alpha" "$DOCKER_LOG"'
check "chown scoped to staged dir only (never the library root)" \
  'grep -q "chown -R sandbox:sandbox /sandbox/.hermes-data/skills/.stage-alpha" "$DOCKER_LOG" &&
   ! grep -qE "chown -R sandbox:sandbox /sandbox/.hermes-data/skills($| )" "$DOCKER_LOG"'
check "swap is a single exec of rm-then-mv" \
  'grep -q "sh -c rm -rf ./sandbox/.hermes-data/skills/alpha. && mv ./sandbox/.hermes-data/skills/.stage-alpha. ./sandbox/.hermes-data/skills/alpha." "$DOCKER_LOG"'
check "chown happens before the swap" \
  '[ "$(grep -n "chown.*stage-alpha" "$DOCKER_LOG" | cut -d: -f1)" -lt "$(grep -n "mv ./sandbox/.hermes-data/skills/.stage-alpha" "$DOCKER_LOG" | cut -d: -f1)" ]'

: > "$DOCKER_LOG"
STUB_PS_OUTPUT="openshell-default--demo-1111" STUB_FAIL_CP_FOR="alpha" SANDBOX=demo EXAMPLE="$EX" \
  bash "$OPS/stage-skills.sh" > "$WORK/stage-fail.out" 2>&1
check "failed copy -> existing skill never removed (no swap ran)" \
  '! grep -q "rm -rf ./sandbox/.hermes-data/skills/alpha" "$DOCKER_LOG"'

echo "== secrets.env merge (embedded python from stage-nvidia-key.sh) =="
# Test the exact shipped merge code: extract the python3 -c payload.
sed -n "/python3 -c '/,/^' \"\$DEST\"/p" "$OPS/stage-nvidia-key.sh" | sed '1d;$d' > "$WORK/merge.py"
DEST="$WORK/secrets.env"
printf 'OTHER_KEY=keep-me\nNVIDIA_API_KEY=old\n' > "$DEST"
printf 'NVIDIA_API_KEY=nvapi-new\nTAVILY_API_KEY=tvly-x\n' | python3 "$WORK/merge.py" "$DEST"
check "merge preserves unrelated keys"    'grep -q "^OTHER_KEY=keep-me$" "$DEST"'
check "merge replaces the staged key"     'grep -q "^NVIDIA_API_KEY=nvapi-new$" "$DEST"'
check "merge appends new keys"            'grep -q "^TAVILY_API_KEY=tvly-x$" "$DEST"'
check "merge tightens mode to 600"        '[ "$(stat -c %a "$DEST")" = "600" ]'

echo
echo "$PASS passed, $FAIL failed"
exit $((FAIL > 0))
