# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Fail the image build if the pinned Hermes base lacks native table blocks."""

from __future__ import annotations

import sys


sys.path.insert(0, "/opt/hermes")

from plugins.platforms.slack.block_kit import render_blocks  # noqa: E402
from plugins.platforms.slack.adapter import SlackAdapter  # noqa: E402


MARKDOWN = """# Product prioritization

| Segment | Core Problem | Evidence Needed |
|---|---|---|
| New users | Slow time to value | Onboarding drop-off |
"""

blocks = render_blocks(MARKDOWN)
tables = [block for block in blocks if block.get("type") == "table"]
if len(tables) != 1:
    raise SystemExit(f"expected exactly one native table block, got {blocks!r}")

rows = tables[0].get("rows")
if not isinstance(rows, list) or len(rows) != 2:
    raise SystemExit(f"expected a header and one data row, got {rows!r}")
if any(not isinstance(row, list) or len(row) != 3 for row in rows):
    raise SystemExit(f"expected three columns in every table row, got {rows!r}")

# The pinned Hermes base inherits Slack clarification from the text-only base
# adapter. sitecustomize installs a direct Slack override. A future Hermes base
# may provide the direct override itself, in which case the compatibility shim
# stands down and this contract still passes.
if "send_clarify" not in SlackAdapter.__dict__:
    raise SystemExit("expected a direct Slack send_clarify implementation")

send_clarify = SlackAdapter.__dict__["send_clarify"]
if send_clarify.__module__ == "sitecustomize" and not hasattr(
    SlackAdapter, "_nemoclaw_handle_clarify_action"
):
    raise SystemExit("compatibility send_clarify is missing its action handler")
