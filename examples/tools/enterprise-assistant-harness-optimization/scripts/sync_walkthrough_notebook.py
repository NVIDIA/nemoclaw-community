#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Render the walkthrough as a sectioned, text-faithful Jupyter notebook."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "walkthrough.md"
TARGET = ROOT / "docs" / "walkthrough.ipynb"


def render() -> str:
    sections: list[list[str]] = []
    for line in SOURCE.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.startswith("## ") or not sections:
            sections.append([])
        sections[-1].append(line)

    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "id": f"section-{index:02d}",
                "metadata": {},
                "source": section,
            }
            for index, section in enumerate(sections, start=1)
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return json.dumps(notebook, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != expected:
            parser.exit(1, "walkthrough.ipynb is out of sync; run scripts/sync_walkthrough_notebook.py\n")
        print("walkthrough notebook matches walkthrough.md")
        return 0
    TARGET.write_text(expected, encoding="utf-8")
    print(f"Wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
