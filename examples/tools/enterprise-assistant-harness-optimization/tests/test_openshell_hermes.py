# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from harbor_agents.openshell_utils import final_answer, sandbox_name

try:
    from harbor_agents.openshell_hermes import OpenShellHermesFlywheel
except (ImportError, ModuleNotFoundError):  # Harbor/Python 3.12 are optional here.
    OpenShellHermesFlywheel = None


class OpenShellHelpersTest(unittest.TestCase):
    def test_sandbox_name_is_dns_safe_bounded_and_stable(self) -> None:
        first = sandbox_name("Source_Coverage__LONG/unsafe value" * 3, "candidate")
        second = sandbox_name("Source_Coverage__LONG/unsafe value" * 3, "candidate")
        self.assertEqual(first, second)
        self.assertLessEqual(len(first), 19)
        self.assertRegex(first, r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")

    def test_final_answer_reads_export_and_skips_tool_call_messages(self) -> None:
        session = json.dumps(
            {
                "messages": [
                    {"role": "assistant", "content": "searching", "tool_calls": [{}]},
                    {"role": "tool", "content": "result"},
                    {"role": "assistant", "content": "grounded answer"},
                ]
            }
        )
        self.assertEqual(final_answer(session), "grounded answer")


@unittest.skipIf(OpenShellHermesFlywheel is None, "Harbor is not installed")
class OpenShellArtifactFailureTest(unittest.IsolatedAsyncioTestCase):
    async def test_startup_cancellation_stops_server_and_closes_log(self):
        for stage in ("connect", "retry", "close"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                agent = OpenShellHermesFlywheel(logs_dir=Path(temp) / "logs", arm="baseline")
                failure = asyncio.CancelledError("Harbor startup deadline")
                process = SimpleNamespace(returncode=None, terminate=Mock(), kill=Mock(),
                                          wait=AsyncMock(return_value=0))
                writer = SimpleNamespace(close=Mock(), wait_closed=AsyncMock(
                    side_effect=failure if stage == "close" else None))
                connect = AsyncMock(return_value=(None, writer))
                if stage == "connect":
                    connect.side_effect = failure
                elif stage == "retry":
                    connect.side_effect = OSError("not ready")
                with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)) as spawn, \
                     patch("asyncio.open_connection", new=connect), \
                     patch("asyncio.sleep", new=AsyncMock(side_effect=failure if stage == "retry" else None)):
                    with self.assertRaises(asyncio.CancelledError) as caught:
                        await agent._start_remote_mcp(Path(temp), "test-token", 8765)
                self.assertIs(caught.exception, failure)
                process.terminate.assert_called_once()
                process.wait.assert_awaited_once()
                self.assertTrue(spawn.call_args.kwargs["stdout"].closed)

    async def test_startup_cleanup_kills_server_if_termination_times_out(self):
        with tempfile.TemporaryDirectory() as temp:
            agent = OpenShellHermesFlywheel(logs_dir=Path(temp) / "logs", arm="baseline")
            failure = asyncio.CancelledError("startup cancelled")
            process = SimpleNamespace(returncode=None, terminate=Mock(), kill=Mock(),
                                      wait=AsyncMock(side_effect=[TimeoutError(), 0]))
            with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)) as spawn, \
                 patch("asyncio.open_connection", new=AsyncMock(side_effect=failure)):
                with self.assertRaises(asyncio.CancelledError) as caught:
                    await agent._start_remote_mcp(Path(temp), "test-token", 8765)
            self.assertIs(caught.exception, failure)
            process.terminate.assert_called_once()
            process.kill.assert_called_once()
            self.assertEqual(process.wait.await_count, 2)
            self.assertTrue(spawn.call_args.kwargs["stdout"].closed)

    async def test_spawn_failure_closes_log(self):
        with tempfile.TemporaryDirectory() as temp:
            agent = OpenShellHermesFlywheel(logs_dir=Path(temp) / "logs", arm="baseline")
            failure = OSError("interpreter unavailable")
            with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=failure)) as spawn:
                with self.assertRaises(OSError) as caught:
                    await agent._start_remote_mcp(Path(temp), "test-token", 8765)
            self.assertIs(caught.exception, failure)
            self.assertTrue(spawn.call_args.kwargs["stdout"].closed)

    async def test_successful_startup_keeps_server_and_log_for_caller(self):
        with tempfile.TemporaryDirectory() as temp:
            agent = OpenShellHermesFlywheel(logs_dir=Path(temp) / "logs", arm="baseline")
            process = SimpleNamespace(returncode=None, terminate=Mock(), kill=Mock(),
                                      wait=AsyncMock(return_value=0))
            writer = SimpleNamespace(close=Mock(), wait_closed=AsyncMock())
            with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)), \
                 patch("asyncio.open_connection", new=AsyncMock(return_value=(None, writer))):
                returned, log = await agent._start_remote_mcp(Path(temp), "test-token", 8765)
            self.assertIs(returned, process)
            self.assertFalse(log.closed)
            process.terminate.assert_not_called()
            await agent._stop_remote_mcp(process, log)
            self.assertTrue(log.closed)

    async def test_harbor_cancellation_downloads_evidence_before_deleting_sandbox(self):
        with tempfile.TemporaryDirectory() as temp:
            agent = OpenShellHermesFlywheel(
                logs_dir=Path(temp) / "logs", arm="baseline",
                model_name="nvidia/nemotron-3-ultra-550b-a55b",
            )
            failure = asyncio.CancelledError("Harbor agent deadline")
            events = []

            async def command(args, **kwargs):
                if "exec" in args:
                    if args[-1] == "run.sh":
                        events.append("cancel")
                        raise failure
                    events.append("export")
                    self.assertIn("hermes sessions export", args[-1])
                if "delete" in args:
                    events.append("delete")
                return 0, "", ""

            async def download(sandbox, remote, local):
                events.append("download")
                if remote.endswith("hermes-session.jsonl"):
                    local.write_text('{"messages":[]}')
                return True

            agent._start_remote_mcp = AsyncMock(return_value=(object(), object()))
            agent._stop_remote_mcp = AsyncMock()
            agent._host_command = AsyncMock(side_effect=command)
            agent._download_optional = AsyncMock(side_effect=download)
            with self.assertRaises(asyncio.CancelledError) as caught:
                await agent.execute_openshell("Prepare a draft.", Path(temp) / "artifacts")
            self.assertIs(caught.exception, failure)
            self.assertEqual(events, ["cancel", "export", "download", "download", "download", "delete"])
            agent._stop_remote_mcp.assert_awaited_once()

    async def test_collected_artifacts_are_published_before_failure_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            agent = OpenShellHermesFlywheel(logs_dir=Path(temp) / "logs", arm="baseline")
            failure = RuntimeError("provider HTTP 429")
            captured = []

            async def execute(instruction, artifacts):
                artifacts.mkdir(parents=True)
                (artifacts / "runtime-fingerprint.json").write_text('{"arm":"baseline"}')
                raise failure

            async def publish(environment, artifacts):
                captured.append(json.loads((artifacts / "runtime-fingerprint.json").read_text()))

            agent.execute_openshell = AsyncMock(side_effect=execute)
            agent._publish_artifacts = AsyncMock(side_effect=publish)
            with self.assertRaises(RuntimeError) as caught:
                await agent.run("Prepare a draft.", object(), SimpleNamespace())
            self.assertIs(caught.exception, failure)
            self.assertEqual(captured, [{"arm": "baseline"}])
            agent._publish_artifacts.assert_awaited_once()

    async def test_publication_error_does_not_mask_the_original_run_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            agent = OpenShellHermesFlywheel(logs_dir=Path(temp) / "logs", arm="baseline")
            failure = RuntimeError("original provider failure")
            agent.execute_openshell = AsyncMock(side_effect=failure)
            agent._publish_artifacts = AsyncMock(side_effect=OSError("artifact upload failed"))
            with self.assertRaises(RuntimeError) as caught:
                await agent.run("Prepare a draft.", object(), SimpleNamespace())
            self.assertIs(caught.exception, failure)
            self.assertIn("artifact upload failed", " ".join(failure.__notes__))


@unittest.skipIf(OpenShellHermesFlywheel is None, "Harbor is not installed")
class OpenShellRuntimeTest(unittest.TestCase):
    def test_remote_mcp_host_bridge_is_allowlisted_as_external_http_service(self) -> None:
        import yaml

        policy = yaml.safe_load(
            (Path(__file__).parents[1] / "openshell" / "policy.yaml").read_text()
        )
        endpoints = policy["network_policies"]["enterprise_mcp"]["endpoints"]
        self.assertEqual(
            {(endpoint["host"], endpoint["port"]) for endpoint in endpoints},
            {("host.openshell.internal", 8765)},
        )
        self.assertTrue(all(endpoint["enforcement"] == "enforce" for endpoint in endpoints))

    def test_nvidia_provider_profile_allows_only_public_build(self) -> None:
        import yaml

        profile = yaml.safe_load(
            (Path(__file__).parents[1] / "openshell" / "provider-nvidia.yaml").read_text()
        )
        hosts = {endpoint["host"] for endpoint in profile["endpoints"]}
        self.assertEqual(profile["id"], "hermes-nvidia-build")
        self.assertEqual(
            hosts, {"integrate.api.nvidia.com"}
        )

    def test_runtime_contains_arm_mcp_relay_and_no_api_key(self) -> None:
        import yaml

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            agent = OpenShellHermesFlywheel(
                logs_dir=root / "logs",
                model_name="nvidia/nemotron-3-ultra-550b-a55b",
                arm="candidate",
            )
            self.assertEqual(agent.version(), "0.21.3")
            runtime = root / "run"
            agent._write_runtime(runtime, 'Summarize the "launch" evidence.')

            config_text = (runtime / "hermes" / "config.yaml").read_text()
            config = yaml.safe_load(config_text)
            self.assertEqual(config["agent"]["max_turns"], 60)
            self.assertEqual(config["toolsets"], ["hermes-cli"])
            self.assertEqual(config["tools"]["tool_search"]["enabled"], "off")
            enterprise = config["mcp_servers"]["enterprise-world"]
            self.assertEqual(
                enterprise["url"], "http://host.openshell.internal:8765/mcp"
            )
            self.assertTrue(enterprise["url"].startswith("http://"))
            self.assertEqual(
                enterprise["headers"]["Authorization"], "Bearer test-token"
            )
            self.assertFalse((runtime / "world.json").exists())
            self.assertEqual(
                (runtime / "instruction.txt").read_text(),
                'Summarize the "launch" evidence.',
            )
            all_text = "\n".join(
                path.read_text(errors="ignore")
                for path in runtime.rglob("*")
                if path.is_file()
            )
            self.assertNotIn("NVIDIA_API_KEY=", all_text)
            fingerprint = json.loads((runtime / "artifacts/runtime-fingerprint.json").read_text())
            self.assertEqual(fingerprint["requested_model"], "nvidia/nemotron-3-ultra-550b-a55b")
            self.assertEqual(fingerprint["arm"], "candidate")
            self.assertNotIn("test-token", json.dumps(fingerprint))
            self.assertIn("HERMES_NEMO_RELAY_PLUGINS_TOML", all_text)
            # A CLI --toolsets override becomes an MCP server-name allowlist in
            # Hermes 0.21.3. Keep arm toolsets in config so enterprise-world
            # remains discoverable.
            self.assertNotIn("--toolsets", (runtime / "run.sh").read_text())

    def test_provider_base_url_is_an_optional_runtime_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            agent = OpenShellHermesFlywheel(
                logs_dir=root / "logs",
                model_name="nvidia/nemotron-3-ultra-550b-a55b",
                arm="baseline",
                provider_base_url="https://inference.example.test/v1/",
            )
            runtime = root / "run"
            agent._write_runtime(runtime, "Find launch evidence.")
            script = (runtime / "run.sh").read_text()
            self.assertIn(
                "export NVIDIA_BASE_URL=https://inference.example.test/v1", script
            )

    def test_model_id_is_passed_to_provider_without_rewriting(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            agent = OpenShellHermesFlywheel(
                logs_dir=root / "logs",
                model_name="my-custom-nemotron",
                arm="baseline",
                provider_base_url="https://models.example.test/v1",
            )
            runtime = root / "run"
            agent._write_runtime(runtime, "Find launch evidence.")
            script = (runtime / "run.sh").read_text()
            self.assertIn("--model my-custom-nemotron", script)
            self.assertIn("export NVIDIA_BASE_URL=https://models.example.test/v1", script)

    def test_baseline_eagerly_exposes_mcp_tools(self) -> None:
        import yaml

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            agent = OpenShellHermesFlywheel(
                logs_dir=root / "logs",
                model_name="nvidia/nemotron-3-ultra-550b-a55b",
                arm="baseline",
            )
            runtime = root / "run"
            agent._write_runtime(runtime, "Find launch evidence.")
            config = yaml.safe_load(
                (runtime / "hermes" / "config.yaml").read_text()
            )
            self.assertEqual(config["tools"]["tool_search"]["enabled"], "off")

    def test_only_profile_fingerprint_changes_between_arms(self) -> None:
        import yaml

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fingerprints = []
            for arm in ("baseline", "candidate"):
                agent = OpenShellHermesFlywheel(logs_dir=root / arm / "logs",
                                               model_name="nvidia/nemotron-3-ultra-550b-a55b", arm=arm)
                runtime = root / arm / "run"
                agent._write_runtime(runtime, "Prepare a draft.")
                config = yaml.safe_load((runtime / "hermes/config.yaml").read_text())
                self.assertEqual(config["agent"], {"max_turns": 60, "api_max_retries": 6})
                fingerprints.append(json.loads((runtime / "artifacts/runtime-fingerprint.json").read_text()))
            self.assertNotEqual(fingerprints[0].pop("profile_sha256"), fingerprints[1].pop("profile_sha256"))
            for record in fingerprints:
                record.pop("arm")
            self.assertEqual(fingerprints[0], fingerprints[1])


if __name__ == "__main__":
    unittest.main()
