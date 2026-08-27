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

# Required frontmatter per page type, from schema.md. The directory a page
# lives in determines its type; `index.md` is checked separately because it is
# the entry point rather than a page.
REQUIRED_FIELDS = {
    "people": ("name", "role", "relationship", "importance",
               "last_interaction", "interaction_frequency"),
    "projects": ("name", "priority", "role", "updated"),
    "patterns": ("type", "updated", "decay"),
    "concepts": ("type", "updated"),
    "goals": ("type", "timeframe", "updated", "decay"),
    "attention": ("type", "updated", "decay"),
}
INDEX_REQUIRED = ("type", "updated")

# Fields whose value must come from a fixed set, again from schema.md.
ENUMS = {
    "importance": {"high", "medium", "low"},
    "interaction_frequency": {"daily", "weekly", "monthly", "rare"},
    "priority": {"high", "medium", "low"},
    "decay": set(DECAY_DAYS),
    "timeframe": {"monthly", "quarterly", "long-term"},
}

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


def _read(path: Path) -> str | None:
    """Return a page's text, or None when it is not text at all.

    A check that dies on one unreadable file reports nothing about the other
    fifty, which is the opposite of what a health check is for.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


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
    """Every memory page, skipping the entry points and editor debris.

    Names beginning with a dot or `._` are not pages. The second form is an
    AppleDouble sidecar, which a macOS archive carries along and which is
    binary despite ending in `.md` — reading it as text is how this was found.
    """
    return sorted(p for p in root.rglob("*.md")
                  if p.name not in {"schema.md", "log.md", "index.md"}
                  and not p.name.startswith("."))


def check_index(root: Path) -> list[Finding]:
    """Every page is indexed and every index entry resolves."""
    index = root / "index.md"
    findings: list[Finding] = []
    if not index.exists():
        return [Finding("index-missing", "index.md", "the entry point does not exist")]

    index_text = _read(index)
    if index_text is None:
        return [Finding("unreadable", "index.md", "not valid UTF-8 text")]
    listed = {(index.parent / t).resolve() for t in LINK.findall(index_text)}
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
        text = _read(page)
        if text is None:
            findings.append(Finding("unreadable", str(page.relative_to(root)),
                                    "not valid UTF-8 text"))
            continue
        for target in LINK.findall(text):
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
        text = _read(page)
        if text is None:
            continue
        fm = _frontmatter(text)
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


def _page_type(page: Path, root: Path) -> str | None:
    """A page's type is the directory it sits under, relative to the root."""
    rel = page.relative_to(root).parts
    return rel[0] if len(rel) > 1 else None


def check_frontmatter(root: Path) -> list[Finding]:
    """Required keys are present, and constrained values are in range.

    The repair skill calls this a mechanical finding, so it has to actually be
    one. A person page missing `name` used to pass every check.
    """
    findings: list[Finding] = []

    index = root / "index.md"
    if index.exists():
        text = _read(index)
        fm = _frontmatter(text) if text else {}
        for key in INDEX_REQUIRED:
            if not fm.get(key):
                findings.append(Finding("missing-field", "index.md",
                                        f"frontmatter has no {key}"))

    for page in _pages(root):
        kind = _page_type(page, root)
        required = REQUIRED_FIELDS.get(kind)
        if not required:
            continue
        text = _read(page)
        if text is None:
            continue
        rel = str(page.relative_to(root))
        fm = _frontmatter(text)
        if not fm:
            findings.append(Finding("missing-frontmatter", rel,
                                    "page has no frontmatter block"))
            continue
        for key in required:
            if not fm.get(key):
                findings.append(Finding("missing-field", rel,
                                        f"{kind} page has no {key}"))
        for key, allowed in ENUMS.items():
            value = fm.get(key)
            # Strip trailing comments, which the schema's examples carry.
            if value:
                value = value.split("#")[0].strip()
            if value and value not in allowed:
                findings.append(Finding("bad-value", rel,
                                        f"{key}={value!r} is not one of "
                                        f"{sorted(allowed)}"))
    return findings


def check_provenance(root: Path) -> list[Finding]:
    """Claims on patterns pages carry a footnote or an inferred marker."""
    findings: list[Finding] = []
    for page in _pages(root):
        if page.parent.name != "patterns":
            continue
        text = _read(page)
        if text is None:
            continue
        body = FRONTMATTER.sub("", text)
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
        text = _read(page)
        if text is None:
            continue
        lines = text.splitlines()
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


# A source name is what appears before the first colon of an identity, so it
# may not contain one. Keys may: a Teams id looks like `29:1a2b`.
IDENTITY_SOURCE = re.compile(r"^[a-z0-9_]+$")


def _identities_of(text: str) -> list[str]:
    """Every identity a page claims, from either spelling of the field."""
    listed = re.search(r"^identities:\s*\n((?:\s*-\s*\S+\s*\n)+)",
                       text, re.M)
    if listed:
        return [line.strip().lstrip("-").strip()
                for line in listed.group(1).splitlines() if line.strip()]
    single = re.search(r"^source_key:\s*(\S+)", text, re.M)
    return [single.group(1)] if single else []


def check_identity(root: Path) -> list[Finding]:
    """People pages carry at least one identity, and no two claim the same one.

    `identities` is what the memory job matches a person on. A page without
    any is found only by its filename, so it is renamed the day a namesake
    appears — and a renamed page is a page whose history was lost. Two pages
    claiming one identity are worse: the job finds whichever it looks at
    first and writes both people into it.

    Neither is repaired by guessing. A missing list is reported so the page
    can be given the values the selector hands over; there is nothing on the
    page itself that could supply them, and deriving one from the name is the
    exact mistake the field exists to prevent.

    A malformed entry is its own finding. `dana@example.com` without a source
    matches nothing — the selector looks for `email:dana@example.com` — and a
    page that matches nothing is silently orphaned rather than loudly broken.
    """
    findings: list[Finding] = []
    seen: dict[str, str] = {}
    for page in sorted(_pages(root)):
        if page.parent.name != "people":
            continue
        text = _read(page)
        if text is None:
            continue
        rel = str(page.relative_to(root))
        claimed = _identities_of(text)
        if not claimed:
            findings.append(Finding(
                "missing-identity", rel,
                "no identities; a page written now must carry the values the "
                "selector reports, and one written before the field existed "
                "needs them supplied rather than derived from the name"))
            continue
        for text_form in claimed:
            source, _, key = text_form.partition(":")
            if not key or not IDENTITY_SOURCE.match(source):
                findings.append(Finding(
                    "malformed-identity", rel,
                    f"{text_form} is not `<source>:<key>`; it will match no "
                    "message, so the page is orphaned rather than broken"))
                continue
            if text_form in seen:
                findings.append(Finding(
                    "duplicate-identity", rel,
                    f"identity {text_form} is also on {seen[text_form]}; one "
                    "of them is about somebody else"))
                continue
            seen[text_form] = rel
    return findings


def check_all(root: Path, today: date | None = None) -> list[Finding]:
    """Cheap and mechanical first, so a clean run finishes quickly."""
    return (check_index(root) + check_frontmatter(root) + check_links(root)
            + check_identity(root) + check_decay(root, today)
            + check_provenance(root) + check_ceilings(root))


def main() -> int:
    """Report findings as JSON so the repair skill has something to act on."""
    import argparse
    import json
    import os

    ap = argparse.ArgumentParser(description="Check the memory against its schema.")
    ap.add_argument("--memory", type=Path,
                    default=Path(os.environ.get("HERMES_HOME", ".")) / "workspace" / "memory")
    args = ap.parse_args()

    if not args.memory.is_dir():
        print(json.dumps({"error": f"no memory at {args.memory}"}))
        return 2

    findings = check_all(args.memory)
    print(json.dumps({
        "memory": str(args.memory),
        "findings": [{"kind": f.kind, "path": f.path, "detail": f.detail} for f in findings],
        "clean": not findings,
    }, indent=2))
    # A clean memory is not an error; the caller reads `clean`.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
