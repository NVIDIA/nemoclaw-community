#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Search an extracted Blender Python API reference and print text excerpts."""

import argparse
import sqlite3
from pathlib import Path


DEFAULT_ROOT = Path("/sandbox/reference/blender-python-api-5.1")

parser = argparse.ArgumentParser()
parser.add_argument("query", nargs="+", help="terms that must all occur in a page")
parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
parser.add_argument("--limit", type=int, default=8)
parser.add_argument("--context", type=int, default=260)
args = parser.parse_args()

terms = [term.lower() for term in args.query]
database = args.root / "api-search.sqlite3"
if not database.is_file():
    raise SystemExit(f"Blender API search index is missing: {database}")

query = " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
try:
    rows = connection.execute(
        "SELECT path, content FROM pages WHERE pages MATCH ? ORDER BY bm25(pages) LIMIT ?",
        (query, args.limit),
    ).fetchall()
finally:
    connection.close()

matches = []
for relative_path, content in rows:
    content_lower = content.lower()
    positions = [content_lower.find(term) for term in terms]
    position = min((value for value in positions if value >= 0), default=0)
    start = max(0, position - args.context)
    end = min(len(content), position + args.context)
    matches.append((Path(relative_path), content[start:end]))

if not matches:
    raise SystemExit(f"no Blender API pages matched: {' '.join(args.query)}")

for path, excerpt in matches:
    print(f"=== {path} ===")
    print(excerpt)
