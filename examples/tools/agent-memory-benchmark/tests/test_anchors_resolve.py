# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Every in-page link must land on a heading that exists.

The root README's contents used bare anchors (`#what-a-run-looks-like`) while
its own body links used the form GitHub actually emits for an emoji heading
(`#-what-a-run-looks-like`). Sixteen entries pointed at nothing, and the file
disagreed with itself about which form was right.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PAGES = [
    REPO / "README.md",
    REPO / "results" / "README.md",
    REPO / "corpus_a" / "README.md",
    REPO / "corpus_b" / "README.md",
    *sorted((REPO / "docs").glob("*.md")),
]

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF←-⯿☀-➿]")
_VARIATION_SELECTOR = "️"


def _slug(heading: str) -> str:
    """The anchor GitHub emits: the emoji goes, the space after it stays.

    A variation selector is not an emoji and is kept, which is why an anchor for
    `## 🗂️ Layout` begins with it and one for `## 🚀 Getting Started` does not.
    """
    kept = "".join(
        c for c in heading
        if c == _VARIATION_SELECTOR or not _EMOJI.match(c))
    kept = re.sub(rf"[^\w\s\-{_VARIATION_SELECTOR}]", "", kept.lower())
    return "#" + re.sub(r"\s+", "-", kept.rstrip())


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.name if p.parent == REPO else f"{p.parent.name}/{p.name}"))
def test_every_in_page_link_resolves(page: Path):
    text = page.read_text(encoding="utf-8")
    fenced = re.sub(r"```.*?```", "", text, flags=re.S)
    headings = {_slug(line[3:].strip())
                for line in fenced.splitlines() if line.startswith("## ")}
    headings |= {_slug(line[4:].strip())
                 for line in fenced.splitlines() if line.startswith("### ")}
    links = set(re.findall(r"\]\((#[^)]+)\)", fenced))
    dead = sorted(link for link in links if link not in headings)
    assert not dead, (
        f"{page.relative_to(REPO)} links to {dead}, which match no heading. "
        f"Headings resolve to: {sorted(headings)}")
