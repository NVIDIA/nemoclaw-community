# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Focused tests for executable example dependency contracts."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.example_dependencies import (
    DependencyContractError,
    _parse_contract_toml,
    load_dependency_contract,
    main,
    resolve_dependency_contract,
    resolved_environment,
)


class ExampleDependencyTests(unittest.TestCase):
    def _manifest(self, content: str) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "dependencies.toml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_nemoclaw_contract_resolves_harness_and_openshell(self) -> None:
        contract = load_dependency_contract(
            self._manifest(
                "schema_version = 1\n\n"
                "[stack]\n"
                'distribution = "nemoclaw"\n'
                'version = "v1.2.3"\n'
                'harness = "hermes"\n'
            )
        )
        stack = resolve_dependency_contract(
            contract,
            {
                "nemoclaw_stacks": {
                    "v1.2.3": {
                        "commit": "a" * 40,
                        "openshell": "0.4.0",
                        "harnesses": {"hermes": "0.21.0"},
                    }
                }
            },
        )

        self.assertEqual(stack.harness_label, "Hermes Agent")
        self.assertEqual(stack.harness_version, "0.21.0")
        self.assertEqual(stack.openshell_version, "0.4.0")
        self.assertEqual(
            resolved_environment(contract, stack),
            {
                "HERMES_VERSION": "0.21.0",
                "NEMOCLAW_AGENT": "hermes",
                "NEMOCLAW_INSTALL_REF": "a" * 40,
                "NEMOCLAW_INSTALL_TAG": "v1.2.3",
                "OPENSHELL_VERSION": "0.4.0",
            },
        )

    def test_nemoclaw_contract_rejects_duplicate_component_pins(self) -> None:
        path = self._manifest(
            "schema_version = 1\n\n"
            "[stack]\n"
            'distribution = "nemoclaw"\n'
            'version = "v1.2.3"\n'
            'harness = "openclaw"\n'
            'openshell_version = "0.4.0"\n'
        )
        with self.assertRaisesRegex(DependencyContractError, "duplicate pins"):
            load_dependency_contract(path)

    def test_portable_parser_accepts_the_supported_contract_subset(self) -> None:
        path = self._manifest(
            "schema_version = 1\n\n"
            "[stack]\n"
            'distribution = "nemoclaw"\n'
            'version = "v1.2.3"\n'
            'harness = "openclaw"\n'
        )

        parsed = _parse_contract_toml(path.read_text(encoding="utf-8"), path)

        self.assertEqual(parsed["stack"]["harness"], "openclaw")

    def test_schema_version_rejects_toml_boolean_alias(self) -> None:
        path = self._manifest(
            "schema_version = true\n\n"
            "[stack]\n"
            'distribution = "nemoclaw"\n'
            'version = "v1.2.3"\n'
            'harness = "openclaw"\n'
        )

        with self.assertRaisesRegex(DependencyContractError, "Unsupported dependency"):
            load_dependency_contract(path)

    def test_direct_contract_can_explicitly_omit_openshell(self) -> None:
        contract = load_dependency_contract(
            self._manifest(
                "schema_version = 1\n\n"
                "[stack]\n"
                'distribution = "direct"\n'
                'harness = "hermes"\n'
                'harness_version = "0.21.0"\n'
            )
        )
        stack = resolve_dependency_contract(contract, {})

        self.assertIsNone(stack.openshell_version)
        self.assertNotIn("OPENSHELL_VERSION", resolved_environment(contract, stack))

        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main([str(contract.path)]), 0)
        self.assertIn("unset ", output.getvalue())
        self.assertIn("export HERMES_VERSION=0.21.0", output.getvalue())
        self.assertNotIn("export OPENSHELL_VERSION=", output.getvalue())

    def test_direct_hermes_source_ref_and_checksum_are_one_contract(self) -> None:
        path = self._manifest(
            "schema_version = 1\n\n"
            "[stack]\n"
            'distribution = "direct"\n'
            'harness = "hermes"\n'
            'harness_version = "0.21.0"\n'
            'harness_ref = "v2026.8.31"\n'
        )

        with self.assertRaisesRegex(DependencyContractError, "must set .* together"):
            load_dependency_contract(path)

if __name__ == "__main__":
    unittest.main()
