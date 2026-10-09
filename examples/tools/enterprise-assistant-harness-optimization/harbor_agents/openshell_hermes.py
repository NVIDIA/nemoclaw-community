# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run a Harbor Hermes trial in an OpenShell sandbox.

Harbor remains the evaluation orchestrator and separate no-network verifier.
OpenShell owns the untrusted agent process, credential boundary, network policy,
and Relay capture. The fixture-backed MCP runs as a separately authenticated host
service. The adapter copies only verifier artifacts into the Harbor environment.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import shlex
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import IO, Any, override

from harbor.agents.installed.base import with_prompt_template
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from harbor_agents.hermes_flywheel import ARM_CONFIG, HermesFlywheel
from harbor_agents.openshell_utils import final_answer, sandbox_name

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = "hermes-flywheel-openshell:0.3"
DEFAULT_PROVIDER = "hermes-nvidia"
HERMES_VERSION = "0.21.3"
DEFAULT_MCP_HOST = "host.openshell.internal"
# Keep one policy-approved host endpoint. Concurrent Harbor trials queue here,
# so a second port never broadens host reachability or risks another service.
DEFAULT_MCP_PORTS = (8765,)
_REMOTE_MCP_QUEUES: dict[asyncio.AbstractEventLoop, asyncio.Queue[int]] = {}


@asynccontextmanager
async def _remote_mcp_port() -> AsyncIterator[int]:
    """Reserve one policy-approved port within the current Harbor process."""
    loop = asyncio.get_running_loop()
    queue = _REMOTE_MCP_QUEUES.get(loop)
    if queue is None:
        queue = asyncio.Queue()
        for port in DEFAULT_MCP_PORTS:
            queue.put_nowait(port)
        _REMOTE_MCP_QUEUES[loop] = queue
    port = await queue.get()
    try:
        yield port
    finally:
        queue.put_nowait(port)


class OpenShellHermesFlywheel(HermesFlywheel):
    """Selectable Hermes arm whose complete agent runtime is OpenShell."""

    def __init__(
        self,
        *args: Any,
        openshell_bin: str = "openshell",
        openshell_image: str = DEFAULT_IMAGE,
        openshell_provider: str = DEFAULT_PROVIDER,
        openshell_policy: str = str(ROOT / "openshell" / "policy.yaml"),
        mcp_python: str = str(ROOT / ".mcp-venv" / "bin" / "python"),
        mcp_host: str = DEFAULT_MCP_HOST,
        provider_base_url: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.openshell_bin = openshell_bin
        self.openshell_image = openshell_image
        self.openshell_provider = openshell_provider
        self.openshell_policy = Path(openshell_policy).expanduser().resolve()
        # Preserve virtual-environment launcher symlinks: resolving them to uv's
        # shared base interpreter drops the venv's installed MCP dependency.
        self.mcp_python = Path(os.path.abspath(Path(mcp_python).expanduser()))
        self.mcp_host = mcp_host
        self.provider_base_url = provider_base_url.rstrip("/")

    @staticmethod
    @override
    def name() -> str:
        return "openshell-hermes-flywheel"

    @override
    def version(self) -> str:
        return HERMES_VERSION

    @override
    async def setup(self, environment: BaseEnvironment) -> None:
        """Validate the host runtime; do not install an agent in the task image."""
        del environment
        if not self.openshell_policy.is_file():
            raise RuntimeError(f"OpenShell policy not found: {self.openshell_policy}")
        if not self.mcp_python.is_file():
            raise RuntimeError(f"Remote MCP Python not found: {self.mcp_python}")
        await self._host_command([self.openshell_bin, "status"], timeout=30)

    async def _host_command(
        self,
        command: list[str],
        *,
        timeout: int = 360,
        check: bool = True,
    ) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except (TimeoutError, asyncio.CancelledError) as exc:
            process.kill()
            await process.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise RuntimeError(
                f"Host command timed out after {timeout}s: {shlex.join(command)}"
            ) from None

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        log_path = self.logs_dir / "openshell.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"$ {shlex.join(command)}\n{stdout}{stderr}\n")
        if check and process.returncode != 0:
            detail = (stderr or stdout or "no output")[-4000:]
            raise RuntimeError(
                f"Host command failed ({process.returncode}): "
                f"{shlex.join(command)}\n{detail}"
            )
        return process.returncode or 0, stdout, stderr

    def _write_runtime(
        self,
        runtime_dir: Path,
        instruction: str,
        *,
        mcp_url: str | None = None,
        mcp_token: str = "test-token",
    ) -> None:
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "artifacts" / "relay").mkdir(parents=True)
        hermes_home = runtime_dir / "hermes"
        (hermes_home / "nemo-relay").mkdir(parents=True)

        # Keep the endpoint's model ID intact, regardless of its vendor prefix.
        model = self.model_name

        mcp_url = mcp_url or f"http://{self.mcp_host}:{DEFAULT_MCP_PORTS[0]}/mcp"
        config = self._build_config_yaml(model) + f'''mcp_servers:
  enterprise-world:
    url: {mcp_url}
    headers:
      Authorization: Bearer {mcp_token}
'''
        (hermes_home / "config.yaml").write_text(
            config, encoding="utf-8"
        )
        (hermes_home / "SOUL.md").write_text(
            ARM_CONFIG[self.arm]["profile"].read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        fingerprint = {
            "schema": "hermes-runtime-fingerprint-v1",
            "arm": self.arm,
            "requested_model": model,
            "provider": self.openshell_provider,
            "provider_base_url": self.provider_base_url or "https://integrate.api.nvidia.com/v1",
            "openshell_image": self.openshell_image,
            "harness_config_sha256": hashlib.sha256(
                self._build_config_yaml(model).encode()
            ).hexdigest(),
            "profile_sha256": hashlib.sha256((hermes_home / "SOUL.md").read_bytes()).hexdigest(),
            "policy_sha256": hashlib.sha256(self.openshell_policy.read_bytes()).hexdigest(),
            "fixture_sha256": hashlib.sha256((ROOT / "fixtures/world-v2.json").read_bytes()).hexdigest(),
            "mcp_implementation_sha256": {
                name: hashlib.sha256((ROOT / "src/pa_style_mock_mcp" / name).read_bytes()).hexdigest()
                for name in ("tools.py", "world.py")
            },
        }
        # Retain only selected hashes/identifiers, never config credentials or
        # the session bearer token. The host writes this before agent execution.
        (runtime_dir / "artifacts/runtime-fingerprint.json").write_text(
            json.dumps(fingerprint, indent=2) + "\n", encoding="utf-8"
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
output_directory = "/workspace/run/artifacts/relay/atof"
filename = "events.jsonl"
mode = "append"

[components.config.atif]
enabled = true
output_directory = "/workspace/run/artifacts/relay/atif"
filename_template = "trajectory-{{session_id}}.json"
agent_name = "Hermes-enterprise-world"
agent_version = "{self.arm}"
'''
        (hermes_home / "nemo-relay" / "relay-plugins.toml").write_text(
            relay_config, encoding="utf-8"
        )
        (runtime_dir / "instruction.txt").write_text(instruction, encoding="utf-8")
        model_arg = shlex.quote(model)
        script = f'''#!/usr/bin/env bash
set -uo pipefail
mkdir -p artifacts/relay
export HERMES_HOME=/workspace/run/hermes
export TERMINAL_ENV=local
export HERMES_NEMO_RELAY_PLUGINS_TOML=/workspace/run/hermes/nemo-relay/relay-plugins.toml
{f'export NVIDIA_BASE_URL={shlex.quote(self.provider_base_url)}' if self.provider_base_url else ''}
hermes --yolo chat \
  -q "$(cat /workspace/run/instruction.txt)" \
  -Q \
  --model {model_arg} \
  --provider nvidia \
  2>&1 | stdbuf -oL tee /workspace/run/artifacts/hermes.txt
hermes_rc=${{PIPESTATUS[0]}}
hermes sessions export /workspace/run/artifacts/hermes-session.jsonl \
  --source cli 2>/dev/null || true
exit "$hermes_rc"
'''
        (runtime_dir / "run.sh").write_text(script, encoding="utf-8")

    async def _start_remote_mcp(
        self, artifact_dir: Path, token: str, port: int
    ) -> tuple[asyncio.subprocess.Process, IO[bytes]]:
        """Start one authenticated host-side MCP service for this trial."""
        # An empty host-owned log is evidence of zero calls. Never accept an
        # agent-written replacement or infer zero mutations from a missing log.
        (artifact_dir / "tool-calls.jsonl").touch()
        server_log = (artifact_dir / "mcp-server.log").open("wb")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["PA_STYLE_MOCK_MCP_TOKEN"] = token
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                str(self.mcp_python),
                "-m",
                "pa_style_mock_mcp.streamable_http",
                "--host",
                "0.0.0.0",
                "--port",
                str(port),
                "--catalog",
                "extended",
                "--fixture",
                str(ROOT / "fixtures" / "world-v2.json"),
                "--call-log",
                str(artifact_dir / "tool-calls.jsonl"),
                "--require-bearer-token",
                "--issuer-url",
                f"http://{self.mcp_host}:{port}",
                "--resource-server-url",
                f"http://{self.mcp_host}:{port}/mcp",
                stdout=server_log,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            for _ in range(100):
                if process.returncode is not None:
                    detail = (artifact_dir / "mcp-server.log").read_text(
                        encoding="utf-8", errors="replace"
                    )
                    raise RuntimeError(f"Remote MCP server exited during startup:\n{detail[-4000:]}")
                try:
                    _, writer = await asyncio.open_connection("127.0.0.1", port)
                except OSError:
                    await asyncio.sleep(0.1)
                    continue
                writer.close()
                await writer.wait_closed()
                return process, server_log
            raise RuntimeError("Remote MCP server did not become ready within 10 seconds")
        except BaseException as failure:
            try:
                if process is not None:
                    await self._stop_remote_mcp(process, server_log)
            except BaseException as cleanup_error:
                failure.add_note(f"Remote MCP startup cleanup failed: {cleanup_error}")
            finally:
                server_log.close()
            raise

    @staticmethod
    async def _stop_remote_mcp(
        process: asyncio.subprocess.Process, log_handle: IO[bytes]
    ) -> None:
        try:
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except (TimeoutError, asyncio.CancelledError) as failure:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    await process.wait()
                    if isinstance(failure, asyncio.CancelledError):
                        raise
        finally:
            log_handle.close()

    async def _download_optional(
        self, sandbox: str, remote: str, local: Path
    ) -> bool:
        local.parent.mkdir(parents=True, exist_ok=True)
        return_code, _, _ = await self._host_command(
            [self.openshell_bin, "sandbox", "download", sandbox, remote, str(local)],
            timeout=120,
            check=False,
        )
        return return_code == 0

    async def _publish_artifacts(
        self, environment: BaseEnvironment, artifact_dir: Path
    ) -> None:
        await environment.exec("mkdir -p /logs/artifacts/relay", timeout_sec=10)
        for name in ("final-answer.txt", "tool-calls.jsonl", "hermes-session.jsonl", "runtime-fingerprint.json"):
            source = artifact_dir / name
            if source.is_file():
                await environment.upload_file(source, f"/logs/artifacts/{name}")
        relay_dir = artifact_dir / "relay"
        if relay_dir.is_dir():
            await environment.upload_dir(relay_dir, "/logs/artifacts/relay")

    async def execute_openshell(self, instruction: str, artifact_dir: Path) -> None:
        """Run one unscored agent turn and retain its deployment artifacts."""
        sandbox = sandbox_name(self.session_id, self.arm)
        run_error: BaseException | None = None
        artifact_dir.mkdir(parents=True, exist_ok=True)
        async with _remote_mcp_port() as mcp_port:
            token = secrets.token_urlsafe(32)
            mcp_process, mcp_log = await self._start_remote_mcp(
                artifact_dir, token, mcp_port
            )
            try:
                with tempfile.TemporaryDirectory(prefix="hermes-openshell-") as temp:
                    runtime_dir = Path(temp) / "run"
                    self._write_runtime(
                        runtime_dir,
                        instruction,
                        mcp_url=f"http://{self.mcp_host}:{mcp_port}/mcp",
                        mcp_token=token,
                    )
                    (artifact_dir / "runtime-fingerprint.json").write_bytes(
                        (runtime_dir / "artifacts/runtime-fingerprint.json").read_bytes()
                    )
                    try:
                        await self._host_command(
                            [
                                self.openshell_bin,
                                "sandbox",
                                "create",
                                "--name",
                                sandbox,
                                "--from",
                                self.openshell_image,
                                "--provider",
                                self.openshell_provider,
                                "--policy",
                                str(self.openshell_policy),
                                "--upload",
                                f"{runtime_dir}:/workspace",
                                "--no-git-ignore",
                                "--detach",
                                "--no-tty",
                            ],
                            timeout=180,
                        )
                        try:
                            await self._host_command(
                                [
                                    self.openshell_bin,
                                    "sandbox",
                                    "exec",
                                    "--name",
                                    sandbox,
                                    "--workdir",
                                    "/workspace/run",
                                    "--timeout",
                                    "360",
                                    "--no-login-shell",
                                    "--no-tty",
                                    "--",
                                    "/bin/bash",
                                    "run.sh",
                                ],
                                timeout=390,
                            )
                        except (RuntimeError, asyncio.CancelledError) as exc:
                            # Harbor can cancel before OpenShell's own timeout.
                            # Retain the partial session and Relay export while
                            # the sandbox still exists, then propagate cancellation.
                            run_error = exc
                            if isinstance(exc, asyncio.CancelledError):
                                # run.sh normally exports after Hermes exits.
                                # A Harbor cancellation can arrive first; take
                                # a read-only session snapshot before teardown.
                                try:
                                    await self._host_command(
                                        [self.openshell_bin, "sandbox", "exec", "--name", sandbox,
                                         "--workdir", "/workspace/run", "--timeout", "30",
                                         "--no-login-shell", "--no-tty", "--", "/bin/bash", "-c",
                                         "HERMES_HOME=/workspace/run/hermes hermes sessions export "
                                         "/workspace/run/artifacts/hermes-session.jsonl --source cli"],
                                        timeout=45, check=False,
                                    )
                                except Exception as collection_error:
                                    exc.add_note(f"Partial session export failed: {collection_error}")

                        for name in ("hermes-session.jsonl", "hermes.txt"):
                            await self._download_optional(
                                sandbox,
                                f"/workspace/run/artifacts/{name}",
                                artifact_dir / name,
                            )
                        await self._download_optional(
                            sandbox,
                            "/workspace/run/artifacts/relay",
                            artifact_dir / "relay",
                        )

                        session_path = artifact_dir / "hermes-session.jsonl"
                        answer = final_answer(
                            session_path.read_text(encoding="utf-8")
                            if session_path.is_file()
                            else ""
                        )
                        (artifact_dir / "final-answer.txt").write_text(
                            answer, encoding="utf-8"
                        )
                        if session_path.is_file():
                            self.logs_dir.mkdir(parents=True, exist_ok=True)
                            (self.logs_dir / "hermes-session.jsonl").write_text(
                                session_path.read_text(encoding="utf-8"),
                                encoding="utf-8",
                            )
                        if run_error is not None:
                            raise run_error
                    finally:
                        await self._host_command(
                            [self.openshell_bin, "sandbox", "delete", sandbox],
                            timeout=60,
                            check=False,
                        )
            finally:
                await self._stop_remote_mcp(mcp_process, mcp_log)

    @with_prompt_template
    @override
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        context.metadata = {
            "runtime": "openshell",
            "image": self.openshell_image,
            "provider": self.openshell_provider,
        }
        with tempfile.TemporaryDirectory(prefix="hermes-openshell-") as temp:
            artifact_dir = Path(temp) / "artifacts"
            try:
                await self.execute_openshell(instruction, artifact_dir)
            except BaseException as run_error:
                # Retain already collected diagnostics before the temporary
                # directory is removed, without replacing the original failure.
                try:
                    await self._publish_artifacts(environment, artifact_dir)
                except Exception as publication_error:
                    run_error.add_note(f"Artifact publication also failed: {publication_error}")
                raise
            else:
                await self._publish_artifacts(environment, artifact_dir)
