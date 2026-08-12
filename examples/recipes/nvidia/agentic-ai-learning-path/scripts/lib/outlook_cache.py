#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read the refresh-token freshness horizon from an Outlook login cache."""

from __future__ import annotations

import json
import sys
from pathlib import Path


DEFAULT_REFRESH_LIFETIME_MS = 90 * 24 * 60 * 60 * 1000


def refresh_expires_at_ms(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return 0
        refresh_token = data.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token.strip():
            return 0
        if int(data.get("expires_at_ms", 0)) <= 0:
            return 0
        explicit = int(data.get("refresh_expires_at_ms", 0))
        if explicit > 0:
            return explicit
        # Legacy caches only recorded the one-hour access-token expiry. Migrate
        # them using the cache creation time plus the compatibility horizon
        # instead of forcing an hourly login.
        return int(path.stat().st_mtime * 1000) + DEFAULT_REFRESH_LIFETIME_MS
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return 0


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: outlook_cache.py CACHE_PATH")
    print(refresh_expires_at_ms(Path(sys.argv[1])))


if __name__ == "__main__":
    main()
