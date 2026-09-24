# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Export a NeMo `agent.yaml` so it runs outside NeMo Platform.

    python3 export_agent.py agent/agent.yaml --to ~/cad-export

Writes three ways to run the same agent, described in the README:

  run_agent.py   the Deep Agents SDK directly, reading agent.yaml as it stands
  dcode/         a dcode project: provider, MCP servers, skills, subagents
  curl.sh        the deployed agent over its OpenAI-compatible endpoint

Everything is derived from the config, so a promoted candidate exports the same
way the baseline does. Nothing here talks to the platform.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import yaml

GATEWAY = "http://localhost:8080/apis/inference-gateway/v2/workspaces/default/openai/-/v1"
RUNNER = Path(__file__).resolve().parent / "harness" / "standalone" / "run_agent.py"


def _model(spec: dict) -> dict:
    return spec.get("models", {}).get("default", {})


def _subagents(spec: dict) -> list[dict]:
    harness = (spec.get("harnesses") or {}).get("deepagents") or {}
    return ((harness.get("settings") or {}).get("deepagents") or {}).get("subagents") or []


def _skills(config: Path, spec: dict) -> Path | None:
    """Return the config's skills directory, if it has one with content."""
    workspace = (spec.get("environment") or {}).get("workspace")
    if not workspace:
        return None
    skills = (config.parent / workspace / "skills").resolve()
    has_content = skills.is_dir() and any(p.name != ".gitkeep" for p in skills.iterdir())
    return skills if has_content else None


def write_sdk(out: Path) -> None:
    """Copy the standalone runner, which reads agent.yaml unchanged."""
    shutil.copyfile(RUNNER, out / "run_agent.py")


def write_curl(out: Path, spec: dict, deployment: str) -> None:
    """Write the OpenAI-compatible call against a deployment of this agent."""
    endpoint = (f"http://localhost:8080/apis/agents/v2/workspaces/default"
                f"/deployments/{deployment}/-/v1/chat/completions")
    (out / "curl.sh").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "# The deployed agent over its OpenAI-compatible endpoint. The /-/ segment\n"
        "# is required; without it the gateway returns 404. Add '\"stream\": true'\n"
        "# for SSE. A `tools` parameter is accepted but ignored: this is an agent\n"
        "# behind a chat-completions shape, not a model a coding harness can drive.\n"
        "#\n"
        "# The body is built with json.dumps rather than string interpolation, so a\n"
        "# prompt containing quotes, backslashes or newlines stays valid JSON.\n"
        'BODY=$(python3 -c \'import json,sys; '
        'print(json.dumps({"messages":[{"role":"user","content":sys.argv[1]}]}))\' '
        '"${1:-Who are you?}")\n'
        f'curl -s -X POST "{endpoint}" \\\n'
        "  -H 'Content-Type: application/json' \\\n"
        '  -d "$BODY"\n'
    )
    (out / "curl.sh").chmod(0o755)


def write_dcode(out: Path, config: Path, spec: dict) -> list[str]:
    """Lay out a dcode project. Returns notes about what could not be carried."""
    notes: list[str] = []
    root = out / "dcode"
    (root / ".deepagents").mkdir(parents=True, exist_ok=True)

    # MCP servers: `url` carries the command for stdio, with args alongside.
    servers = (spec.get("mcp") or {}).get("servers") or {}
    if servers:
        (root / ".deepagents" / ".mcp.json").write_text(json.dumps(
            {"mcpServers": {name: {"command": s["url"], "args": s.get("args", [])}
                            for name, s in servers.items()}}, indent=2) + "\n")

    # The system prompt becomes project AGENTS.md. dcode keeps its own coding
    # agent identity and appends this, rather than replacing the prompt.
    prompt = ((spec.get("instructions") or {}).get("system") or {}).get("content", "")
    if prompt:
        (root / ".deepagents" / "AGENTS.md").write_text(prompt.rstrip() + "\n")
        notes.append("the system prompt is appended to dcode's own, not substituted for it")

    # Skills copy verbatim: same SKILL.md frontmatter.
    skills = _skills(config, spec)
    if skills:
        shutil.copytree(skills, root / ".deepagents" / "skills", dirs_exist_ok=True)

    # Subagents: one directory each, frontmatter plus the prompt as the body.
    for sub in _subagents(spec):
        d = root / ".deepagents" / "agents" / sub["name"]
        d.mkdir(parents=True, exist_ok=True)
        front = {"name": sub["name"], "description": " ".join(sub.get("description", "").split())}
        d.joinpath("AGENTS.md").write_text(
            "---\n" + yaml.safe_dump(front, sort_keys=False).strip() + "\n---\n\n"
            + sub.get("system_prompt", "").rstrip() + "\n")
        if sub.get("response_format"):
            notes.append(f"subagent '{sub['name']}' loses its response_format: "
                         "dcode reads only name, description and model from frontmatter")

    # Project skills and subagents are found only under a git root, so make one.
    if not (root / ".git").is_dir():
        subprocess.run(["git", "init", "-q"], cwd=root, check=False)
        notes.append("git init run in dcode/: project skills and subagents are "
                     "invisible without a git root")

    model = _model(spec).get("model", "")
    base_url = _model(spec).get("base_url", GATEWAY)
    (root / "run.sh").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'cd "$(dirname "$0")"\n'
        "# DEEPAGENTS_HOME relocates dcode's whole configuration, so this writes a\n"
        "# config beside the project instead of editing ~/.deepagents/config.toml.\n"
        "# Sharing that file would mean either clobbering your recent model, agent\n"
        "# and approval mode, or silently reusing an existing [models.providers.openai]\n"
        "# block pointed at the real OpenAI endpoint and invoking a NeMo model name\n"
        "# against it.\n"
        'export DEEPAGENTS_HOME="$PWD/.dcode-home"\n'
        'mkdir -p "$DEEPAGENTS_HOME"\n'
        'cat > "$DEEPAGENTS_HOME/config.toml" <<TOML\n'
        "# dcode only accepts known provider ids, so the NeMo gateway is configured\n"
        "# as `openai` with a custom base_url.\n"
        "[models.providers.openai]\n"
        f'base_url = "{base_url}"\n'
        'api_key = "not-used"\n'
        f'models = ["{model}"]\n'
        "\n[warnings]\n"
        'suppress = ["tavily"]\n'
        "TOML\n"
        "# --auto-classifier-model matters. Auto mode reviews each action with a\n"
        "# second model, and its default is not served by this gateway: the\n"
        "# classifier 404s, a failed classification counts as denied, and every\n"
        "# tool call is refused with 'Auto denied [classifier unavailable]'.\n"
        "#\n"
        "# Pass --yolo to skip review entirely, which is usually what you want\n"
        "# against a local FreeCAD session you are willing to let the agent drive.\n"
        f"OPENAI_API_KEY=not-used exec dcode -M openai:{model} \\\n"
        f"  --auto-classifier-model openai:{model} --trust-project-mcp \"$@\"\n"
    )
    (root / "run.sh").chmod(0o755)
    notes.append("dcode config is written to dcode/.dcode-home via DEEPAGENTS_HOME, "
                 "so your ~/.deepagents/config.toml is neither read nor written")
    notes.append("MCP tools need the interactive TUI: headless blocks unannotated "
                 "MCP actions and --yolo is ignored there")
    notes.append("run.sh pins the Auto-mode classifier to the same model: its "
                 "default is not served here, and a classifier that 404s denies "
                 "every action")
    return notes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config", type=Path, help="path to an agent.yaml")
    parser.add_argument("--to", type=Path, required=True, help="output directory")
    parser.add_argument("--deployment", default="cad-agent-deployment",
                        help="deployment name for curl.sh")
    args = parser.parse_args()

    config = args.config.resolve()
    spec = yaml.safe_load(config.read_text())
    out = args.to.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    write_sdk(out)
    write_curl(out, spec, args.deployment)
    notes = write_dcode(out, config, spec)

    skills = _skills(config, spec)
    print(f"exported {spec.get('name')} -> {out}")
    print(f"  model      {_model(spec).get('model')}")
    print(f"  mcp        {', '.join((spec.get('mcp') or {}).get('servers') or {}) or 'none'}")
    print(f"  skills     {', '.join(p.name for p in skills.iterdir()) if skills else 'none'}")
    print(f"  subagents  {', '.join(s['name'] for s in _subagents(spec)) or 'none'}")
    for note in notes:
        print(f"  note: {note}")
    print(f"\n  SDK    python3 {out}/run_agent.py {config}")
    print(f"  dcode  {out}/dcode/run.sh")
    print(f"  curl   {out}/curl.sh 'your prompt'")


if __name__ == "__main__":
    main()
