"""Ask NemoClaw browser-context plugin."""
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0


def register(_ctx) -> None:
    """Satisfy Hermes plugin discovery for this dashboard-only plugin.

    The authenticated HTTP routes are registered through ``dashboard/plugin_api.py``;
    this plugin intentionally adds no model tools, hooks, or command handlers.
    """
