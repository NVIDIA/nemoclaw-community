# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for exporting an agent.yaml to run outside NeMo Platform.

The export is a translation, and the parts that do not survive it matter as
much as the parts that do: dcode reads only name, description and model from
subagent frontmatter, so a response_format is lost and the export says so.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EXAMPLE))

try:
    import yaml  # noqa: F401
    import export_agent
except ImportError:  # pragma: no cover - PyYAML is not in requirements.txt
    export_agent = None


@unittest.skipIf(export_agent is None, "PyYAML not installed")
class Export(unittest.TestCase):
    """One agent.yaml becomes three ways to run the same agent."""

    SPEC = {
        "name": "cad-agent",
        "instructions": {"system": {"content": "You are a CAD Agent."}},
        "models": {"default": {"model": "a-model", "base_url": "http://gw/v1"}},
        "mcp": {"servers": {"freecad": {"transport": "stdio", "url": "/bin/uvx",
                                        "args": ["freecad-mcp"]}}},
        "environment": {"workspace": "./workspace"},
        "harnesses": {"deepagents": {"settings": {"deepagents": {"subagents": [
            {"name": "analyst", "description": "Measures the reference.",
             "system_prompt": "Analyze only.", "response_format": {"type": "object"}},
        ]}}}},
    }

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        agent = self.tmp / "agent"
        (agent / "workspace" / "skills" / "policy").mkdir(parents=True)
        (agent / "workspace" / "skills" / "policy" / "SKILL.md").write_text(
            "---\nname: policy\ndescription: d\n---\n\nbody\n")
        self.config = agent / "agent.yaml"
        self.config.write_text(yaml.safe_dump(self.SPEC))
        self.out = self.tmp / "out"
        self.notes = export_agent.write_dcode(self.out, self.config, self.SPEC)
        self.dcode = self.out / "dcode" / ".deepagents"

    def test_mcp_servers_become_a_dcode_config(self) -> None:
        servers = json.loads((self.dcode / ".mcp.json").read_text())["mcpServers"]
        self.assertEqual(servers["freecad"], {"command": "/bin/uvx", "args": ["freecad-mcp"]})

    def test_the_system_prompt_becomes_project_agents_md(self) -> None:
        self.assertIn("You are a CAD Agent.", (self.dcode / "AGENTS.md").read_text())

    def test_skills_copy_verbatim(self) -> None:
        self.assertTrue((self.dcode / "skills" / "policy" / "SKILL.md").is_file())

    def test_a_subagent_becomes_frontmatter_plus_prompt(self) -> None:
        text = (self.dcode / "agents" / "analyst" / "AGENTS.md").read_text()
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("name: analyst", text)
        self.assertIn("Analyze only.", text)

    def test_a_lost_response_format_is_reported(self) -> None:
        # dcode reads only name, description and model from frontmatter, so a
        # structured response contract does not survive the export.
        self.assertTrue(any("response_format" in n for n in self.notes))

    def test_the_export_creates_a_git_root(self) -> None:
        # Project skills and subagents are invisible to dcode without one.
        self.assertTrue((self.out / "dcode" / ".git").is_dir())


if __name__ == "__main__":
    unittest.main()
