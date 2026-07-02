# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Monkey-patch deepagents to add unregister_harness_profile.

Vendored from the deepagents fork's `.tmp/deepagents_patch.py`. Fills a gap
in the deepagents public API that does not yet have a deregistration
primitive — used by `DeepAgentsAdapter.validate_config`'s trial-import
pre-check to restore the harness-profile registry to its pre-trial baseline.

Once upstream deepagents ships `unregister_harness_profile` natively, this
file can be deleted with no other changes required.
"""

from __future__ import annotations

_applied = False


def apply() -> None:
    """Inject `unregister_harness_profile` into deepagents, once per process."""
    global _applied  # noqa: PLW0603
    if _applied:
        return

    import deepagents as _da
    from deepagents.profiles.harness import harness_profiles as _hr

    def unregister_harness_profile(key: str) -> None:
        """Remove a registered harness profile by key.

        Ensures the built-in profile bootstrap has run first, then removes the
        entry so a subsequent register_harness_profile call starts from a clean
        slate rather than merging on top of the existing registration.

        Args:
            key: The provider or model spec to remove, e.g.
                ``"openai:nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B"``.
                Silently does nothing if the key is not registered.
        """
        _hr._ensure_harness_profiles_loaded()
        _hr._HARNESS_PROFILES.pop(key, None)

    _hr.unregister_harness_profile = unregister_harness_profile
    _da.unregister_harness_profile = unregister_harness_profile
    _applied = True
