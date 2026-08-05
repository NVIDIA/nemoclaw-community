# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for DeepAgentsAdapter.validate_config's in-process trial-registration pre-check.

Requires the optional `deepagents` extra (`uv sync --extra deepagents`); the whole
module is skipped cleanly when it isn't installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hep.adapters.deepagents import DeepAgentsAdapter

pytest.importorskip("deepagents")

from deepagents.profiles.harness import harness_profiles as hr  # noqa: E402


def _adapter(tmp_path: Path) -> DeepAgentsAdapter:
    return DeepAgentsAdapter(evals_dir=tmp_path)


def test_validate_config_accepts_semantically_valid_profile(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    content = (
        "from deepagents.profiles.harness.harness_profiles import (\n"
        "    HarnessProfile,\n"
        "    _register_harness_profile_impl,\n"
        ")\n\n"
        "def register() -> None:\n"
        "    _register_harness_profile_impl(\n"
        "        '_hep_test_valid', HarnessProfile(system_prompt_suffix='be careful')\n"
        "    )\n"
    )
    assert adapter.validate_config(content) is True


def test_validate_config_rejects_semantically_broken_profile(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    content = "def register() -> None:\n    this_name_is_not_defined_anywhere()\n"
    assert adapter.validate_config(content) is False


def test_validate_config_trial_restores_registry_baseline(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    key = "_hep_test_restore"
    before = dict(hr._HARNESS_PROFILES)

    first = (
        "from deepagents.profiles.harness.harness_profiles import (\n"
        "    HarnessProfile,\n"
        "    _register_harness_profile_impl,\n"
        ")\n\n"
        "def register() -> None:\n"
        f"    _register_harness_profile_impl('{key}', HarnessProfile(system_prompt_suffix='first'))\n"
    )
    second = first.replace("first", "second")

    assert adapter.validate_config(first) is True
    after_first = dict(hr._HARNESS_PROFILES)
    assert adapter.validate_config(second) is True
    after_second = dict(hr._HARNESS_PROFILES)

    assert after_first == before
    assert after_second == before
