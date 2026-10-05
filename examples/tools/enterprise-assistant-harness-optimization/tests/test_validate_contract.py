# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
import json
import unittest

from scripts.validate_contract import ROOT, validate, validate_world


class ValidateContractTest(unittest.TestCase):
    def test_checked_in_contract_is_valid(self) -> None:
        world = json.loads((ROOT / "fixtures" / "world-v2.json").read_text())
        cases = json.loads((ROOT / "tests" / "fixtures" / "world-contract-cases.json").read_text())
        self.assertEqual(validate(world, cases), [])

    def test_unknown_eval_tool_is_rejected(self) -> None:
        world = json.loads((ROOT / "fixtures" / "world-v1.json").read_text())
        cases = [{"id": "bad-tool", "expectations": {"required_tools": ["invented.tool"]}}]
        self.assertIn("case bad-tool references unknown tool: invented.tool", validate(world, cases))

    def test_candidate_fixture_requires_fictional_person_identity(self) -> None:
        world = json.loads((ROOT / "fixtures" / "world-v1.json").read_text())
        world["people"][0]["email"] = "not-fictional@example.com"
        self.assertIn("person person_ava must use an example.test email", validate_world(world))
