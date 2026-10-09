# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Shared model defaults and endpoint-scoped OpenShell provider setup."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"


def model_slug() -> str:
    return os.environ.get("MODEL_SLUG") or DEFAULT_MODEL


def model_base_url(value: str | None = None) -> str:
    url = (value if value is not None else os.environ.get("MODEL_BASE_URL")) or DEFAULT_BASE_URL
    url = url.rstrip("/")
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*[a-z0-9]", host)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or any(char.isspace() for char in url)
    ):
        raise ValueError("MODEL_BASE_URL must be an HTTPS API base URL with a DNS host")
    try:
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
    except ValueError as exc:
        raise ValueError("MODEL_BASE_URL has an invalid port") from exc
    return url


def provider_name(base_url: str) -> str:
    if base_url == DEFAULT_BASE_URL:
        return "hermes-nvidia"
    return "hermes-model-" + hashlib.sha256(base_url.encode()).hexdigest()[:12]


def profile_type(base_url: str) -> str:
    return "hermes-nvidia-build" if base_url == DEFAULT_BASE_URL else provider_name(base_url)


def write_provider_profile(base_url: str, target: Path) -> tuple[str, str]:
    base_url = model_base_url(base_url)
    name = provider_name(base_url)
    profile = profile_type(base_url)
    template = (ROOT / "openshell/provider-nvidia.yaml").read_text(encoding="utf-8")
    if base_url != DEFAULT_BASE_URL:
        host = urlsplit(base_url).hostname
        port = urlsplit(base_url).port or 443
        template = template.replace("id: hermes-nvidia-build", f"id: {profile}")
        template = template.replace("display_name: NVIDIA Build for Hermes", "display_name: Model API for Hermes")
        template = template.replace(
            "description: NVIDIA inference access for the tutorial's pinned Hermes image",
            "description: Model API access for the tutorial's pinned Hermes image",
        )
        template = template.replace("description: NVIDIA API key", "description: Model provider API key")
        template = template.replace(
            "- host: integrate.api.nvidia.com\n    port: 443",
            f"- host: {host}\n    port: {port}",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template, encoding="utf-8")
    return name, profile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("MODEL_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    try:
        base_url = model_base_url(args.base_url)
        name, profile = write_provider_profile(base_url, args.profile)
    except ValueError as exc:
        parser.error(str(exc))
    print(name, profile, base_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
