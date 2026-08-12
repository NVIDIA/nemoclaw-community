#!/usr/bin/python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Shared Slack helper utilities for the NemoClaw demo skills."""

from __future__ import annotations

import os
from pathlib import Path


def _candidate_env_files() -> list[Path]:
    hermes_home = Path(os.environ.get("HERMES_HOME", "/sandbox/.hermes-data"))
    return [
        hermes_home / ".env",
        Path("/sandbox/.hermes-data/.env"),
        Path("/sandbox/.hermes/.env"),
    ]


def _read_env_value(env_file: Path, key: str) -> str:
    if not env_file.is_file():
        return ""
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, value = line.split("=", 1)
        if current_key == key:
            return value.strip()
    return ""


def load_env_defaults() -> None:
    """Load Hermes-style .env files into os.environ if values are missing."""
    for env_file in _candidate_env_files():
        if not env_file.is_file():
            continue
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)


def get_slack_bot_token() -> str:
    """Return the best available Slack bot token placeholder for egress."""
    load_env_defaults()
    runtime_value = _read_env_value(Path("/sandbox/.hermes-data/.env"), "SLACK_BOT_TOKEN")
    if runtime_value.startswith("openshell:resolve:env:"):
        return runtime_value

    env_value = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    if env_value:
        return env_value

    return _read_env_value(Path("/sandbox/.hermes/.env"), "SLACK_BOT_TOKEN")
