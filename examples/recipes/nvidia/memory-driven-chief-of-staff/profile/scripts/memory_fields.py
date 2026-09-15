# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Conservative byte spans for owned fields. Unselected bytes are never rendered."""

from __future__ import annotations

from dataclasses import dataclass
import re

from memory_io import MemoryConflict

ENTRY = re.compile(rb"^<!-- (/?mdcos:entry):([A-Za-z0-9_-]{1,80}) -->\r?\n?$")
FIELD = re.compile(r"(?:frontmatter:[A-Za-z_][A-Za-z0-9_-]*|section:[^\r\n]+|entry:[A-Za-z0-9_-]{1,80})\Z")


@dataclass(frozen=True)
class Span:
    start: int
    end: int


class Document:
    def __init__(self, data: bytes):
        data.decode("utf-8")
        self.data = data
        self.spans = {}
        self.frontmatter_end = None
        self.newline = b"\r\n" if b"\r\n" in data else b"\n"
        lines = data.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        start = 0
        if lines and lines[0].strip() == b"---":
            end = next((i for i in range(1, len(lines)) if lines[i].strip() == b"---"), None)
            if end is None:
                raise MemoryConflict("unterminated frontmatter")
            self.frontmatter_end = offsets[end]
            keys = []
            for i in range(1, end):
                line = lines[i]
                if not line.strip() or line.lstrip().startswith(b"#"):
                    continue
                match = re.match(rb"^([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]|\r?$)", line)
                if match:
                    value = line[match.end():].strip()
                    if value.startswith((b"{", b"[", b"&", b"*", b"!")):
                        raise MemoryConflict("ambiguous YAML value; use the flat page schema")
                    keys.append((match[1].decode(), i))
                elif not (line.startswith((b" ", b"\t")) and keys):
                    raise MemoryConflict("unsupported frontmatter boundary")
                elif re.match(rb"\s+[^#\s][^:]*:", line):
                    raise MemoryConflict("nested YAML mappings are not managed fields")
            for n, (key, i) in enumerate(keys):
                stop = keys[n + 1][1] if n + 1 < len(keys) else end
                # Keep inter-field comments and whitespace outside ownership.
                while stop > i + 1 and (not lines[stop - 1].strip() or lines[stop - 1].lstrip().startswith(b"#")):
                    stop -= 1
                self._add("frontmatter:" + key, offsets[i], offsets[stop])
            start = end + 1
        headings = []
        names = set()
        fence = None
        entry = None
        for i in range(start, len(lines)):
            line = lines[i]
            fm = re.match(rb"^ {0,3}(`{3,}|~{3,})", line)
            if fm:
                if fence is None:
                    fence = fm[1]
                elif fm[1][:1] == fence[:1] and len(fm[1]) >= len(fence):
                    fence = None
                continue
            if fence:
                continue
            marker = ENTRY.fullmatch(line)
            if marker:
                name = marker[2].decode()
                if marker[1] == b"mdcos:entry":
                    if entry is not None:
                        raise MemoryConflict("nested additive entry")
                    entry = (name, offsets[i])
                else:
                    if entry is None or entry[0] != name:
                        raise MemoryConflict("unmatched additive entry")
                    self._add("entry:" + name, entry[1], offsets[i + 1])
                    entry = None
                continue
            if b"mdcos:entry:" in line:
                raise MemoryConflict("malformed additive entry marker")
            heading = re.match(rb"^(#{1,6}) ([^\r\n]+)\r?\n?$", line)
            if heading:
                if entry:
                    raise MemoryConflict("heading crosses additive entry")
                name = heading[2].decode()
                if name in names or name.endswith("#"):
                    raise MemoryConflict("duplicate or ambiguous heading")
                names.add(name)
                headings.append((len(heading[1]), name, offsets[i]))
            elif re.match(rb"^(?:===+|---+)\s*$", line):
                raise MemoryConflict("setext headings and thematic breaks are ambiguous")
        if entry or fence:
            raise MemoryConflict("unclosed entry or code fence")
        for n, (level, name, offset) in enumerate(headings):
            stop = next((p for lev, _, p in headings[n + 1:] if lev <= level), len(data))
            self._add("section:" + name, offset, stop)

    def _add(self, name, start, end):
        if name in self.spans:
            raise MemoryConflict("duplicate field boundary")
        self.spans[name] = Span(start, end)

    def field(self, name: str) -> bytes | None:
        if not isinstance(name, str) or not FIELD.fullmatch(name):
            raise MemoryConflict("invalid field identifier")
        span = self.spans.get(name)
        return None if span is None else self.data[span.start:span.end]

    def render_fields(self, updates: dict[str, bytes]) -> bytes:
        edits = []
        for name, content in updates.items():
            self.field(name)
            span = self.spans.get(name)
            if span:
                edits.append((span.start, span.end, content))
            elif name.startswith("frontmatter:"):
                if self.frontmatter_end is None:
                    raise MemoryConflict("adding frontmatter requires a declared frontmatter block")
                edits.append((self.frontmatter_end, self.frontmatter_end, content))
            else:
                if self.data and not self.data.endswith(b"\n"):
                    raise MemoryConflict("cannot add a field after an unterminated line")
                edits.append((len(self.data), len(self.data), content))
        edits.sort(key=lambda e: (e[0], e[1]))
        for a, b in zip(edits, edits[1:]):
            if a[1] > b[0]:
                raise MemoryConflict("overlapping managed fields")
        result = self.data
        for start, end, content in reversed(edits):
            result = result[:start] + content + result[end:]
        parsed = Document(result)
        for name, content in updates.items():
            if parsed.field(name) != content:
                raise MemoryConflict("replacement changes a field boundary")
        # A replacement must not smuggle extra fields outside its own span.
        for name in parsed.spans.keys() - self.spans.keys() - updates.keys():
            span = parsed.spans[name]
            if not any(parsed.spans[key].start <= span.start and span.end <= parsed.spans[key].end
                       for key in updates):
                raise MemoryConflict("replacement adds undeclared fields")
        return result


def validate_scope(document: Document, fields: dict) -> None:
    intervals = []
    for name, policy in fields.items():
        if policy not in {"cas_protected", "write_once", "additive"}:
            raise MemoryConflict("unknown ownership policy")
        if name.startswith("entry:") and policy != "additive":
            raise MemoryConflict("entry fields require additive policy")
        if policy == "additive" and not name.startswith("entry:"):
            raise MemoryConflict("additive ownership requires a stable entry ID")
        if document.field(name) is None:
            raise MemoryConflict("declared field is absent")
        span = document.spans[name]
        intervals.append((span.start, span.end))
    intervals.sort()
    if any(a[1] > b[0] for a, b in zip(intervals, intervals[1:])):
        raise MemoryConflict("overlapping ownership scopes")
