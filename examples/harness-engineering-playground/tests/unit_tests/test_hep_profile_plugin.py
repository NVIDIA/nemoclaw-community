# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Regression test for hep_profile_plugin.py's clobber-not-merge registration.

Requires the optional `deepagents` extra; the whole module is skipped cleanly
when it isn't installed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("deepagents")

from deepagents.profiles.harness import harness_profiles as hr  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN_PATH = _PROJECT_ROOT / "plugins" / "hep_profile_plugin.py"


def _load_plugin_module() -> None:
    """Import hep_profile_plugin.py fresh, triggering its module-level side effect."""
    spec = importlib.util.spec_from_file_location("hep_profile_plugin", _PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def test_plugin_clears_existing_middleware_instead_of_merging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = "_hep_test_clobber"

    class _FakeMiddleware:
        pass

    # Simulate a pre-existing ("built-in") registration with non-empty
    # middleware for this key, exactly like a real profile's bootstrap entry.
    hr._register_harness_profile_impl(key, hr.HarnessProfile(extra_middleware=[_FakeMiddleware()]))
    assert hr._get_harness_profile(key).extra_middleware  # sanity: non-empty before

    profile_file = tmp_path / "blank_profile.py"
    profile_file.write_text(
        "from deepagents.profiles.harness.harness_profiles import (\n"
        "    HarnessProfile,\n"
        "    _register_harness_profile_impl,\n"
        ")\n\n"
        "def register() -> None:\n"
        f"    _register_harness_profile_impl('{key}', HarnessProfile(extra_middleware=[]))\n"
    )
    monkeypatch.setenv("HEP_PROFILE_FILE", str(profile_file))

    try:
        _load_plugin_module()
        # A naive (merging) registration would still show the old middleware
        # here, since register_harness_profile's merge-by-type can only add
        # or replace, never remove, an existing entry's middleware.
        assert hr._get_harness_profile(key).extra_middleware == ()
    finally:
        hr._HARNESS_PROFILES.pop(key, None)
