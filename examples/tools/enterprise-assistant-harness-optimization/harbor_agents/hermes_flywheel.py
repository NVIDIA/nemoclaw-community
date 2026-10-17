# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run the tutorial's Hermes harness arms inside a Harbor task.

The adapter deliberately changes only harness configuration. Both arms use the
same model, task image, MCP server, fixture world, instruction, and verifier.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, override

import yaml
from harbor.agents.installed import hermes as harbor_hermes
from harbor.agents.installed.hermes import Hermes
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

ROOT = Path(__file__).resolve().parents[1]

# Harbor 0.22 predates Hermes' first-class NVIDIA provider. Extend its routing
# table so the built-in runner forwards the right credential and CLI provider
# instead of silently falling back to OpenRouter.
harbor_hermes._NATIVE_PROVIDERS["nvidia"] = ("nvidia", ["NVIDIA_API_KEY"])

ARM_CONFIG = {
    "baseline": {
        "profile": ROOT / "profiles" / "baseline-soul.md",
        "max_turns": 60,
        "toolsets": ["hermes-cli"],
        "tool_search": "off",
    },
    "candidate": {
        "profile": ROOT / "profiles" / "candidate-soul.md",
        "max_turns": 60,
        "toolsets": ["hermes-cli"],
        "tool_search": "off",
    },
}
# The baseline offering only the enterprise MCP tools and clarify.
# `hermes chat` reads platform_toolsets.cli; it ignores the `toolsets` key.
ARM_CONFIG["tool-scope"] = {
    **ARM_CONFIG["baseline"],
    "platform_toolsets": {"cli": ["clarify", "enterprise-world"]},
}


class HermesFlywheel(Hermes):
    """Pinned Hermes runner with selectable baseline/candidate harness arms."""

    def __init__(self, *args: Any, arm: str = "baseline", **kwargs: Any) -> None:
        if arm not in ARM_CONFIG:
            raise ValueError(f"arm must be one of: {', '.join(ARM_CONFIG)}")
        self.arm = arm
        extra_env = dict(kwargs.pop("extra_env", {}) or {})
        extra_env["HERMES_NEMO_RELAY_PLUGINS_TOML"] = (
            "/tmp/hermes/nemo-relay/relay-plugins.toml"
        )
        super().__init__(*args, extra_env=extra_env, **kwargs)

    @staticmethod
    @override
    def name() -> str:
        return "hermes-flywheel"

    @override
    async def install(self, environment: BaseEnvironment) -> None:
        """Use the Hermes and Relay versions baked into the task image."""
        await self.exec_as_agent(
            environment,
            command=(
                "command -v hermes >/dev/null && hermes --version"
            ),
            timeout_sec=30,
        )

    @override
    def get_version_command(self) -> str | None:
        return "hermes --version"

    def _build_config_yaml(self, model: str) -> str:
        arm = ARM_CONFIG[self.arm]
        config: dict[str, Any] = {
            "model": model,
            "provider": "auto",
            "toolsets": arm["toolsets"],
            "tools": {"tool_search": {"enabled": arm["tool_search"]}},
            # Shared transport resilience, not a candidate optimization. Hermes
            # applies its existing backoff; the OpenShell run timeout still caps
            # total execution. Exhausted provider errors remain invalid trials.
            "agent": {"max_turns": arm["max_turns"], "api_max_retries": 6},
            "memory": {"memory_enabled": False, "user_profile_enabled": False},
            "compression": {"enabled": True, "threshold": 0.85},
            "terminal": {"backend": "local", "timeout": 180},
            "delegation": {"max_iterations": 12},
            "checkpoints": {"enabled": False},
        }
        if "platform_toolsets" in arm:
            config["platform_toolsets"] = arm["platform_toolsets"]
        return yaml.safe_dump(config, default_flow_style=False)

    async def _stage_harness(self, environment: BaseEnvironment) -> None:
        await self.exec_as_agent(
            environment,
            command="mkdir -p /tmp/hermes/nemo-relay /logs/artifacts/relay",
            timeout_sec=10,
        )
        profile = ARM_CONFIG[self.arm]["profile"]
        await self._upload_config_text(
            environment,
            content=profile.read_text(encoding="utf-8"),
            remote_path="/tmp/hermes/SOUL.md",
            filename="SOUL.md",
        )
        relay_config = f'''version = 1

[[components]]
kind = "observability"
enabled = true

[components.config]
version = 3

[components.config.atof]
enabled = true

[[components.config.atof.sinks]]
type = "file"
output_directory = "/logs/artifacts/relay/atof"
filename = "events.jsonl"
mode = "append"

[components.config.atif]
enabled = true
output_directory = "/logs/artifacts/relay/atif"
filename_template = "trajectory-{{session_id}}.json"
agent_name = "Hermes-enterprise-world"
agent_version = "{self.arm}"
'''
        await self._upload_config_text(
            environment,
            content=relay_config,
            remote_path="/tmp/hermes/nemo-relay/relay-plugins.toml",
            filename="relay-plugins.toml",
        )

    async def _materialize_final_answer(self, environment: BaseEnvironment) -> None:
        script = r'''import json
from pathlib import Path

source = Path("/logs/agent/hermes-session.jsonl")
messages = []
if source.exists():
    for line in source.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and isinstance(item.get("messages"), list):
            messages.extend(item["messages"])
        elif isinstance(item, dict):
            messages.append(item)

answer = ""
for message in reversed(messages):
    if message.get("role") != "assistant" or message.get("tool_calls"):
        continue
    content = message.get("content", "")
    if isinstance(content, list):
        content = " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    if content:
        answer = str(content)
        break

target = Path("/logs/artifacts/final-answer.txt")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(answer, encoding="utf-8")
'''
        await self._upload_config_text(
            environment,
            content=script,
            remote_path="/tmp/extract-hermes-answer.py",
            filename="extract-hermes-answer.py",
        )
        await self.exec_as_agent(
            environment,
            command="python /tmp/extract-hermes-answer.py",
            timeout_sec=30,
        )

    @override
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        await self._stage_harness(environment)
        try:
            await super().run(instruction, environment, context)
        finally:
            await self._materialize_final_answer(environment)
            await self.exec_as_agent(
                environment,
                command=(
                    "cp /logs/agent/hermes-session.jsonl "
                    "/logs/artifacts/hermes-session.jsonl 2>/dev/null || true"
                ),
                timeout_sec=10,
            )
