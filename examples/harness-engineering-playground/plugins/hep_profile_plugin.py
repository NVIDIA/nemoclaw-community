# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Pytest plugin entrypoint that registers a hep-managed harness profile.

Loaded via `-p hep_profile_plugin` with this file's directory prepended to
PYTHONPATH (see `hep.adapters.deepagents.DeepAgentsAdapter._run_pytest`).
Reads the config-file path from the HEP_PROFILE_FILE environment variable,
imports it, and calls its `register()` function — the same convention every
deepagents built-in profile file already follows — before pytest collects
any tests.

Deliberately zero third-party dependencies beyond `deepagents` itself (which
is always present in the target venv, since that's what's being evaluated):
this module gets imported inside whatever venv the target deepagents
checkout's `uv run pytest` uses, which has no reason to have hep's own
dependencies (typer, anthropic) installed.
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path


def _register_from_env() -> None:
    """Import the config file named by HEP_PROFILE_FILE and call its register()."""
    raw_path = os.environ.get("HEP_PROFILE_FILE")
    if not raw_path:
        return
    config_file = Path(raw_path)

    from deepagents.profiles.harness import harness_profiles as hr

    hr._ensure_harness_profiles_loaded()
    original_impl = hr._register_harness_profile_impl

    def _clobbering_impl(key: str, profile: object) -> None:
        # register_harness_profile additively merges onto any existing
        # registration for `key` (e.g. a built-in default) rather than
        # replacing it — and the merge can only add or replace middleware by
        # type, never remove it, so an empty extra_middleware=[] in a
        # hep-managed profile would otherwise silently no-op against a
        # built-in's non-empty middleware list. A hep-managed profile is
        # meant to fully describe the behavior for its keys, including a
        # deliberately blank starting point, so clear any existing entry
        # first rather than merging onto it.
        hr._HARNESS_PROFILES.pop(key, None)
        original_impl(key, profile)

    # Patch *before* importing the candidate module: if it does `from
    # deepagents.profiles.harness.harness_profiles import
    # _register_harness_profile_impl` (as every built-in profile file does),
    # that import binds whatever this attribute currently is into the
    # candidate's own module namespace — patching afterward would have no
    # effect on that already-bound local name.
    hr._register_harness_profile_impl = _clobbering_impl
    try:
        module_name = f"_hep_profile_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(module_name, config_file)
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.register()
    finally:
        hr._register_harness_profile_impl = original_impl


_register_from_env()
