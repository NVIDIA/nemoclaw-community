#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Emit two base64-JSON lines for the Dockerfile build args:
1. messaging channels list (e.g. ["slack", "outlook"])
2. allowed-IDs map keyed by channel (e.g. {"slack": ["U123"]})

Matches `nemoclaw onboard`'s output shape — see src/lib/onboard.ts:1568-1572.
"""
from __future__ import annotations

import base64
import json
import os


def main() -> None:
    channels: list[str] = []
    if os.environ.get("OUTLOOK_CLIENT_ID"):
        channels.append("outlook")
    if os.environ.get("SLACK_BOT_TOKEN"):
        channels.append("slack")
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        channels.append("telegram")
    if os.environ.get("DISCORD_BOT_TOKEN"):
        channels.append("discord")

    allowed: dict[str, list[str]] = {}
    for ch, env in [("slack", "SLACK_ALLOWED_IDS"), ("telegram", "TELEGRAM_ALLOWED_IDS")]:
        raw = (os.environ.get(env) or "").strip()
        if raw:
            allowed[ch] = [s.strip() for s in raw.split(",") if s.strip()]

    print(base64.b64encode(json.dumps(channels).encode()).decode())
    print(base64.b64encode(json.dumps(allowed).encode()).decode())


if __name__ == "__main__":
    main()
