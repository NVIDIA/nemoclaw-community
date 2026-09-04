# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tool schemas for teammates — what the LLM sees."""

MESSAGE_TEAMMATE = {
    "name": "message_teammate",
    "description": (
        "Send a message DIRECTLY to a teammate bot running on another machine or "
        "in another sandbox, and get their reply back. Use this to delegate work, "
        "ask for a second opinion, request a critique, or hand off a task. "
        "The teammate runs a full agent turn on their own hardware with their own "
        "tools and memory, then their answer is returned to you. "
        "Call list_teammates first if you are unsure who is reachable. "
        "Be specific in your message; the teammate does not see this conversation. "
        "Any image attached to the message you are currently answering is forwarded "
        "with yours automatically, so a teammate who can see can look at it. Do not "
        "send file paths; they mean nothing outside your sandbox."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "teammate": {
                "type": "string",
                "description": "Name of the teammate to message (e.g. 'beta'). Use list_teammates to see options.",
            },
            "message": {
                "type": "string",
                "description": (
                    "The full message to send. Include all context the teammate needs; "
                    "they cannot see your conversation history."
                ),
            },
            "with_images": {
                "type": "boolean",
                "description": (
                    "Set true to forward the images attached to the current user turn along with "
                    "this message. Off by default: pixels stay in this sandbox unless you choose to "
                    "send them. Use it only when the teammate needs to see the image to answer."
                ),
            },
        },
        "required": ["teammate", "message"],
    },
}

LIST_TEAMMATES = {
    "name": "list_teammates",
    "description": (
        "List the teammate bots you can reach with message_teammate. "
        "Returns each teammate's name and a short note about their role."
    ),
    "parameters": {"type": "object", "properties": {}},
}
