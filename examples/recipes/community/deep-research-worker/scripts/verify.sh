#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(dirname "$SCRIPT_DIR")"

echo "== 1/5 shell syntax =="
bash -n "$EXAMPLE_DIR"/scripts/*.sh

echo "== 2/5 python syntax =="
python3 -m py_compile "$EXAMPLE_DIR"/src/*.py

echo "== 3/5 behavioral tests =="
if python3 -c 'import deepagents, fastapi, httpx' >/dev/null 2>&1; then
  PYTHONPATH="$EXAMPLE_DIR/src" python3 -m unittest discover \
    -s "$EXAMPLE_DIR/src/tests" -p 'test_*.py' -v
else
  verify_image="deep-research-worker-verify:$$"
  cleanup_verify_image() {
    docker image rm "$verify_image" >/dev/null 2>&1 || true
  }
  trap cleanup_verify_image EXIT
  docker build -t "$verify_image" -f "$EXAMPLE_DIR/src/Dockerfile" "$EXAMPLE_DIR/src"
  docker run --rm \
    -e DEEPAGENTS_SERVICE_SECRET=verification-only \
    -e OPENAI_API_KEY=verification-only \
    "$verify_image" python -m unittest discover -s tests -p 'test_*.py' -v
  cleanup_verify_image
  trap - EXIT
fi

echo "== 4/5 compose rendering =="
DEEPAGENTS_SERVICE_SECRET=verification-only \
  docker compose -f "$EXAMPLE_DIR/docker-compose.yml" config >/dev/null

echo "== 5/5 policy and skill metadata =="
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
