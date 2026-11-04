# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run the real Hermes loop inside the sandbox with only its terminal tool."""

import json
import os

from run_agent import AIAgent


def main():
    agent = AIAgent(
        base_url=os.environ["TOOL_SERVICE_URL"] + "/v1",
        api_key="local-proxy",
        # The host proxy maps this alias to the configured real ACTOR_MODEL.
        model="guard-example-actor",
        provider="custom",
        enabled_toolsets=["terminal"],
        max_iterations=8,
        quiet_mode=True,
        api_mode="chat_completions",
        max_tokens=2048,
        run_budget_seconds=120,
        skip_context_files=True,
        skip_memory=True,
        skip_background_review=True,
    )
    # Hermes 0.20.6's nonstreaming path; this example holds complete JSON responses.
    agent._disable_streaming = True
    answer = agent.run_conversation(
        os.environ["AGENT_TASK"] + "\nUse the terminal tool and the provided service client. "
        "Read with `python3 /opt/decision-guard/mail_client.py inbox`. "
        "Send with `python3 /opt/decision-guard/mail_client.py send '<JSON>'`, "
        "Use the action fields shown in the tool result. "
        "If a send is rejected, report the rejection; do not retry it or bypass the mail client."
    )
    print(
        json.dumps(
            {
                "hermes_completed": bool(answer.get("completed") and not answer.get("failed")),
                "result": answer,
            },
            default=str,
        )
    )


if __name__ == "__main__":
    main()
