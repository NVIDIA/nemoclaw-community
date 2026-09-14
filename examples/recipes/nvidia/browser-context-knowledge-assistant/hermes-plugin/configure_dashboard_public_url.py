#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Set the public URL in NemoClaw's isolated Hermes dashboard profile."""

from __future__ import annotations

import sys
from urllib.parse import urlsplit

from configure_dashboard_auth import atomic_write, dashboard_config_path
import yaml


def validated_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise SystemExit("Public URL must be one HTTPS origin with no path, query, or fragment")
    return f"https://{parsed.netloc}"


def set_public_url(value: str) -> None:
    path = dashboard_config_path()
    config = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise SystemExit("Hermes dashboard config root must be a mapping")
    dashboard = config.setdefault("dashboard", {})
    if not isinstance(dashboard, dict):
        raise SystemExit("Hermes dashboard config must be a mapping")
    dashboard["public_url"] = validated_origin(value)
    atomic_write(path, yaml.safe_dump(config, sort_keys=False, allow_unicode=True), 0o640)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: configure_dashboard_public_url.py https://host")
    set_public_url(sys.argv[1])
    print("Hermes dashboard public URL configured.")


if __name__ == "__main__":
    main()
