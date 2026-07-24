#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Install guide-owned always-on Hermes instructions inside a sandbox."""

from pathlib import Path


START = "<!-- nemoclaw-blender-host-boundary:start -->"
END = "<!-- nemoclaw-blender-host-boundary:end -->"
FRAGMENT = Path("/sandbox/blender-host-boundary.md")
TARGETS = (
    Path("/sandbox/.hermes/SOUL.md"),
    Path("/sandbox/.hermes/dashboard-home/SOUL.md"),
)


def replace_managed_block(current: str, block: str) -> str:
    if START in current and END in current:
        prefix, remainder = current.split(START, 1)
        _, suffix = remainder.split(END, 1)
        return f"{prefix.rstrip()}\n\n{block}\n{suffix.lstrip()}".rstrip() + "\n"
    return f"{current.rstrip()}\n\n{block}\n"


fragment = FRAGMENT.read_text(encoding="utf-8").strip()
managed = f"{START}\n{fragment}\n{END}"

for target in TARGETS:
    target.parent.mkdir(parents=True, exist_ok=True)
    current = target.read_text(encoding="utf-8") if target.exists() else ""
    target.write_text(replace_managed_block(current, managed), encoding="utf-8")
    print(f"updated {target}")
