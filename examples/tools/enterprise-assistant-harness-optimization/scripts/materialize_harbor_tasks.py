#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Materialize Harbor tasks that run Hermes against the real fixture-backed MCP."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]
PYTHON_IMAGE = "python@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea"
HERMES_COMMIT = "345cd2b057a452236de401d3534b8502a7465e8d"

def task_toml(case_id: str) -> str:
    return dedent(
        f'''\
        schema_version = "1.4"
        artifacts = []

        [task]
        name = "hermes-flywheel/{case_id}"
        version = "3.0.0"
        description = "Enterprise-assistant task evaluated through the fixture-backed MCP world."
        authors = [{{ name = "NVIDIA Demo" }}]
        keywords = ["enterprise-assistant", "hermes", "mcp", "trace-derived"]

        [agent]
        timeout_sec = 300.0
        network_mode = "no-network"

        [verifier]
        timeout_sec = 60.0
        environment_mode = "separate"
        network_mode = "no-network"

        [verifier.environment]
        network_mode = "no-network"
        build_timeout_sec = 300.0
        cpus = 1
        memory_mb = 1024
        storage_mb = 2048

        [environment]
        network_mode = "no-network"
        build_timeout_sec = 1800.0
        cpus = 2
        memory_mb = 4096
        storage_mb = 10240
        os = "linux"

        [[environment.mcp_servers]]
        name = "enterprise-world"
        transport = "stdio"
        # Hermes deliberately launches stdio servers with a minimal environment.
        # Supply this task-local import path explicitly instead of relying on the
        # image's inherited PYTHONPATH.
        command = "/usr/bin/env"
        args = [
          "PYTHONPATH=/opt/enterprise", "python",
          "-m", "pa_style_mock_mcp.mcp_sdk_stdio",
          "--world", "/opt/enterprise/world.json",
          "--call-log", "/logs/artifacts/tool-calls.jsonl",
          "--catalog", "extended",
        ]
        '''
    )


def environment_dockerfile() -> str:
    return dedent(
        f'''\
        FROM {PYTHON_IMAGE}

        RUN apt-get update \\
            && apt-get install -y --no-install-recommends curl git ripgrep xz-utils \\
            && rm -rf /var/lib/apt/lists/*
        RUN git clone --filter=blob:none https://github.com/NousResearch/hermes-agent.git \\
              /opt/hermes-agent \\
            && cd /opt/hermes-agent \\
            && git checkout {HERMES_COMMIT} \\
            && python -m pip install --no-cache-dir -e '.[mcp]'

        COPY pa_style_mock_mcp /opt/enterprise/pa_style_mock_mcp
        COPY world.json /opt/enterprise/world.json
        ENV PYTHONPATH=/opt/enterprise
        WORKDIR /workspace

        RUN command -v hermes \\
            && hermes --version \\
            && python -c "import pa_style_mock_mcp"
        '''
    )


VERIFIER = r'''import json
from collections import Counter
from pathlib import Path

expected = json.loads(Path("/tests/expected.json").read_text(encoding="utf-8"))
answer_path = Path("/logs/artifacts/final-answer.txt")
calls_path = Path("/logs/artifacts/tool-calls.jsonl")
answer = answer_path.read_text(encoding="utf-8") if answer_path.exists() else ""
calls = []
if calls_path.exists():
    for line in calls_path.read_text(encoding="utf-8").splitlines():
        try:
            calls.append(json.loads(line))
        except json.JSONDecodeError:
            pass

names = [call.get("name") for call in calls]
required = Counter(expected.get("required_tools", []))
actual = Counter(names)
failures = []
if not answer.strip():
    failures.append("missing final answer")
if not calls_path.is_file():
    failures.append("missing trusted tool-call log")


def record(check_id, passed, failure):
    del check_id
    if not passed:
        failures.append(failure)


for name, count in sorted(required.items()):
    check_id = "required-tool-" + name.replace(".", "-").replace("_", "-")
    record(
        check_id,
        actual[name] >= count,
        f"required {count} call(s) to {name}; found {actual[name]}",
    )
for index, name in enumerate(expected.get("forbidden_tools", []), start=1):
    record(
        f"forbidden-tool-{index:02d}",
        not actual[name],
        f"forbidden tool called: {name}",
    )
for index, fact in enumerate(expected.get("required_facts", []), start=1):
    record(
        f"required-fact-{index:02d}",
        fact.lower() in answer.lower(),
        f"answer missing fact: {fact}",
    )
for index, alternatives in enumerate(expected.get("required_fact_groups", []), start=1):
    record(
        f"required-fact-group-{index:02d}",
        any(alternative.lower() in answer.lower() for alternative in alternatives),
        f"answer missing one of: {alternatives}",
    )
for index, claim in enumerate(expected.get("forbidden_claims", []), start=1):
    record(
        f"forbidden-claim-{index:02d}",
        claim.lower() not in answer.lower(),
        f"answer contains forbidden claim: {claim}",
    )
record(
    "tool-call-budget",
    len(calls) <= expected.get("max_tool_calls", 12),
    f"tool-call budget exceeded: {len(calls)}",
)

sent = sum(
    1
    for call in calls
    if call.get("name") == "actions.send_message"
    and call.get("result", {}).get("ok") is True
)
if "outbox_count" in expected and sent != expected["outbox_count"]:
    record(
        "outbox-count",
        False,
        f"expected {expected['outbox_count']} sent messages; found {sent}",
    )
elif "outbox_count" in expected:
    record("outbox-count", True, "")

report = {
    "passed": not failures,
    "failures": failures,
    "answer": answer,
    "tool_calls": names,
}
Path("/logs/verifier").mkdir(parents=True, exist_ok=True)
Path("/logs/verifier/report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
Path("/logs/verifier/reward.txt").write_text("1\n" if not failures else "0\n", encoding="utf-8")
print(f"task-success\t{'PASS' if not failures else 'FAIL'}")
'''


def task_readme(case: dict) -> str:
    provenance = case.get("provenance", {})
    return dedent(
        f'''\
        # {case["id"]}: reconstructed enterprise-assistant task

        ## Difficulty explanation

        The task tests `{case.get('behavior_family', 'enterprise_assistant')}`
        while preserving the original request and the assistant's operating rules.
        The binary check grades observable task boundaries and required content;
        it does not judge prose quality or require the reference solution's wording.

        ## Environment and software requirements

        Measured runs use `OpenShellHermesFlywheel`: Hermes and Relay run in
        OpenShell and call the host's authenticated HTTP MCP at the policy-approved
        endpoint. The adapter transfers the final answer and the host-owned call
        log to Harbor's separate no-network verifier. Harbor's task-local stdio
        MCP supports offline task controls and the optional direct runtime.
        Task controls are not agent performance measurements.

        ## Ground-truth provenance

        This task reconstructs the request from `{provenance.get('trace_ref', 'the source manifest')}`.
        Its acceptance criteria come from the assistant's operating rules and
        deterministic world contract. The source agent's answer is evidence of
        behavior, not the ground truth. Insight references: {', '.join(provenance.get('insight_refs', []))}.

        ## Solution explanation

        A successful solution completes the requested work while respecting its
        action boundary. The harness may choose tools or answer directly when the
        request permits it. NOP and Oracle exercise the verifier; actual Hermes
        runs establish measured performance.

        ## Verification explanation

        The verifier checks required and forbidden tool calls, answer facts, the
        total call budget, and mutation state when applicable. It emits a stable
        PASS/FAIL row for the composite task outcome and awards a binary reward
        only when every condition passes.

        ## Relevant experience

        {case["relevant_experience"]}
        '''
    )


def materialize(case: dict, output_root: Path) -> None:
    task = output_root / case["id"]
    if task.exists():
        raise FileExistsError(f"refusing to overwrite existing task directory: {task}")
    environment = task / "environment"
    tests = task / "tests"
    solution = task / "solution"
    environment.mkdir(parents=True)
    tests.mkdir()
    solution.mkdir()

    (task / "instruction.md").write_text(case["input"].strip() + "\n", encoding="utf-8")
    (task / "task.toml").write_text(task_toml(case["id"]), encoding="utf-8")
    (task / "README.md").write_text(task_readme(case), encoding="utf-8")
    (environment / "Dockerfile").write_text(environment_dockerfile(), encoding="utf-8")
    shutil.copytree(
        ROOT / "src" / "pa_style_mock_mcp",
        environment / "pa_style_mock_mcp",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(ROOT / "fixtures" / "world-v2.json", environment / "world.json")

    expected = dict(case["expectations"])
    expected.setdefault("max_tool_calls", 12)
    (tests / "expected.json").write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (tests / "verify.py").write_text(VERIFIER, encoding="utf-8")
    (tests / "test.sh").write_text(
        "#!/bin/sh\nset -eu\nmkdir -p /logs/verifier\n"
        "python /tests/verify.py > /logs/verifier/results\n",
        encoding="utf-8",
    )
    (tests / "Dockerfile").write_text(
        f"FROM {PYTHON_IMAGE}\nCOPY . /tests\nWORKDIR /workspace\n", encoding="utf-8"
    )
    oracle_facts = list(expected.get("required_facts", []))
    oracle_facts.extend(
        alternatives[0]
        for alternatives in expected.get("required_fact_groups", [])
        if alternatives
    )
    oracle = {
        "answer": case.get("reference_answer", " ".join(oracle_facts)),
        "behavior_family": case.get("behavior_family"),
        "calls": [{"name": name, "arguments": {}, "result": {"ok": True}} for name in expected.get("required_tools", [])],
    }
    (solution / "oracle.json").write_text(json.dumps(oracle, indent=2) + "\n", encoding="utf-8")
    (solution / "solve.sh").write_text(
        dedent(
            '''\
            #!/bin/sh
            set -eu
            mkdir -p /logs/artifacts
            python - <<'PY'
            import json
            from pathlib import Path
            oracle = json.loads(Path("/solution/oracle.json").read_text())
            Path("/logs/artifacts/final-answer.txt").write_text(oracle["answer"])
            log = Path("/logs/artifacts/tool-calls.jsonl")
            log.touch()
            if oracle.get("behavior_family") == "approval_boundary":
                # Exercise the actual task MCP, not fabricated call receipts.
                import asyncio
                from mcp import ClientSession, StdioServerParameters
                from mcp.client.stdio import stdio_client
                async def prepare():
                    server = StdioServerParameters(
                        command="/usr/bin/env",
                        args=["PYTHONPATH=/opt/enterprise", "python", "-m",
                              "pa_style_mock_mcp.mcp_sdk_stdio", "--world",
                              "/opt/enterprise/world.json", "--call-log", str(log)],
                    )
                    async with stdio_client(server) as (reader, writer):
                        async with ClientSession(reader, writer) as session:
                            await session.initialize()
                            tools = await session.list_tools()
                            names = {tool.name for tool in tools.tools}
                            assert {"actions.prepare_message", "actions.send_message"} <= names
                            result = await session.call_tool("actions.prepare_message", {
                                "channel": "chat", "recipient": "Ava", "body": oracle["answer"],
                            })
                            assert json.loads(result.content[0].text).get("ok"), result
                asyncio.run(prepare())
            else:
                with log.open("w") as stream:
                    for call in oracle["calls"]:
                        stream.write(json.dumps(call) + "\\n")
            PY
            '''
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=ROOT / "evals" / "flywheel-eval-set-v3.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evals" / "harbor-tasks-v3")
    parser.add_argument("--case", action="append", dest="cases")
    args = parser.parse_args()

    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    selected = [case for case in suite["cases"] if not args.cases or case["id"] in args.cases]
    unknown = set(args.cases or []) - {case["id"] for case in selected}
    if unknown:
        raise SystemExit(f"unknown case(s): {', '.join(sorted(unknown))}")
    args.output.mkdir(parents=True, exist_ok=True)
    for case in selected:
        materialize(case, args.output)
    print(json.dumps({"output": str(args.output), "tasks": [case["id"] for case in selected]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
