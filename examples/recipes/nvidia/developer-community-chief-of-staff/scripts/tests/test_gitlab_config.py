# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import subprocess
from pathlib import Path

RECIPE_DIR = Path(__file__).resolve().parents[2]
LIB = RECIPE_DIR / "scripts/_lib.sh"


def source_lib(api_url: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GITLAB_API_URL"] = api_url
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; printf "%s:%s\\n" "$GITLAB_API_HOST" "$GITLAB_API_PORT"',
            "bash",
            str(LIB),
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )


def test_gitlab_api_url_derives_exact_host_and_port():
    result = source_lib("https://gitlab.example.com:8443/api/v4")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "gitlab.example.com:8443\n"


def test_gitlab_api_url_rejects_plaintext_and_embedded_credentials():
    plaintext = source_lib("http://gitlab.example.com/api/v4")
    credentials = source_lib("https://user:pass@gitlab.example.com/api/v4")

    assert plaintext.returncode != 0
    assert "must be an https:// URL" in plaintext.stderr
    assert credentials.returncode != 0
    assert "must not contain embedded credentials" in credentials.stderr


def test_gitlab_provider_uses_the_private_172_network_only():
    provider = (RECIPE_DIR / "providers/gitlab.yaml").read_text(encoding="utf-8")

    assert "172.16.0.0/12" in provider
    assert "172.0.0.0/8" not in provider
