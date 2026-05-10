#!/usr/bin/env bash
# setup.sh — one-shot configuration of an already-onboarded sandbox.
#
# Run this AFTER `nemohermes onboard` and AFTER you've switched
# the gateway to Omni (see Part 2 of the guide). It applies the lookup
# policy, installs the two skills, uploads the scripts and SOUL.md, and
# fixes the two display labels that still say "Super 120B".
#
# Usage:
#   SANDBOX=my-hermes bash scripts/setup.sh
#
# Defaults:
#   SANDBOX  : my-hermes (override with env var)
set -euo pipefail

# Bootstrap nvm if present so this works over non-login SSH (cron, systemd).
[ -s "$HOME/.nvm/nvm.sh" ] && \. "$HOME/.nvm/nvm.sh"

HERE=$(cd "$(dirname "$0")/.." && pwd)
if [[ -f "$HERE/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$HERE/.env"
    set +a
fi

SANDBOX="${SANDBOX:-my-hermes}"
HERMES_CLI="${HERMES_CLI:-nemohermes}"

echo "→ sandbox: $SANDBOX"
echo "→ source:  $HERE"
echo

if ! command -v "$HERMES_CLI" >/dev/null 2>&1; then
    echo "✗ $HERMES_CLI CLI not found. Install current NemoClaw/NemoHermes, then run: nemohermes onboard" >&2
    exit 1
fi

# Verify the sandbox actually exists before doing anything destructive.
if ! "$HERMES_CLI" "$SANDBOX" status >/dev/null 2>&1; then
    echo "✗ sandbox '$SANDBOX' not found." >&2
    echo "  available sandboxes:" >&2
    "$HERMES_CLI" list 2>&1 | sed -n '/Sandboxes:/,/^$/p' | tail -n +2 >&2
    echo "  Set SANDBOX=<name> or run: nemohermes onboard" >&2
    exit 1
fi

# Hermes config/state: /sandbox/.hermes can be a read-only front door with
# symlinks into the mutable state dir. Prefer the writable data dir when present.
# In current images this resolves to /sandbox/.hermes-data, so config edits
# target /sandbox/.hermes-data/config.yaml, script uploads land at
# /sandbox/.hermes-data/workspace/, and SOUL.md lands at
# /sandbox/.hermes-data/memories/SOUL.md.
# One line: openshell rejects newlines inside exec command arguments (gRPC).
HERMES_STATE=$(openshell sandbox exec -n "$SANDBOX" -- bash -c \
  'for d in /sandbox/.hermes-data /sandbox/.hermes; do if [ -f "$d/config.yaml" ] && [ -d "$d/workspace" ] && [ -d "$d/memories" ]; then echo "$d"; exit; fi; done; echo MISSING' \
  | tr -d '\r\n[:space:]')
if [[ "$HERMES_STATE" == "MISSING" ]]; then
    echo "✗ Hermes state not found under /sandbox/.hermes-data or /sandbox/.hermes." >&2
    exit 1
fi

# ── 1. fix the two display labels (gateway route is set separately) ──
echo "[1/6] fixing display labels"
openshell sandbox exec -n "$SANDBOX" -- bash -c \
  "sed -i 's|nvidia/nemotron-3-super-120b-a12b|nvidia/nemotron-3-nano-omni-30b-a3b-reasoning|' ${HERMES_STATE}/config.yaml"

# Long-video skill can take 5-10 minutes on a 2hr+ recording (audio
# transcription is multiple pieces). Hermes's default terminal-tool
# timeout (180s) kills it with exit 124. Bump to 30 min so the skill
# has room to finish.
openshell sandbox exec -n "$SANDBOX" -- bash -c \
  "sed -i 's|^  timeout: 180$|  timeout: 1800|' ${HERMES_STATE}/config.yaml"

# ── 2. add Phoenix/NemoFlow project metadata when requested ──
echo "[2/6] configuring Phoenix/NemoFlow project metadata"
if [[ -n "${PHOENIX_COLLECTOR_ENDPOINT:-}" ]]; then
    NEMO_FLOW_PROJECT_NAME="${NEMO_FLOW_PROJECT_NAME:-hermes-omni-demo}"
    openshell sandbox exec -n "$SANDBOX" -- env \
      CONFIG_PATH="${HERMES_STATE}/config.yaml" \
      PHOENIX_COLLECTOR_ENDPOINT="$PHOENIX_COLLECTOR_ENDPOINT" \
      NEMO_FLOW_PROJECT_NAME="$NEMO_FLOW_PROJECT_NAME" \
      python3 -c '
import os
from pathlib import Path
try:
    import yaml
except Exception as exc:
    print(f"    warning: PyYAML unavailable in sandbox; skipped NemoFlow config ({exc})")
    raise SystemExit(0)

path = Path(os.environ["CONFIG_PATH"])
project = os.environ["NEMO_FLOW_PROJECT_NAME"].strip()
endpoint = os.environ["PHOENIX_COLLECTOR_ENDPOINT"].strip()
cfg = yaml.safe_load(path.read_text()) or {}
cfg["nemo_flow"] = {
    "enabled": True,
    "openinference": {
        "enabled": True,
        "transport": "http_binary",
        "endpoint": endpoint,
        "service_name": project,
        "instrumentation_scope": f"{project}/nemo-flow/openinference",
        "resource_attributes": {
            "openinference.project.name": project,
            "nemo.claw.example": project,
        },
    },
}
path.write_text(yaml.safe_dump(cfg, sort_keys=False))
print(f"    project: {project}")
'
else
    echo "    skipped (PHOENIX_COLLECTOR_ENDPOINT is not set)"
fi

python3 - "$SANDBOX" <<'PY'
import json, pathlib, sys
sandbox = sys.argv[1]
p = pathlib.Path.home() / '.nemoclaw' / 'sandboxes.json'
if not p.exists():
    print(f"    note: {p} not found — skipping host metadata update")
    sys.exit(0)
d = json.load(open(p))
sandboxes = d.get("sandboxes", {})
if sandbox not in sandboxes:
    print(f"    warning: {sandbox!r} not in {p}; available: {sorted(sandboxes)}")
    sys.exit(0)
sandboxes[sandbox]["model"] = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
json.dump(d, open(p, "w"), indent=4)
print("    host metadata updated")
PY

# ── 3. apply the lookup policy ──
echo "[3/6] applying lookup policy (Wikipedia + Free Dictionary)"
raw_policy=$(mktemp)
current_policy=$(mktemp)
trap 'rm -f "$raw_policy" "$current_policy"' EXIT

openshell policy get "$SANDBOX" --full > "$raw_policy"
awk '/^---$/{seen=1; next} seen' "$raw_policy" > "$current_policy"
cat "$HERE/policy.yaml" >> "$current_policy"
openshell policy set --policy "$current_policy" "$SANDBOX"

# ── 4. install the skills ──
echo "[4/6] installing skills"
"$HERMES_CLI" "$SANDBOX" skill install "$HERE/agents/hermes/skills/video-analyze"
"$HERMES_CLI" "$SANDBOX" skill install "$HERE/agents/hermes/skills/jargon-lookup"

# ── 5. upload scripts ──
echo "[5/6] uploading scripts"
openshell sandbox upload "$SANDBOX" "$HERE/agents/hermes/workspace/omni-video-analyze.py" \
  "${HERMES_STATE}/workspace/"
openshell sandbox upload "$SANDBOX" "$HERE/agents/hermes/workspace/lookup-jargon.py" \
  "${HERMES_STATE}/workspace/"
openshell sandbox exec -n "$SANDBOX" -- chmod +x \
  "${HERMES_STATE}/workspace/omni-video-analyze.py" \
  "${HERMES_STATE}/workspace/lookup-jargon.py"

# ── 6. upload SOUL.md to both locations ──
# Canonical copy under memories/; also at Hermes home root where some images
# keep SOUL.md for the agent entrypoint.
echo "[6/6] uploading SOUL.md"
openshell sandbox upload "$SANDBOX" "$HERE/agents/hermes/SOUL.md" \
  "${HERMES_STATE}/memories/"
openshell sandbox upload "$SANDBOX" "$HERE/agents/hermes/SOUL.md" \
  "${HERMES_STATE}/"

# ── 6. verify the SOUL.md is readable through the path Hermes uses ──
expected=$(wc -c < "$HERE/agents/hermes/SOUL.md")
actual=$(openshell sandbox exec -n "$SANDBOX" -- bash -c \
    "wc -c </sandbox/.hermes/SOUL.md 2>/dev/null || wc -c <${HERMES_STATE}/SOUL.md 2>/dev/null || wc -c <${HERMES_STATE}/memories/SOUL.md" \
    | tr -d '[:space:]')
if [[ "$actual" != "$expected" ]]; then
    echo "✗ SOUL.md verification failed: expected $expected bytes, got $actual" >&2
    echo "  Hermes will not see the demo's tool instructions." >&2
    exit 1
fi
echo "    verified SOUL.md visible to Hermes ($expected bytes)"

echo
echo "✓ setup complete"
echo
echo "Next:"
echo "  bash scripts/start.sh        # build UI + run server on http://localhost:8765"
