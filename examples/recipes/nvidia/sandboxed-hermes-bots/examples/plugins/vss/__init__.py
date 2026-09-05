# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""vss plugin: put a video in front of NVIDIA RT-VLM and get text back."""

import logging

from . import schemas, tools

logger = logging.getLogger(__name__)


def register(ctx):
    ctx.register_tool(
        name="vss_describe_video",
        toolset="vss",
        schema=schemas.VSS_DESCRIBE_VIDEO,
        handler=tools.vss_describe_video,
    )
    ctx.register_tool(
        name="vss_ask_video",
        toolset="vss",
        schema=schemas.VSS_ASK_VIDEO,
        handler=tools.vss_ask_video,
    )
    logger.info("vss: registered vss_describe_video, vss_ask_video")
