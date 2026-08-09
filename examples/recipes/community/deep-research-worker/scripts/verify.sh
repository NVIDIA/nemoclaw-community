#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(dirname "$SCRIPT_DIR")"

echo "== 1/4 shell syntax =="
bash -n "$EXAMPLE_DIR"/scripts/*.sh

echo "== 2/4 python syntax =="
python3 -m py_compile "$EXAMPLE_DIR"/src/*.py

echo "== 3/4 compose rendering =="
docker compose -f "$EXAMPLE_DIR/docker-compose.yml" config >/dev/null

echo "== 4/4 policy and skill metadata =="
python3 - "$EXAMPLE_DIR" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
skill = (root / "src" / "SKILL.md").read_text(encoding="utf-8")
policy = (root / "policies" / "deep-research-worker.yaml").read_text(encoding="utf-8")

if not skill.startswith("---\n"):
    raise SystemExit("SKILL.md is missing YAML frontmatter")
if "name: deep-research" not in skill:
    raise SystemExit("SKILL.md is missing the deep-research skill name")
if "host.openshell.internal" not in policy or "9050" not in policy:
    raise SystemExit("policy file does not contain the expected worker route")
PY

echo "PASS: deep-research-worker local verification"
