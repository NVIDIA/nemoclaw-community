# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""NVIDIA Nemotron 3 Ultra harness profile — self-hosted, OpenAI-compatible endpoint.

Registers a `HarnessProfile` for NVIDIA Nemotron 3 Ultra served through a
self-hosted, OpenAI-compatible endpoint. This is a deliberately minimal
starting point; additional middleware and prompt tuning can be added as
needed.
"""

from deepagents import HarnessProfile, register_harness_profile


_NEMOTRON_ULTRA_MODEL_SPECS: tuple[str, ...] = (
    # Self-hosted Nemotron 3 Ultra with openai API.
    "openai:nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B",
)


def register() -> None:
    """Register the built-in Nemotron 3 Ultra harness profile."""
    profile = HarnessProfile(
        system_prompt_suffix="",
        extra_middleware=[],
    )
    for spec in _NEMOTRON_ULTRA_MODEL_SPECS:
        register_harness_profile(spec, profile)
