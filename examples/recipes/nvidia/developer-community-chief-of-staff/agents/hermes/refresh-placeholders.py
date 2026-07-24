#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Rewrite Hermes's .env file with OpenShell provider placeholders.

Called by start.sh at sandbox boot. Reads NEMOCLAW_PROVIDER_PLACEHOLDER_KEYS
(a space-separated list of env var names) and for each one whose value starts
with `openshell:resolve:env:`, ensures the target env file has the canonical
placeholder string. Idempotent — no-op if values already match. Symlink guard
lives in the bash caller.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: refresh-placeholders.py <env_file>", file=sys.stderr)
        return 2

    env_file = sys.argv[1]
    prefix = "openshell:resolve:env:"
    keys = os.environ.get("NEMOCLAW_PROVIDER_PLACEHOLDER_KEYS", "").split()
    replacements = {}

    for key in keys:
        value = os.environ.get(key, "")
        if value.startswith(prefix):
            # OpenShell may inject revision-pinned placeholders into process env
            # (for example, openshell:resolve:env:v123_KEY). Hermes persists this
            # file for long-running bridges, so store the stable provider lookup.
            replacements[key] = f"{prefix}{key}"

    if not replacements:
        return 0

    with open(env_file, encoding="utf-8") as f:
        lines = f.readlines()

    changed = False
    updated: list[str] = []
    seen: set[str] = set()
    for line in lines:
        stripped = line.rstrip("\n")
        replaced = False
        for key, value in replacements.items():
            if stripped.startswith(f"{key}="):
                new_line = f"{key}={value}\n"
                updated.append(new_line)
                seen.add(key)
                changed = changed or new_line != line
                replaced = True
                break
        if not replaced:
            updated.append(line)

    for key, value in replacements.items():
        if key not in seen:
            updated.append(f"{key}={value}\n")
            changed = True

    if not changed:
        return 0

    with open(env_file, "w", encoding="utf-8") as f:
        f.writelines(updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
