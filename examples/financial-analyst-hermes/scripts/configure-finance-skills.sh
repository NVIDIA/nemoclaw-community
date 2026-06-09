#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

SANDBOX_NAME="${1:-${NEMOCLAW_SANDBOX_NAME:-financial-analyst}}"

KEEP_SKILLS="${FINANCE_KEEP_SKILLS:-financial-market-snapshot,sec-company-facts,financial-analyst-brief,financial-analyst-playbook,nemoclaw-openshell-runtime-context}"

echo "Scoping Hermes skills for sandbox: ${SANDBOX_NAME}"
echo "Keeping: ${KEEP_SKILLS}"

nemohermes "${SANDBOX_NAME}" exec -- /bin/sh -lc '
set -euo pipefail
export HOME=/sandbox
export PYTHONPATH=/opt/hermes

/opt/hermes/.venv/bin/python - "$1" <<'"'"'PY'"'"'
import sys

from hermes_cli.config import load_config
from hermes_cli.skills_config import save_disabled_skills
from tools.skills_tool import _find_all_skills

keep = {item.strip() for item in sys.argv[1].split(",") if item.strip()}
skills = _find_all_skills(skip_disabled=True)
all_names = {skill["name"] for skill in skills}
missing = sorted(keep - all_names)
disabled = {name for name in all_names if name not in keep}

config = load_config()
save_disabled_skills(config, disabled)

print(f"enabled={len(all_names - disabled)} disabled={len(disabled)}")
if missing:
    print("missing_keep_skills=" + ",".join(missing))
PY
' sh "${KEEP_SKILLS}"

echo "Done. New Hermes sessions will use the scoped financial skill set."
echo "If a gateway is already running, ask the agent to reload skills or restart the sandbox."
