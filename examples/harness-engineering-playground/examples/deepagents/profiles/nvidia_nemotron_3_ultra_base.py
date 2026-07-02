# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Built-in NVIDIA Nemotron 3 Ultra harness profile — minimal baseline.

Registers a `HarnessProfile` for NVIDIA Nemotron 3 Ultra.
This is a deliberately minimal starting point;
additional middleware and prompt tuning can be added as needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deepagents.profiles.harness.harness_profiles import (
    HarnessProfile,
    _register_harness_profile_impl,
)

if TYPE_CHECKING:
    pass

_NEMOTRON_ULTRA_MODEL_SPECS: tuple[str, ...] = (
    "openai:nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B",
    "NVIDIA:nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia:nvidia/nemotron-3-ultra-550b-a55b",
    "fireworks:accounts/fireworks/models/nemotron-3-ultra-nvfp4",
    "fireworks:accounts/fireworks/models/nemotron-3-ultra-bf16",
    "baseten:nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B",
    "openrouter:nvidia/nemotron-3-ultra-550b-a55b",
)


def register() -> None:
    """Register the built-in Nemotron 3 Ultra harness profile."""
    profile = HarnessProfile(
        system_prompt_suffix="",
        extra_middleware=[],
    )
    for spec in _NEMOTRON_ULTRA_MODEL_SPECS:
        _register_harness_profile_impl(spec, profile)
