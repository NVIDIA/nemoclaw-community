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


def pinned_config(config: Path) -> str:
    """Return *config* with the mutable blocks removed, for comparison."""
    kept, dropping = [], False
    for line in config.read_text(encoding="utf-8").splitlines():
        if line[:1] not in (" ", "\t", ""):  # a new top-level key
            dropping = line.startswith(MUTABLE_CONFIG_KEYS)
        if not dropping:
            kept.append(line)
    return "\n".join(kept).strip()


def violations(candidate: Path) -> list[str]:
    """Return what *candidate* changed that it cannot promote."""
    found = []
    wrapper = candidate / "harbor_wrapper.py"
    if wrapper.is_file():
        if wrapper.read_bytes() != (PRISTINE / "harbor_wrapper.py").read_bytes():
            found.append("harbor_wrapper.py differs from the original")
    else:
        found.append("harbor_wrapper.py is missing")
    config = candidate / "agent.yaml"
    if config.is_file():
        if pinned_config(config) != pinned_config(PRISTINE / "agent.yaml"):
            found.append("agent.yaml changed a pinned block")
    else:
        found.append("agent.yaml is missing")
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
