#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# validate-example.sh — every offline check for this example, one command.
# Stable and teardown-safe: no sandbox, no docker, no network. Requires
# python3 with PyYAML (the policy builder reads/writes OpenShell policy
# YAML). Live checks (policy probes, Jupyter) remain in
# scripts/verify-sandbox-ready.sh.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
fail=0

python3 -c 'import yaml' 2>/dev/null \
  || { echo "FAIL: python3 with PyYAML is required (pip install pyyaml)"; exit 1; }

echo "== syntax =="
syntax_fail=0
while IFS= read -r f; do
  bash -n "$f" || { echo "  FAIL bash -n: $f"; syntax_fail=1; }
done < <(find "$ROOT" -name '*.sh' -not -path '*/.claude/*' \
  -not \( -path "$ROOT/scripts/*" -o -path "$ROOT/agents/*" -o -path "$ROOT/extras/*" \))
# The vendored deployment scripts (scripts/, agents/, extras/ — verbatim from
# the chief-of-staff recipe) target bash >= 4 (associative arrays); macOS's
# bash 3.2 false-positives on them, so sweep them only under bash >= 4.
if [ "${BASH_VERSINFO[0]}" -ge 4 ]; then
  while IFS= read -r f; do
    bash -n "$f" || { echo "  FAIL bash -n: $f"; syntax_fail=1; }
  done < <(find "$ROOT" -name '*.sh' \
    \( -path "$ROOT/scripts/*" -o -path "$ROOT/agents/*" -o -path "$ROOT/extras/*" \))
else
  echo "  note: vendored deployment scripts skipped (bash ${BASH_VERSINFO[0]} < 4)"
fi
while IFS= read -r f; do
  python3 -m py_compile "$f" || { echo "  FAIL py_compile: $f"; syntax_fail=1; }
done < <(find "$ROOT" -name '*.py' -not -path '*/.claude/*' -not -path '*/__pycache__/*')
python3 - "$ROOT" <<'EOF' || syntax_fail=1
import glob, sys, yaml
for f in glob.glob(sys.argv[1] + "/**/*.yaml", recursive=True):
    list(yaml.safe_load_all(open(f)))
EOF
if [ "$syntax_fail" = 0 ]; then echo "  syntax OK"; else echo "  syntax FAIL"; fail=1; fi

echo "== unit tests =="
python3 -m unittest discover -s "$HERE" -p 'test_*.py' -q || fail=1

echo "== vendored deployment tests =="
dep_fail=0
# test_generate_config.py drives generate-config.ts via
# `node --experimental-strip-types` (node >= 22); skip only that file on
# older hosts — CI installs node 22, so drift is always caught there.
if node -e 'process.exit(parseInt(process.versions.node) >= 22 ? 0 : 1)' 2>/dev/null; then
  python3 -m unittest discover -s "$ROOT/agents/hermes/tests" -p 'test_*.py' -q || dep_fail=1
else
  echo "  note: node >= 22 not found — skipping test_generate_config.py"
  for f in "$ROOT"/agents/hermes/tests/test_*.py; do
    [ "$(basename "$f")" = "test_generate_config.py" ] && continue
    python3 -m unittest discover -s "$ROOT/agents/hermes/tests" -p "$(basename "$f")" -q || dep_fail=1
  done
fi
# The NVTeam in-image skill ships its own validator tests (relative imports —
# discover from its directory).
(cd "$ROOT/agents/hermes/skills/nemoclaw-nvteam/scripts/tests" && python3 -m unittest discover -s . -q) || dep_fail=1
if [ "$dep_fail" = 0 ]; then echo "  deployment tests OK"; else echo "  deployment tests FAIL"; fail=1; fi

echo "== operator script behavior =="
bash "$HERE/test_operator_scripts.sh" || fail=1

find "$ROOT" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null

echo
[ "$fail" = 0 ] && echo "VALIDATE: PASS" || echo "VALIDATE: FAIL"
exit "$fail"
