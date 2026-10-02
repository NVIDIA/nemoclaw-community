# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pa_style_mock_mcp import EnterpriseWorld, ToolRegistry, verify_case


class ToolRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry(EnterpriseWorld.default())

    def test_search_then_read_exposes_message_evidence(self) -> None:
        search = self.registry.call("chat.search", {"query": "launch blocker"})
        self.assertTrue(search["ok"])
        self.assertEqual(search["items"][0]["id"], "chat_launch_blocker")

        read = self.registry.call("chat.read_thread", {"thread_id": "chat_launch_blocker"})
        self.assertTrue(read["ok"])
        self.assertIn("security evidence packet", str(read["thread"]["messages"]))

    def test_fault_is_deterministic_and_retry_can_succeed(self) -> None:
        first = self.registry.call("chat.search", {"query": "network incident"})
        second = self.registry.call("chat.search", {"query": "network incident"})
        self.assertFalse(first["ok"])
        self.assertEqual(first["error"]["code"], "TEMPORARY_UNAVAILABLE")
        self.assertTrue(second["ok"])

    def test_mutation_requires_and_consumes_approval(self) -> None:
        denied = self.registry.call("actions.send_message", {"approval_token": "not-a-token"})
        self.assertEqual(denied["error"]["code"], "APPROVAL_REQUIRED")

        prepared = self.registry.call("actions.prepare_message", {"channel": "mail", "recipient": "ava.patel@example.test", "body": "Please send the packet."})
        sent = self.registry.call("actions.send_message", {"approval_token": prepared["approval_token"]})
        self.assertTrue(sent["ok"])
        self.assertEqual(len(self.registry.world.outbox), 1)
        reused = self.registry.call("actions.send_message", {"approval_token": prepared["approval_token"]})
        self.assertEqual(reused["error"]["code"], "APPROVAL_REQUIRED")

    def test_new_session_has_no_mutation_state(self) -> None:
        prepared = self.registry.call("actions.prepare_message", {"channel": "chat", "recipient": "ava.patel@example.test", "body": "hello"})
        self.registry.call("actions.send_message", {"approval_token": prepared["approval_token"]})
        fresh_registry = ToolRegistry(EnterpriseWorld.default())
        self.assertEqual(fresh_registry.world.outbox, [])

    def test_world_fixture_can_be_selected_without_changing_v1_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "world-v2.json"
            world = EnterpriseWorld.default().state
            world["world_version"] = "v2-test"
            fixture.write_text(json.dumps(world))
            with patch.dict(os.environ, {"PA_STYLE_WORLD_FIXTURE": str(fixture)}):
                self.assertEqual(EnterpriseWorld.default().state["world_version"], "v2-test")
        self.assertEqual(EnterpriseWorld.default().state["world_version"], "v1")

    def test_pagination_is_stable_and_bounded(self) -> None:
        first = self.registry.call("people.search", {"query": "example test", "page": 1, "page_size": 1})
        second = self.registry.call("people.search", {"query": "example test", "page": 2, "page_size": 1})
        self.assertTrue(first["ok"])
        self.assertEqual(first["pagination"]["total_items"], 3)
        self.assertEqual(first["pagination"]["total_pages"], 3)
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])

    def test_extended_catalog_is_fixture_backed_not_unknown_tool_padding(self) -> None:
        extended = ToolRegistry(EnterpriseWorld.default(), catalog="extended")
        names = {schema["name"] for schema in extended.schemas()}
        self.assertEqual(len(names), 15)
        self.assertIn("files.search", names)
        self.assertIn("files.read_json", names)
        self.assertTrue(extended.call("files.search", {"query": "security evidence"})["ok"])
        self.assertTrue(extended.call("support.search_tickets", {"query": "network incident"})["ok"])

    def test_call_log_persists_arguments_and_results_for_external_verifiers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            call_log = Path(directory) / "artifacts" / "tool-calls.jsonl"
            registry = ToolRegistry(
                EnterpriseWorld.default(), catalog="extended", call_log_path=call_log
            )
            registry.call("connectors.get_status", {"connector": "crm"})

            record = json.loads(call_log.read_text().strip())
            self.assertEqual(record["index"], 0)
            self.assertEqual(record["name"], "connectors.get_status")
            self.assertEqual(record["arguments"], {"connector": "crm"})
            self.assertEqual(record["result"]["status"], "needs_auth")

    def test_structured_file_requires_search_then_bounded_pointer_read(self) -> None:
        registry = ToolRegistry(EnterpriseWorld.default(), catalog="extended")
        search = registry.call("files.search", {"query": "launch evidence register"})
        self.assertTrue(search["ok"])
        result = search["items"][0]
        self.assertEqual(result["id"], "json_launch_evidence_register")
        self.assertNotIn("content", result)
        root = registry.call("files.read_json", {"file_id": result["id"]})
        self.assertEqual(root["keys"], ["evidence", "history", "release"])
        security = registry.call(
            "files.read_json", {"file_id": result["id"], "json_pointer": "/evidence/security"}
        )
        self.assertTrue(security["ok"])
        self.assertEqual({item["key"] for item in security["items"]}, {"owner", "required_artifact", "status"})

    def test_verifier_keeps_answer_trajectory_and_state_separate(self) -> None:
        result = verify_case(
            {
                "expectations": {
                    "required_tools": ["chat.search"],
                    "required_facts": ["security evidence packet"],
                    "outbox_count": 0,
                }
            },
            [{"name": "chat.search", "arguments": {"query": "launch"}}],
            "The blocker is the security evidence packet.",
            [],
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["dimensions"], {"trajectory": True, "answer": True, "state": True})

    def test_verifier_checks_expected_mutation_payload(self) -> None:
        result = verify_case(
            {
                "expectations": {
                    "outbox_count": 1,
                    "outbox_messages": [
                        {"channel": "mail", "recipient": "ava.patel@example.test", "body_contains": "packet"}
                    ],
                }
            },
            [],
            "Draft approved and sent.",
            [{"channel": "mail", "recipient": "ava.patel@example.test", "body": "Please send the budget."}],
        )
        self.assertFalse(result["passed"])
        self.assertTrue(result["dimensions"]["state"] is False)
