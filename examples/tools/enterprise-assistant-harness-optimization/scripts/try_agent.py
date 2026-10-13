#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Keep a configured OpenShell sandbox and host MCP alive for interactive use."""

from __future__ import annotations

import argparse
import asyncio
import secrets
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harbor_agents.openshell_hermes import OpenShellHermesFlywheel
from harbor_agents.model_settings import model_base_url, model_slug, provider_name


async def wait_for_exit() -> None:
    await asyncio.Event().wait()


async def serve(args: argparse.Namespace) -> None:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    agent = OpenShellHermesFlywheel(
        logs_dir=output / "logs", model_name=args.model, arm=args.arm,
        openshell_provider=args.openshell_provider,
        provider_base_url=args.provider_base_url,
    )
    artifacts = output / "artifacts"
    artifacts.mkdir()
    token = secrets.token_urlsafe(32)
    runtime = output / "run"
    agent._write_runtime(runtime, "Interactive session.", mcp_token=token)
    (runtime / "interactive-env.sh").write_text(
        "export HERMES_HOME=/workspace/run/hermes\n"
        "export TERMINAL_ENV=local\n"
        "export HERMES_NEMO_RELAY_PLUGINS_TOML="
        "/workspace/run/hermes/nemo-relay/relay-plugins.toml\n"
        f"export NVIDIA_BASE_URL={shlex.quote(args.provider_base_url)}\n"
        f"export MODEL_SLUG={shlex.quote(args.model)}\n",
        encoding="utf-8",
    )
    process, log = await agent._start_remote_mcp(artifacts, token, 8765)
    created = False
    try:
        await agent._host_command(
            ["openshell", "sandbox", "create", "--name", args.name,
             "--from", agent.openshell_image, "--provider", agent.openshell_provider,
             "--policy", str(agent.openshell_policy), "--upload", f"{runtime}:/workspace",
             "--no-git-ignore", "--detach", "--no-tty"], timeout=180,
        )
        created = True
        print(
            "Host MCP service: http://127.0.0.1:8765/mcp\n"
            f"Sandbox ready: {args.name}\n"
            f"Artifacts: {output}",
            flush=True,
        )
        print(
            f"In another host terminal: openshell sandbox connect {args.name}\n"
            "Inside the sandbox: cd /workspace/run && source interactive-env.sh\n"
            f"Start Hermes: hermes chat --tui --model {args.model} --provider nvidia\n"
            "Leave this terminal running so the MCP service stays up. "
            "Press Ctrl-C here after exiting Hermes to collect the session and "
            "remove this sandbox and the MCP service.",
            flush=True,
        )
        await wait_for_exit()
    finally:
        if created:
            try:
                await agent._host_command(
                    ["openshell", "sandbox", "exec", "--name", args.name,
                     "--workdir", "/workspace/run", "--timeout", "30",
                     "--no-login-shell", "--no-tty", "--", "/bin/bash", "-c",
                     "source interactive-env.sh; hermes sessions export "
                     "/workspace/run/artifacts/hermes-session.jsonl --source cli"],
                    timeout=45, check=False,
                )
                for name in ("hermes-session.jsonl", "relay"):
                    await agent._download_optional(
                        args.name, f"/workspace/run/artifacts/{name}", artifacts / name
                    )
            finally:
                await agent._host_command(
                    ["openshell", "sandbox", "delete", args.name],
                    timeout=60, check=False,
                )
                await agent._stop_remote_mcp(process, log)
        else:
            await agent._stop_remote_mcp(process, log)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="hermes-try")
    parser.add_argument("--arm", choices=("baseline", "candidate"), default="baseline")
    parser.add_argument("--model", default=model_slug())
    parser.add_argument("--provider-base-url", default=model_base_url())
    parser.add_argument("--openshell-provider")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    parser.add_argument("--output", type=Path, default=ROOT / ".runs/interactive" / stamp)
    args = parser.parse_args()
    try:
        args.provider_base_url = model_base_url(args.provider_base_url)
    except ValueError as exc:
        parser.error(str(exc))
    args.openshell_provider = args.openshell_provider or provider_name(args.provider_base_url)
    if not args.name or len(args.name) > 15 or not all(
        char in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in args.name
    ):
        parser.error("name must contain 1–15 lowercase letters, digits or hyphens")
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(
            "ERROR: could not start the host MCP service and sandbox: "
            f"{exc}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
