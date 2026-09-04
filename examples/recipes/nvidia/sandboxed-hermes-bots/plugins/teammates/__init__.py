# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""teammates plugin — lets a bot message a teammate bot directly."""

import logging

from . import schemas, tools

logger = logging.getLogger(__name__)


def register(ctx):
    """Wire the teammates tools into the registry."""
    ctx.register_tool(
        name="message_teammate",
        toolset="peer_messaging",
        schema=schemas.MESSAGE_TEAMMATE,
        handler=tools.message_teammate,
    )
    ctx.register_tool(
        name="list_teammates",
        toolset="peer_messaging",
        schema=schemas.LIST_TEAMMATES,
        handler=tools.list_teammates,
    )
    # Once per turn, Hermes hands hooks the user message exactly as received,
    # before it decides what this bot's own model can see. Remember any images
    # so message_teammate can forward them to a teammate whose model can look.
    # Observer only: returns nothing, changes nothing.
    ctx.register_hook("pre_llm_call", _remember_images)
    logger.info("teammates: registered message_teammate, list_teammates, image relay")


def _remember_images(session_id="", user_message=None, **_ignored):
    try:
        tools.remember_turn_images(session_id or "", user_message)
    except Exception as exc:  # never let bookkeeping break a turn
        logger.debug("teammates: image relay bookkeeping failed: %s", exc)
    return None
