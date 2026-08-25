# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Dated price snapshot used to convert token counts into dollars.

Prices move and tokenizers differ, so the leaderboard reports raw token counts
only. Dollars are computed from this table into each run's summary.md; the table
carries the date it was captured, so anyone can recompute an old run against a
new one.
"""

from __future__ import annotations

SNAPSHOT_DATE = "2026-08-21"

# USD per 1M tokens: (input, output). Unknown models fall back to None and the
# report prints tokens only rather than inventing a number.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "text-embedding-3-small": (0.02, 0.0),
    "azure/openai/gpt-5.5": (1.25, 10.00),
    "nvidia/deepseek-ai/deepseek-v4-pro": (0.27, 1.10),
    "nvidia/deepseek-ai/deepseek-v4-flash": (0.07, 0.28),
    "azure/openai/text-embedding-3-small": (0.02, 0.0),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    return round(input_tokens / 1e6 * price[0] + output_tokens / 1e6 * price[1], 4)


def phase_cost_usd(phase_models: dict[str, list[int]]) -> float | None:
    """Cost of one phase, summed over every model it actually called.

    Returns ``None`` if any model in the mix has no price, because a partial
    total is worse than no total — it silently understates the run.
    """
    if not phase_models:
        return 0.0
    total = 0.0
    for model, (prompt, completion) in phase_models.items():
        priced = cost_usd(model, prompt, completion)
        if priced is None:
            return None
        total += priced
    return round(total, 4)
