# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deterministic checks over the memory.

Detection is mechanical, so it lives here and can be tested without a model.
Deciding what to do about a finding needs judgment, so that stays in the
repair and consolidation skills. Splitting them this way means a reviewer can
verify that the checks are right, and the skills are left with the part that
genuinely needs reading comprehension.

Every check returns findings rather than fixing anything. Nothing in this
module writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
LINK = re.compile(r"\[[^\]]*\]\(([^)]+\.md)\)")
FOOTNOTE = re.compile(r"\^\[[^\]]+\]")
INFERRED = re.compile(r"\(inferred\)", re.I)

DECAY_DAYS = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90}

# From the growth-control table in schema.md. Detection only: exceeding a
# ceiling is a finding for the consolidation job, not a defect in itself.
CEILINGS = {"recent_interactions": 30}


@dataclass(frozen=True)
class Finding:
    kind: str
    path: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.path} — {self.detail}"


def _frontmatter(text: str) -> dict[str, str]:
    m = FRONTMATTER.match(text)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def _pages(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.md")
                  if p.name not in {"schema.md", "log.md", "index.md"})


def check_index(root: Path) -> list[Finding]:
    """Every page is indexed and every index entry resolves."""
    index = root / "index.md"
    findings: list[Finding] = []
    if not index.exists():
        return [Finding("index-missing", "index.md", "the entry point does not exist")]

    listed = {(index.parent / t).resolve() for t in LINK.findall(index.read_text("utf-8"))}
    for page in _pages(root):
        if page.resolve() not in listed:
            findings.append(Finding("unindexed", str(page.relative_to(root)),
                                    "page has no entry in index.md"))
    for target in sorted(listed):
        if not target.exists():
            findings.append(Finding("index-dangling", "index.md",
                                    f"entry points at missing {target.name}"))
    return findings


def check_links(root: Path) -> list[Finding]:
    """Relative links between pages resolve."""
    findings: list[Finding] = []
    for page in _pages(root) + [root / "index.md"]:
        if not page.exists():
            continue
        for target in LINK.findall(page.read_text("utf-8")):
            if not (page.parent / target).resolve().exists():
                findings.append(Finding("broken-link", str(page.relative_to(root)),
                                        f"link to {target} does not resolve"))
    return findings


def check_decay(root: Path, today: date | None = None) -> list[Finding]:
    """Pages past their decay window are stale.

    Stale is reported, never corrected. Bumping the date would assert a
    freshness the page has not earned.
    """
    today = today or date.today()
    findings: list[Finding] = []
    for page in _pages(root):
        fm = _frontmatter(page.read_text("utf-8"))
        decay, updated = fm.get("decay"), fm.get("updated")
        if not decay or decay not in DECAY_DAYS or not updated:
            continue
        try:
            age = (today - datetime.strptime(updated, "%Y-%m-%d").date()).days
        except ValueError:
            findings.append(Finding("bad-date", str(page.relative_to(root)),
                                    f"updated is not a date: {updated!r}"))
            continue
        if age > DECAY_DAYS[decay]:
            findings.append(Finding("stale", str(page.relative_to(root)),
                                    f"{age}d old, decay is {decay}"))
    return findings


def check_provenance(root: Path) -> list[Finding]:
    """Claims on patterns pages carry a footnote or an inferred marker."""
    findings: list[Finding] = []
    for page in _pages(root):
        if page.parent.name != "patterns":
            continue
        body = FRONTMATTER.sub("", page.read_text("utf-8"))
        prose = [ln for ln in body.splitlines()
                 if ln.strip() and not ln.startswith("#")]
        if prose and not FOOTNOTE.search(body) and not INFERRED.search(body):
            findings.append(Finding("unsourced", str(page.relative_to(root)),
                                    "no provenance footnote and no (inferred) marker"))
    return findings


def check_ceilings(root: Path) -> list[Finding]:
    """Sections over their growth ceiling, reported for consolidation."""
    findings: list[Finding] = []
    limit = CEILINGS["recent_interactions"]
    for page in _pages(root):
        if page.parent.name != "people":
            continue
        lines = page.read_text("utf-8").splitlines()
        try:
            start = next(i for i, ln in enumerate(lines)
                         if ln.strip().lower().startswith("## recent interactions"))
        except StopIteration:
            continue
        count = 0
        for ln in lines[start + 1:]:
            if ln.startswith("## "):
                break
            if ln.strip().startswith("- "):
                count += 1
        if count > limit:
            findings.append(Finding("over-ceiling", str(page.relative_to(root)),
                                    f"Recent Interactions has {count} items, ceiling is {limit}"))
    return findings


def check_all(root: Path, today: date | None = None) -> list[Finding]:
    """Cheap and mechanical first, so a clean run finishes quickly."""
    return (check_index(root) + check_links(root) + check_decay(root, today)
            + check_provenance(root) + check_ceilings(root))
