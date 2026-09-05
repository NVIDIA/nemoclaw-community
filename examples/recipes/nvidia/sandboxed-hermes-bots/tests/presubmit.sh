#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Gate before a public push: no credentials, no internal hostnames, SPDX on
# every source file, shell syntax clean, executables executable. Runs anywhere
# (no host, no Docker). Exit 0 means push.
set -uo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.."
# A tree copied from macOS with tar/scp carries AppleDouble ._* files; they are
# noise, not source. Drop them so the checks below judge the real files.
find . -name '._*' -not -path './.git/*' -delete 2>/dev/null

fail=0
say()  { printf '  %-4s %s\n' "$1" "$2"; }
bad()  { say FAIL "$1"; fail=1; }
good() { say ok "$1"; }

# 1. credentials and key-shaped strings
pat='lsv2_pt_[A-Za-z0-9]{6}|tvly-[A-Za-z0-9]{8}|gh[po]_[A-Za-z0-9]{8}|github_pat_[A-Za-z0-9]|sk-[A-Za-z0-9]{16}|AKIA[0-9A-Z]{12}|-----BEGIN [A-Z ]*PRIVATE KEY|nvapi-[A-Za-z0-9]{8}'
hits=$(grep -rInE "$pat" . --exclude-dir=.git 2>/dev/null | grep -viE 'example|placeholder|YOUR_|<your|\.tmpl|presubmit' || true)
[[ -z "$hits" ]] && good "no credential-shaped strings" || { bad "credential-shaped strings:"; printf '%s\n' "$hits" | sed 's/^/         /'; }

# 2. internal hostnames and addresses
hosts='nvaie-tme|omni-lsn|omnistation|poc-nvaie|\.nvidia\.com|10\.187\.|169\.254\.'
hits=$(grep -rInE "$hosts" . --exclude-dir=.git --exclude='*.log' 2>/dev/null | grep -viE 'inference-api\.nvidia\.com|docs\.nvidia\.com|developer\.nvidia\.com|github\.com/NVIDIA|presubmit' || true)
[[ -z "$hits" ]] && good "no internal hostnames" || { bad "internal hostnames:"; printf '%s\n' "$hits" | sed 's/^/         /'; }

# 3. SPDX header on every source file
missing=$(find . -type f \( -name '*.sh' -o -name '*.py' -o -name '*.yaml' -o -name '*.tmpl' -o -name 'Dockerfile*' -o -name 'swarm' -o -name 'swarm.env.example' \) \
  -not -path './.git/*' -not -path '*/__pycache__/*' \
  | while read -r f; do grep -q 'SPDX-License-Identifier' "$f" || echo "$f"; done)
[[ -z "$missing" ]] && good "SPDX headers present" || { bad "missing SPDX:"; printf '%s\n' "$missing" | sed 's/^/         /'; }

# 4. shell syntax
bad_sh=$(for f in swarm lib/*.sh tests/*.sh; do bash -n "$f" 2>&1 | sed "s|^|$f: |"; done)
[[ -z "$bad_sh" ]] && good "shell syntax" || { bad "shell syntax:"; printf '%s\n' "$bad_sh" | sed 's/^/         /'; }

# 5. python syntax
if command -v python3 >/dev/null; then
  bad_py=$(find plugins examples/plugins -name '*.py' -not -path '*/__pycache__/*' -exec python3 -m py_compile {} \; 2>&1)
  [[ -z "$bad_py" ]] && good "python syntax" || { bad "python syntax:"; printf '%s\n' "$bad_py" | sed 's/^/         /'; }
  find plugins examples/plugins -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null

  if unit_out=$(python3 -m unittest discover -s tests -p 'test_*.py' 2>&1); then
    good "python regression tests"
  else
    bad "python regression tests:"
    printf '%s\n' "$unit_out" | sed 's/^/         /'
  fi
fi

# 6. executables
for f in swarm tests/e2e.sh tests/lifecycle.sh tests/presubmit.sh; do
  [[ -x "$f" ]] && good "$f executable" || bad "$f not executable (chmod +x)"
done

# 7. no tracked state, logs, keys
stray=$(git ls-files 2>/dev/null | grep -E '(^|/)(keys|logs|secrets)/|\.key$|\.log$|^swarm\.env$' || true)
[[ -z "$stray" ]] && good "no tracked state or secrets" || { bad "tracked state/secrets:"; printf '%s\n' "$stray" | sed 's/^/         /'; }

# 8. the skill points at commands that exist
for c in $(grep -oE '\./swarm [a-z][a-z-]*' skill/SKILL.md | awk '{print $2}' | sort -u); do
  grep -qE "^  $c\)" swarm || bad "skill mentions './swarm $c' but swarm has no such command"
done
good "skill commands resolve"

# 9. lifecycle/ownership tests use only a temporary HOME and mocked commands.
if lifecycle_out=$(tests/lifecycle.sh 2>&1); then
  good "isolated lifecycle tests"
else
  bad "isolated lifecycle tests:"
  printf '%s\n' "$lifecycle_out" | sed 's/^/         /'
fi

echo
(( fail == 0 )) && echo "  presubmit: PASS" || { echo "  presubmit: FAIL"; exit 1; }
