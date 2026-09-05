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
# Bare Markdown link destinations cannot contain whitespace, controls, angle
# brackets, or parentheses. Keeping this grammar shared between entry and
# link checks prevents a malformed destination from being normalized by
# `Path.resolve()` onto a real page and falsely treated as navigable.
LINK_TARGET = r"([^\s()<>\x00-\x1f\x7f]+\.md)"
# Labels may be empty and may contain CommonMark backslash escapes. An escaped
# closing bracket is consumed as label content, so it cannot be mistaken for
# the delimiter that starts the destination.
INDEX_LINK_LABEL = r"(?:\\[^\r\n]|[^\[\]\\\r\n])*"
PAGE_LINK_LABEL = r"(?:\\.|[^\[\]\\])*"
# Memory-page prose may wrap a link label over a soft line ending. Index
# entries are one physical line by contract and use the narrower pattern.
LINK = re.compile(
    r"\[" + PAGE_LINK_LABEL + r"\]\(" + LINK_TARGET + r"\)", re.S)
INDEX_LINK = re.compile(
    r"\[" + INDEX_LINK_LABEL + r"\]\(" + LINK_TARGET + r"\)")
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

# Page types the schema writes as a folder rather than a file, spelled
# `<type>/<slug>/` in its own headings. Only these have sidecars, and only
# here does a file that is not the page get skipped — an earlier form of this
# skipped every nested file whose name did not match its folder, which made a
# page nested anywhere else invisible to every check rather than merely
# unindexed.
FOLDER_SHAPED = frozenset({"projects"})

# What the schema says a folder-shaped page's directory contains besides the
# page itself. Named, because the schema names them:
#
#     projects/<slug>/
#     ├── <slug>.md        # the current picture
#     ├── log.md           # append-only history
#     └── log.archive.md   # created when log.md rotates
#
# Reading "anything not named after the folder" as a sidecar instead is what
# an earlier form of this did, and it deleted a real page from every check:
# a project page written as `overview.md` reported nothing at all — no
# missing field, no bad value, no broken link — where before it reported
# four. A file here that is neither the page nor one of these is treated as
# a page, so it is reported rather than swallowed.
#
# Exemption is by *position*, not by name alone: a file only counts as one of
# these if it sits at the exact depth the schema puts it at,
# `projects/<slug>/log.md`. A name match anywhere else — `patterns/log.md`,
# `projects/<slug>/nested/log.archive.md` — is a page under a reserved name,
# not the sidecar the schema means, and is checked like any other page.
DECLARED_SIDECARS = frozenset({"log.md", "log.archive.md"})

# What the schema writes at the memory root besides the pages themselves: the
# entry point, the append-only job log, and the schema document, were it ever
# placed inside the live memory. Exempt only as the root's own direct child —
# `log.md` two directories down is not this file, it is a reserved name
# collision.
ROOT_SPECIALS = frozenset({"schema.md", "index.md", "log.md"})

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

    A folder-shaped page type holds one page and any number of sidecars, and
    the page is the file named after its folder. `projects/<slug>/` carries
    `<slug>.md` plus `log.md` and, once it rotates, `log.archive.md`. The
    archive was treated as a page and so was reported `unindexed` and
    `missing-frontmatter` for as long as it existed — a permanent pair of
    findings produced by following the schema, on a file that is an
    append-only history and is not supposed to carry frontmatter at all.
    Naming the archive here would have fixed that one file and left the next
    sidecar to rediscover it, so the rule is structural instead.
    """
    def is_page(path: Path) -> bool:
        if path.name.startswith("."):
            return False
        parts = path.relative_to(root).parts
        if len(parts) == 1:
            return parts[0] not in ROOT_SPECIALS
        # Inside a folder-shaped type, at exactly the depth the schema puts a
        # sidecar: the page, plus the sidecars the schema declares. Anything
        # else — including a reserved name at any other depth — is checked,
        # because it is far more likely to be a page under the wrong name or
        # in the wrong place than a sidecar nobody documented.
        if (len(parts) == 3 and parts[0] in FOLDER_SHAPED
                and path.name in DECLARED_SIDECARS):
            return False
        return True

    return sorted(p for p in root.rglob("*.md") if is_page(p))


# Sections, in schema order. `REQUIRED_FIELDS`'s own key order already
# matches `schema.md`'s "Sections, in this order" list (a test compares
# them), so a page type's rank is looked up here rather than kept in a
# second constant that could drift from the first.
_INDEX_RANK = {kind.capitalize(): i for i, kind in enumerate(REQUIRED_FIELDS)}

# `index.md` is data, not an arbitrary Markdown article. Parse the two
# top-level constructs its contract names rather than searching all source
# text for link-shaped strings. The accepted entry forms deliberately remain
# broad: the schema requires a relative link first, but does not require a
# particular list marker or description separator.
HEADING_LINE = re.compile(r"^ {0,3}##[ \t]+(\w+)[ \t]*$")
BARE_ENTRY_LINE = re.compile(
    r"^ {0,3}\[" + INDEX_LINK_LABEL + r"\]\(" + LINK_TARGET + r"\).*$")
MARKED_ENTRY_LINE = re.compile(
    r"^( {0,3})([-+*]|[0-9]{1,9}[.)])([ \t]+)"
    r"\[" + INDEX_LINK_LABEL + r"\]\(" + LINK_TARGET + r"\).*$")
LIST_ITEM = re.compile(
    r"^( {0,3})([-+*]|[0-9]{1,9}[.)])([ \t]+|$)")
BLOCK_QUOTE = re.compile(r"^ {0,3}>")
FENCE_LINE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)$")
COMMENT_BLOCK = re.compile(r"^ {0,3}<!--")
# A small contract checker must not guess where an arbitrary raw HTML block
# ends. Any top-level line beginning with an HTML-like opener is therefore
# ambiguous unless it is a positively recognized URI/email autolink. Literal
# comparisons such as ``latency < 5`` are ordinary text. HTML comments are
# handled separately before this guard.
HTML_LIKE_LINE = re.compile(r"^ {0,3}(?:</?[A-Za-z]|<\?|<!)")
HTML_LIKE_TOKEN = re.compile(r"(?:</?[A-Za-z]|<\?|<!)")
AUTOLINK_LINE = re.compile(
    r"^ {0,3}<(?:(?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^ <>]*)|"
    r"(?:[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?))>")
AUTOLINK_TOKEN = re.compile(AUTOLINK_LINE.pattern.removeprefix(r"^ {0,3}"))


@dataclass(frozen=True)
class _ParsedIndex:
    headings: tuple[str, ...]
    entries: tuple[tuple[str, str | None], ...]
    links: tuple[str, ...]
    error: str | None = None


def _indent_width(line: str, initial: int = 0) -> int:
    """Leading indentation in Markdown columns (tabs stop every four)."""
    width = initial
    for ch in line:
        if ch == " ":
            width += 1
        elif ch == "\t":
            width += 4 - (width % 4)
        else:
            break
    return width


def _list_content_indent(match: re.Match) -> int:
    """The continuation indentation established by a list marker."""
    marker_end = match.end(2)
    width_after_padding = _indent_width(match.group(3), marker_end)
    padding = width_after_padding - marker_end
    return marker_end + (padding if 1 <= padding <= 4 else 1)


def _list_marker_kind(match: re.Match) -> str:
    marker = match.group(2)
    return marker if marker in "-+*" else marker[-1]


def _list_marker_interrupts_paragraph(match: re.Match) -> bool:
    """Whether this list marker may interrupt a CommonMark paragraph."""
    marker = match.group(2)
    return not marker[0].isdigit() or int(marker[:-1]) == 1


def _entry_target(line: str) -> str | None:
    """Return a schema entry target without accepting list-item code.

    CommonMark permits one to four columns of padding between a list marker
    and its inline content. Five or more makes the apparent link an indented
    code block, so it cannot be an index entry.
    """
    bare = BARE_ENTRY_LINE.match(line)
    if bare:
        return bare.group(1)
    marked = MARKED_ENTRY_LINE.match(line)
    if not marked:
        return None
    marker_end = marked.end(2)
    padding = _indent_width(marked.group(3), marker_end) - marker_end
    return marked.group(4) if 1 <= padding <= 4 else None


def _raw_html_or_ambiguous(line: str) -> bool:
    return bool(HTML_LIKE_LINE.match(line) and not AUTOLINK_LINE.match(line))


def _definite_block_start(line: str) -> bool:
    """A construct that cannot be a lazy paragraph continuation."""
    item = LIST_ITEM.match(line)
    return bool(HEADING_LINE.match(line) or FENCE_LINE.match(line)
                or COMMENT_BLOCK.match(line)
                or (item and _list_marker_interrupts_paragraph(item))
                or _raw_html_or_ambiguous(line))


def _inline_content(line: str) -> tuple[str, str | None]:
    """Blank same-line code spans and comments before reading links.

    A comment that begins in ordinary inline content and does not close on
    that line is valid enough Markdown to be ambiguous to this deliberately
    small parser. Report that ambiguity instead of allowing a later line to
    be mistaken for top-level index data. Backslash-escaped markers and
    markers inside a closed code span remain literal.
    """
    visible = list(line)
    i = 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line):
            visible[i] = " "
            visible[i + 1] = " "
            i += 2
            continue
        if line[i] == "`":
            end = i + 1
            while end < len(line) and line[end] == "`":
                end += 1
            marker = line[i:end]
            close = -1
            candidate = end
            while candidate < len(line):
                candidate = line.find("`", candidate)
                if candidate < 0:
                    break
                run_end = candidate + 1
                while run_end < len(line) and line[run_end] == "`":
                    run_end += 1
                if run_end - candidate == len(marker):
                    close = candidate
                    break
                candidate = run_end
            if close >= 0:
                for pos in range(i, close + len(marker)):
                    visible[pos] = " "
                i = close + len(marker)
                continue
            return line, "a multiline or unmatched code span obscures structure"
        if line.startswith("<!--", i):
            close = line.find("-->", i + 4)
            if close < 0:
                return line, "a multiline inline HTML comment obscures structure"
            close += 3
            for pos in range(i, close):
                visible[pos] = " "
            i = close
            continue
        if line[i] == "<":
            autolink = AUTOLINK_TOKEN.match(line, i)
            if autolink:
                for pos in range(i, autolink.end()):
                    visible[pos] = " "
                i = autolink.end()
                continue
            if HTML_LIKE_TOKEN.match(line, i):
                return line, "inline HTML or an angle marker obscures structure"
        i += 1
    return "".join(visible), None


def _parse_index(text: str) -> _ParsedIndex:
    """Read the top-level headings and entries in an index safely.

    Fences and comments are interpreted only after a line is known to be at
    top level. That matters for an installed, user-owned index: a fence or
    comment marker inside a list example, block quote, inline code span, or
    indented code block must not hide real content that follows its container.
    If a lazy continuation or raw HTML makes top-level ownership ambiguous,
    parsing fails closed so repair cannot add duplicate entries from a partial
    view of the file.
    """
    lines = text.splitlines()
    headings: list[str] = []
    entries: list[tuple[str, str | None]] = []
    links: list[str] = []
    current_heading: str | None = None
    fence_char: str | None = None
    fence_length = 0
    in_comment = False
    in_indented_code = False
    list_indent: int | None = None
    list_marker_indent = 0
    list_marker_kind: str | None = None
    list_saw_blank = False
    quote_may_continue = False
    paragraph_may_continue = False

    # YAML frontmatter is not index content.
    frontmatter_end = 0
    frontmatter = FRONTMATTER.match(text)
    if frontmatter:
        frontmatter_end = text[:frontmatter.end()].count("\n")

    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\r")
        if i < frontmatter_end:
            i += 1
            continue

        if fence_char is not None:
            close = FENCE_LINE.match(line)
            if close:
                marker, trailing = close.groups()
                if (marker[0] == fence_char and len(marker) >= fence_length
                        and not trailing.strip(" \t")):
                    fence_char = None
                    fence_length = 0
            i += 1
            continue

        if in_comment:
            if "-->" in line:
                in_comment = False
            i += 1
            continue

        if in_indented_code:
            if not line.strip() or _indent_width(line) >= 4:
                i += 1
                continue
            in_indented_code = False
            continue

        if list_indent is not None:
            if not line.strip():
                list_saw_blank = True
                i += 1
                continue
            indent = _indent_width(line)
            sibling = LIST_ITEM.match(line)
            if list_saw_blank:
                if indent >= list_indent:
                    if INDEX_LINK.search(line):
                        return _ParsedIndex(
                            tuple(headings), tuple(entries), tuple(links),
                            "a visible link is nested in a list container")
                    i += 1
                    continue
                list_indent = None
                continue
            if sibling and _indent_width(sibling.group(1)) <= list_marker_indent:
                if (_list_marker_kind(sibling) == list_marker_kind
                        or _list_marker_interrupts_paragraph(sibling)):
                    list_indent = None
                    continue
                if INDEX_LINK.search(line):
                    return _ParsedIndex(
                        tuple(headings), tuple(entries), tuple(links),
                        "a link-shaped line may be a lazy list continuation")
                i += 1
                continue
            if indent >= list_indent:
                if INDEX_LINK.search(line):
                    return _ParsedIndex(
                        tuple(headings), tuple(entries), tuple(links),
                        "a visible link is nested in a list container")
                i += 1
                continue
            if _definite_block_start(line) or list_saw_blank:
                list_indent = None
                continue
            if INDEX_LINK.search(line):
                return _ParsedIndex(
                    tuple(headings), tuple(entries), tuple(links),
                    "a visible link may be a lazy list continuation")
            # Ordinary lazy paragraph continuation remains inside the item.
            i += 1
            continue

        if BLOCK_QUOTE.match(line):
            if INDEX_LINK.search(line):
                return _ParsedIndex(
                    tuple(headings), tuple(entries), tuple(links),
                    "a visible link is nested in a block quote")
            quote_may_continue = True
            i += 1
            continue
        if quote_may_continue:
            if not line.strip():
                quote_may_continue = False
                i += 1
                continue
            if _definite_block_start(line):
                quote_may_continue = False
                continue
            if INDEX_LINK.search(line):
                return _ParsedIndex(
                    tuple(headings), tuple(entries), tuple(links),
                    "a visible link may be a lazy block quote continuation")
            i += 1
            continue

        if paragraph_may_continue:
            if not line.strip():
                paragraph_may_continue = False
                i += 1
                continue
            item = LIST_ITEM.match(line)
            if item and not _list_marker_interrupts_paragraph(item):
                visible_line, inline_error = _inline_content(line)
                if inline_error:
                    return _ParsedIndex(
                        tuple(headings), tuple(entries), tuple(links),
                        inline_error)
                if INDEX_LINK.search(visible_line):
                    return _ParsedIndex(
                        tuple(headings), tuple(entries), tuple(links),
                        "a link-shaped line may continue a paragraph")
                i += 1
                continue
            if _raw_html_or_ambiguous(line):
                return _ParsedIndex(
                    tuple(headings), tuple(entries), tuple(links),
                    "raw HTML may continue a paragraph")
            if (HEADING_LINE.match(line) or FENCE_LINE.match(line)
                    or COMMENT_BLOCK.match(line) or BLOCK_QUOTE.match(line)
                    or (item and _list_marker_interrupts_paragraph(item))):
                paragraph_may_continue = False
                continue
            # A bare link first on its physical line remains an accepted
            # schema entry. Other ordinary source continues the paragraph.
            if not _entry_target(line):
                visible_line, inline_error = _inline_content(line)
                if inline_error:
                    return _ParsedIndex(
                        tuple(headings), tuple(entries), tuple(links),
                        inline_error)
                links.extend(INDEX_LINK.findall(visible_line))
                i += 1
                continue
            paragraph_may_continue = False

        if _indent_width(line) >= 4:
            in_indented_code = True
            i += 1
            continue

        fence = FENCE_LINE.match(line)
        if fence:
            marker, info = fence.groups()
            if marker[0] == "~" or "`" not in info:
                fence_char = marker[0]
                fence_length = len(marker)
                i += 1
                continue

        if COMMENT_BLOCK.match(line):
            in_comment = "-->" not in line
            i += 1
            continue

        if _raw_html_or_ambiguous(line):
            return _ParsedIndex(tuple(headings), tuple(entries), tuple(links),
                                "raw HTML can hide index structure")

        visible_line, inline_error = _inline_content(line)
        if inline_error:
            return _ParsedIndex(tuple(headings), tuple(entries), tuple(links),
                                inline_error)

        # Structural tokens must begin at their original source position.
        # Masking an earlier code span or comment must not turn the spaces it
        # leaves behind into the permitted indentation before a heading/link.
        heading = HEADING_LINE.match(line)
        if heading:
            current_heading = heading.group(1)
            headings.append(current_heading)
            i += 1
            continue

        target = _entry_target(line)
        if target:
            entries.append((target, current_heading))
            links.extend(INDEX_LINK.findall(visible_line))
            item = LIST_ITEM.match(line)
            if item:
                list_marker_indent = _indent_width(item.group(1))
                list_marker_kind = _list_marker_kind(item)
                list_indent = _list_content_indent(item)
                list_saw_blank = False
            i += 1
            continue

        item = LIST_ITEM.match(line)
        if item:
            # A non-entry list item is a container. Its indented children may
            # contain examples, but they cannot declare top-level index data.
            if INDEX_LINK.search(visible_line):
                return _ParsedIndex(
                    tuple(headings), tuple(entries), tuple(links),
                    "a list item contains a link that is not an index entry")
            list_marker_indent = _indent_width(item.group(1))
            list_marker_kind = _list_marker_kind(item)
            list_indent = _list_content_indent(item)
            list_saw_blank = False
            i += 1
            continue

        links.extend(INDEX_LINK.findall(visible_line))
        if line.strip():
            paragraph_may_continue = True
        i += 1

    return _ParsedIndex(tuple(headings), tuple(entries), tuple(links))


def check_index(root: Path) -> list[Finding]:
    """Every page is indexed, every entry resolves, and each is filed under
    its own type's section, which appears where `schema.md` orders it."""
    index = root / "index.md"
    findings: list[Finding] = []
    if not index.exists():
        return [Finding("index-missing", "index.md", "the entry point does not exist")]

    index_text = _read(index)
    if index_text is None:
        return [Finding("unreadable", "index.md", "not valid UTF-8 text")]

    parsed = _parse_index(index_text)
    if parsed.error:
        return [Finding(
            "index-unparseable", "index.md",
            "cannot verify top-level structure safely: " + parsed.error
            + "; preserve the file and make no automatic index repair")]
    present = set(parsed.headings)

    # Every linked target, and which section's span each of its occurrences
    # falls inside — a link can be present in the document and still not be
    # filed where it belongs. Every occurrence is kept, not just the first:
    # a target linked once correctly and once from the wrong section is
    # still a misfiled entry, and checking only the first occurrence missed
    # exactly that duplicate.
    listed: set[Path] = set()
    filed_under: dict[Path, list[str | None]] = {}
    for relative, heading in parsed.entries:
        target = (index.parent / relative).resolve()
        listed.add(target)
        filed_under.setdefault(target, []).append(heading)

    for page in _pages(root):
        rel = str(page.relative_to(root))
        target = page.resolve()
        if target not in listed:
            findings.append(Finding("unindexed", rel,
                                    "page has no entry in index.md"))
            continue
        kind = _page_type(page, root)
        expected = kind.capitalize() if kind else None
        occurrences = filed_under.get(target, [])
        if expected in _INDEX_RANK and any(h != expected for h in occurrences):
            actual = next(h for h in occurrences if h != expected) or "no section"
            findings.append(Finding(
                "index-misfiled", rel,
                f"linked under `## {actual}` instead of its own"
                f" `## {expected}` section"))

    for target in sorted(listed):
        if not target.exists():
            findings.append(Finding("index-dangling", "index.md",
                                    f"entry points at missing {target.name}"))

    # A section per validated page type, so there is somewhere to file the
    # first page of each.
    #
    # This is the half of a schema change that a seed cannot deliver.
    # `bootstrap` copies in what is missing and never overwrites — correctly,
    # because the index is the user's — so a memory installed before a page
    # type was added keeps the sections it was created with, and the people
    # most likely to have content are exactly the people who never receive
    # the new one. The seed is right for a fresh install and this is what
    # reaches the rest.
    for kind in sorted({_page_type(p, root) for p in _pages(root)} - {None}):
        heading = kind.capitalize()
        if heading not in present:
            findings.append(Finding(
                "index-section-missing", "index.md",
                f"pages of type {kind}/ exist and there is no `## {heading}`"
                " section to file them under, so their entries have nowhere"
                " to go"))

    # Order, independent of whether every section is present. A heading that
    # exists is still wrong if the schema puts it earlier than one that
    # already precedes it in the file — a set of heading names cannot see
    # this, only their positions relative to each other can.
    furthest_rank, furthest_heading = -1, None
    for heading in parsed.headings:
        rank = _INDEX_RANK.get(heading)
        if rank is None:
            continue
        if rank < furthest_rank:
            findings.append(Finding(
                "index-out-of-order", "index.md",
                f"`## {heading}` comes after `## {furthest_heading}`, but"
                f" schema.md orders it before `## {furthest_heading}`"))
        else:
            furthest_rank, furthest_heading = rank, heading

    return findings


def check_links(root: Path) -> list[Finding]:
    """Relative links between pages resolve."""
    findings: list[Finding] = []
    for page in _pages(root):
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

    # Index links use the same parse as index structure. Scanning its raw
    # source here would reintroduce false findings for fenced and commented
    # examples that `check_index` correctly excludes. If parsing failed,
    # `check_index` already reports the authoritative fail-closed finding.
    index = root / "index.md"
    if index.exists():
        text = _read(index)
        if text is not None:
            parsed = _parse_index(text)
            if not parsed.error:
                for target in parsed.links:
                    if not (index.parent / target).resolve().exists():
                        findings.append(Finding(
                            "broken-link", "index.md",
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
                    f"identity {text_form} is also on {seen[text_form]}. "
                    "Either one of them is about somebody else, or a merge "
                    "copied the content across and left the emptied page "
                    "behind. Only the memory job knows which: it reports the "
                    "pages a confirmed link has joined. Do not merge and do "
                    "not pick on what is visible here."))
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
