# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Dependency-free helpers shared by the OpenShell Harbor adapter and tests."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def sandbox_name(session_id: str | None, arm: str) -> str:
    raw = session_id or "trial"
    slug = re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-")[:4]
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    # The local Docker gateway currently caps names at 19 characters even
    # though the portable DNS label limit is larger.
    return f"hf-{arm[0]}-{slug or 'run'}-{digest}"[:19].rstrip("-")


def final_answer(session_text: str) -> str:
    messages: list[dict[str, Any]] = []
    for line in session_text.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and isinstance(item.get("messages"), list):
            messages.extend(item["messages"])
        elif isinstance(item, dict):
            messages.append(item)

    for message in reversed(messages):
        if message.get("role") != "assistant" or message.get("tool_calls"):
            continue
        content = message.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if content:
            return str(content)
    return ""
