#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# validate-example.sh — every offline check for this example, one command.
# Stable and teardown-safe: no sandbox, no docker, no network. Live checks
# (policy probes, Jupyter) remain in scripts/verify-sandbox-ready.sh.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
fail=0

echo "== syntax =="
while IFS= read -r f; do
  bash -n "$f" || { echo "  FAIL bash -n: $f"; fail=1; }
done < <(find "$ROOT" -name '*.sh' -not -path '*/.claude/*')
while IFS= read -r f; do
  python3 -m py_compile "$f" || { echo "  FAIL py_compile: $f"; fail=1; }
done < <(find "$ROOT" -name '*.py' -not -path '*/.claude/*' -not -path '*/__pycache__/*')
python3 - "$ROOT" <<'EOF' || fail=1
import glob, sys, yaml
for f in glob.glob(sys.argv[1] + "/**/*.yaml", recursive=True):
    list(yaml.safe_load_all(open(f)))
EOF
find "$ROOT" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
echo "  syntax OK"

echo "== unit tests =="
python3 -m unittest discover -s "$HERE" -p 'test_*.py' -q || fail=1

echo "== operator script behavior =="
bash "$HERE/test_operator_scripts.sh" || fail=1

echo
[ "$fail" = 0 ] && echo "VALIDATE: PASS" || echo "VALIDATE: FAIL"
exit "$fail"
