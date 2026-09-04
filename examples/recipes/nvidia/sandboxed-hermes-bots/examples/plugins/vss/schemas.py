# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tool schemas for vss: what the model sees."""

VSS_DESCRIBE_VIDEO = {
    "name": "vss_describe_video",
    "description": (
        "Watch a video with NVIDIA RT-VLM and return a timestamped description of "
        "what happens: people, vehicles, equipment, actions, in order. Use this "
        "first when asked about a video you have not seen. `video` is a filename "
        "under /sandbox/videos or an http(s) URL. Takes 10 to 60 seconds."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "video": {
                "type": "string",
                "description": "Filename under /sandbox/videos (e.g. 'forklift-training.mp4') or an http(s) URL.",
            },
            "focus": {
                "type": "string",
                "description": "Optional: what to pay particular attention to (e.g. 'safety hazards', 'who enters the room').",
            },
        },
        "required": ["video"],
    },
}

VSS_ASK_VIDEO = {
    "name": "vss_ask_video",
    "description": (
        "Ask NVIDIA RT-VLM one specific question about a video and get one answer "
        "grounded in what is visible. Use after vss_describe_video when a follow-up "
        "needs a closer look (counts, colours, whether X happened). `video` is a "
        "filename under /sandbox/videos or an http(s) URL."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "video": {"type": "string", "description": "Filename under /sandbox/videos or an http(s) URL."},
            "question": {"type": "string", "description": "The question. Be concrete: 'How many people wear hi-vis?' not 'Is it safe?'"},
        },
        "required": ["video", "question"],
    },
}
