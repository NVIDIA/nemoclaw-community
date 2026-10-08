# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Reject an optimization run whose candidates changed something unpromotable.

The wrapper checks this too, but that check is advisory and cannot be otherwise:
Harbor resolves the entry point *inside* the agent directory, so the file
carrying the check is the same file a candidate may rewrite, and an edit that
removes the check removes its own enforcement.

This script lives outside `agent_source/`, is never copied into a candidate, and
compares every candidate against the pristine originals. Run it before trusting
a run's results:

    python3 scorer/verify_candidates.py harness/experiment

Exit status is 0 when every candidate stayed inside the change surface, and 1
when any did not, naming each offender.
"""

from __future__ import annotations

import sys
from pathlib import Path

EXAMPLE_ROOT = Path(__file__).resolve().parent.parent
PRISTINE = EXAMPLE_ROOT / "harness" / "agent_source"

#: The only `agent.yaml` blocks a candidate may change. Both promote by copying
#: the file: the system prompt lives under `instructions`, subagents under
#: `harnesses`. Skills are files under `workspace/skills/` and are unrestricted.
MUTABLE_CONFIG_KEYS = ("instructions:", "harnesses:")

#: Runtime output the optimizer and the agent write inside the candidate. Not
#: authored content, so not part of the comparison.
IGNORED_DIRS = ("artifacts", "traces", ".fabric")

#: Not runtime output: Python imports cached bytecode in place of source, so a
#: `.pyc` here runs while the `.py` beside it still compares equal. The optimizer
#: strips it when forking a candidate, and the documented run sets
#: PYTHONPYCACHEPREFIX so trials never write one, so a legitimate candidate has
#: none and any found is rejected.
BYTECODE_DIR = "__pycache__"

#: Written into every candidate by the optimizer itself, after the change is
#: final (`coder.py`, `fork.workdir / "architecture.md"`). It documents the
#: agent for the next round's proposer and is never imported or executed, so it
#: is not a candidate edit and rejecting it would fail every trial.
OPTIMIZER_FILES = ("architecture.md",)


def pinned_config(config: Path) -> str:
    """Return *config* with the mutable blocks removed, for comparison."""
    kept, dropping = [], False
    for line in config.read_text(encoding="utf-8").splitlines():
        if line[:1] not in (" ", "\t", ""):  # a new top-level key
            dropping = line.startswith(MUTABLE_CONFIG_KEYS)
        if not dropping:
            kept.append(line)
    return "\n".join(kept).strip()


def _tracked(root: Path) -> dict[str, Path]:
    """Map relative path to entry for everything under *root* worth comparing.

    Walked explicitly rather than with rglob so the symlink test happens
    *before* an ignored directory is pruned. Skipping on name first let a
    candidate replace `artifacts/` or `traces/` with a symlink to anywhere on
    the host and have the whole subtree ignored.
    """
    found: dict[str, Path] = {}

    def walk(directory: Path, base: str) -> None:
        for entry in sorted(directory.iterdir()):
            rel = f"{base}/{entry.name}" if base else entry.name
            if entry.is_symlink() or entry.name == BYTECODE_DIR:
                found[rel] = entry  # recorded so the caller can reject it
            elif entry.is_dir():
                if entry.name not in IGNORED_DIRS:
                    walk(entry, rel)
            elif entry.is_file():
                if rel in OPTIMIZER_FILES or entry.name.startswith(".trial-"):
                    continue
                found[rel] = entry

    walk(root, "")
    return found


def violations(candidate: Path) -> list[str]:
    """Return everything *candidate* changed that it cannot promote.

    The change surface is the whole candidate tree minus two openings: the
    `instructions` and `harnesses` blocks of `agent.yaml`, and anything under
    `workspace/skills/`. Every other file must be byte-identical to the
    original, and files the original does not have are rejected rather than
    ignored: a new module can be imported by an edited wrapper, and a changed
    `pyproject.toml` changes what the trial installs.
    """
    found: list[str] = []
    # The checkout's own bytecode is local residue from running the tests; the
    # optimizer never copies it into a candidate, so it is not an expected file.
    ours = {rel: p for rel, p in _tracked(PRISTINE).items() if p.name != BYTECODE_DIR}
    theirs = _tracked(candidate)

    for rel, path in sorted(theirs.items()):
        if path.is_symlink():
            found.append(f"{rel} is a symlink; candidates may not link outside the tree")
            continue
        if path.name == BYTECODE_DIR:
            found.append(f"{rel} is cached bytecode, which Python imports in place of source")
            continue
        if rel.startswith("workspace/skills/"):
            continue  # skills are the change surface
        if rel == "agent.yaml":
            if rel not in ours:
                found.append("agent.yaml is missing from the original")
            elif pinned_config(path) != pinned_config(ours[rel]):
                found.append("agent.yaml changed a pinned block")
            continue
        if rel not in ours:
            found.append(f"{rel} is not in the original; only workspace/skills/ may gain files")
        elif path.read_bytes() != ours[rel].read_bytes():
            found.append(f"{rel} differs from the original")

    for rel in sorted(ours):
        if rel not in theirs and not rel.startswith("workspace/skills/"):
            found.append(f"{rel} was deleted; the original ships it")
    return found


def main() -> int:
    """Check every candidate under the experiment directory given on argv."""
    experiment = Path(sys.argv[1] if len(sys.argv) > 1 else "harness/experiment")
    candidates = sorted((experiment / "eval-and-optimize" / "agents").glob("agent-*"))
    if not candidates:
        print(f"no candidates under {experiment}", file=sys.stderr)
        return 1
    rejected = False
    for candidate in candidates:
        found = violations(candidate)
        for detail in found:
            print(f"REJECTED {candidate.name}: {detail}", file=sys.stderr)
        rejected = rejected or bool(found)
        if not found:
            print(f"ok {candidate.name}")
    if rejected:
        print(
            "\nA rejected candidate changed something that cannot be deployed, so "
            "its reward does not measure a shippable change. Do not promote it, "
            "and treat the run's ranking as unsound.",
            file=sys.stderr,
        )
    return 1 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
