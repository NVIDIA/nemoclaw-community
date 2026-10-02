# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Validation for the distinct production-trace request matrix."""

from __future__ import annotations

from typing import Any


def validate_matrix(matrix: dict[str, Any], *, allow_partial: bool = False) -> None:
    scenarios = matrix.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("matrix must contain a non-empty scenarios list")
    if any(not isinstance(scenario, dict) for scenario in scenarios):
        raise ValueError("each scenario must be an object")
    ids = [scenario.get("id") for scenario in scenarios]
    prompts = [scenario.get("prompt") for scenario in scenarios]
    if any(not isinstance(value, str) or not value.strip() for value in ids):
        raise ValueError("every scenario needs a non-empty id")
    if len(set(ids)) != len(ids):
        raise ValueError("scenario IDs must be unique")
    if any(not isinstance(value, str) or not value.strip() for value in prompts):
        raise ValueError("every scenario needs a non-empty prompt")
    normalized_prompts = [value.strip().casefold() for value in prompts]
    if len(set(normalized_prompts)) != len(normalized_prompts):
        raise ValueError("source workload prompts must be distinct")
    if not allow_partial and not 36 <= len(scenarios) <= 48:
        raise ValueError("production source workload must contain 36–48 distinct requests")
    if not allow_partial and any(
        not isinstance(scenario.get("behavior_family"), str)
        or not scenario["behavior_family"].strip()
        for scenario in scenarios
    ):
        raise ValueError("every production request needs a behavior_family")
