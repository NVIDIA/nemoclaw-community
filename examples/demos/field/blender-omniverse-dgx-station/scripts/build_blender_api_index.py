#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Build a compact full-text index for extracted Blender API HTML."""

import html
import re
import sqlite3
import sys
from pathlib import Path


if len(sys.argv) != 2:
    raise SystemExit("usage: build_blender_api_index.py DOCUMENTATION_ROOT")

root = Path(sys.argv[1]).resolve()
database = root / "api-search.sqlite3"
temporary = database.with_suffix(".sqlite3.building")


def article_text(markup: str) -> str:
    match = re.search(
        r'<article\b[^>]*id="furo-main-content"[^>]*>(.*?)</article>',
        markup,
        flags=re.I | re.S,
    )
    content = match.group(1) if match else markup
    content = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", content, flags=re.I | re.S)
    content = re.sub(r"<[^>]+>", " ", content)
    return re.sub(r"\s+", " ", html.unescape(content)).strip()


temporary.unlink(missing_ok=True)
connection = sqlite3.connect(temporary)
try:
    connection.execute("CREATE VIRTUAL TABLE pages USING fts5(path UNINDEXED, content)")
    rows = []
    for path in root.rglob("*.html"):
        raw = path.read_text(encoding="utf-8", errors="ignore")
        rows.append((str(path.relative_to(root)), article_text(raw)))
        if len(rows) >= 200:
            connection.executemany("INSERT INTO pages(path, content) VALUES (?, ?)", rows)
            rows.clear()
    if rows:
        connection.executemany("INSERT INTO pages(path, content) VALUES (?, ?)", rows)
    connection.commit()
finally:
    connection.close()

temporary.replace(database)
print(f"indexed Blender API documentation at {database}")
