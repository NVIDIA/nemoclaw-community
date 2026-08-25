# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Content hashes for the things a score depends on.

A score is only comparable to another score if both were produced against the
same documents, the same questions and the same grading rules. Those three are
files, and files drift: a typo gets fixed, a rule gets relaxed, a document gets
regenerated. Recording a hash of each in the report turns "are these two rows
comparable?" from a judgement call into a comparison.

``hash_tree`` covers the bytes of every file under a directory and the path it
sits at, in sorted order, so a renamed document changes the hash even if its
contents did not. ``hash_file`` covers a single artifact's bytes alone, with no
path framing — three of the published rows are single files.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# Bump when the hashing rule itself changes, so an old hash is never silently
# compared against one computed a different way.
ALGORITHM = "sha256-v1"


def _walk(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def hash_tree(root: Path) -> str:
    """Hash every file under ``root``, path included, in a stable order."""
    digest = hashlib.sha256()
    for path in _walk(root):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(corpus: Path, questions: Path, gold: Path) -> dict:
    """The identity of one scoring configuration."""
    from bench.normalize import ALT_YEARS, DEFAULT_YEAR  # noqa: PLC0415

    return {
        "algorithm": ALGORITHM,
        # Date normalization changes verdicts, so it belongs in the identity of
        # a scoring configuration alongside the files themselves.
        "normalization": {"default_year": DEFAULT_YEAR, "alt_years": sorted(ALT_YEARS)},
        "corpus": hash_tree(corpus),
        "corpus_documents": len(_walk(corpus)),
        "questions": hash_file(questions),
        "gold": hash_file(gold),
    }
