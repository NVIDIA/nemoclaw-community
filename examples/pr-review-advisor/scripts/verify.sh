#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

static_only=0
if [[ "${1:-}" == "--static-only" ]]; then
  static_only=1
elif [[ $# -gt 0 ]]; then
  echo "Usage: verify.sh [--static-only]" >&2
  exit 2
fi

pass() { printf '  [ok] %s\n' "$1"; }
fail() { printf '  [!!] %s\n' "$1" >&2; exit 1; }

for script in "$EXAMPLE_DIR"/scripts/*.sh "$EXAMPLE_DIR"/agents/hermes/start.sh; do
  bash -n "$script" || fail "bash syntax: $script"
done
pass "shell syntax"

python3 - "$EXAMPLE_DIR" <<'PY' || exit 1
import ast
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
for parent in (root / "scripts", root / "agents" / "hermes"):
    for path in parent.rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
PY
pass "Python syntax"

node --experimental-strip-types --check \
  "$EXAMPLE_DIR/agents/hermes/generate-config.ts" >/dev/null || fail "config generator syntax"
pass "Hermes config generator syntax"

if python3 -c 'import yaml' >/dev/null 2>&1; then
  python3 - "$EXAMPLE_DIR" <<'PY' || exit 1
import pathlib
import sys
import yaml

root = pathlib.Path(sys.argv[1])
for relative in (
    "policy.yaml",
    "review-profiles/generic.yaml",
    "review-profiles/nemoclaw.yaml",
    "agents/hermes/plugins/review-advisor/plugin.yaml",
):
    path = root / relative
    with path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise SystemExit(f"{relative}: expected a YAML object")
PY
  pass "YAML checks"
else
  printf '  [skip] YAML semantic checks (optional host PyYAML is not installed)\n'
fi

python3 - "$EXAMPLE_DIR" <<'PY' || exit 1
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
for path in root.rglob("*"):
    if not path.is_file() or path.name.startswith(".env"):
        continue
    if any(
        part
        in {
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".tox",
            ".venv",
            "__pycache__",
            "node_modules",
        }
        for part in path.parts
    ) or path.suffix in {".png", ".gz", ".pyc"}:
        continue
    text = path.read_text(encoding="utf-8")
    if path.name in {"LICENSE", "package.json", "package-lock.json"}:
        continue
    if path.name == "SKILL.md" and "license: Apache-2.0" in text:
        continue
    if "SPDX-License-Identifier: Apache-2.0" not in text:
        raise SystemExit(f"{path.relative_to(root)}: missing SPDX license")
PY
pass "SPDX checks"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "$EXAMPLE_DIR"/scripts/*.sh "$EXAMPLE_DIR"/agents/hermes/start.sh \
    || fail "shellcheck"
  pass "shellcheck"
fi

if [[ "$static_only" == 1 ]]; then
  echo "Static verification complete."
  exit 0
fi

scrub_external_secrets
load_env
scrub_external_secrets
require_command curl
require_command openshell
validate_port "$HERMES_FORWARD_PORT"
acquire_review_lock
trap release_review_lock EXIT INT TERM
assert_sandbox_ready
assert_inference_route
if run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" --timeout 45 -- \
  /opt/hermes/.venv/bin/python /opt/review-advisor/probe-inference.py \
    "$NEMOCLAW_MODEL"; then
  pass "sandbox inference route"
else
  fail "sandbox inference route"
fi
start_forward
if curl -fsS --max-time 3 "http://127.0.0.1:${HERMES_FORWARD_PORT}/health" >/dev/null; then
  pass "Hermes loopback API"
else
  fail "Hermes loopback API"
fi
if run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
  test -f /sandbox/.hermes/plugins/review-advisor/plugin.yaml; then
  pass "review-advisor plugin"
else
  fail "review-advisor plugin"
fi
if run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
  test -f /sandbox/.hermes/skills/pr-review/SKILL.md; then
  pass "pr-review skill"
else
  fail "pr-review skill"
fi
toolsets="$(
  run_openshell sandbox exec --name "$NEMOCLAW_SANDBOX_NAME" -- \
    awk '
      /^platform_toolsets:/ { in_platform = 1; next }
      in_platform && /^  api_server:/ { in_api = 1; next }
      in_api && /^    - / { sub(/^    - /, ""); print; next }
      in_api { exit }
    ' /sandbox/.hermes/config.yaml
)"
if [[ "$toolsets" != "review-advisor" ]]; then
  fail "review API toolsets must contain only review-advisor"
else
  pass "review API exposes only the read-only review-advisor toolset"
fi
echo "Runtime verification complete."
