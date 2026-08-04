#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Adversarial tests for the NVTeam authority-registry validator."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock


VALIDATOR_PATH = Path(__file__).resolve().parents[1] / "validate_authorities.py"
SPEC = importlib.util.spec_from_file_location("validate_authorities", VALIDATOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load validator from {VALIDATOR_PATH}")
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)

TODAY = date(2026, 7, 29)


def valid_registry() -> dict[str, object]:
    """Return a minimal, independent valid registry fixture."""

    return {
        "schema_version": 1,
        "registry_kind": "base",
        "people": {
            "example-lead": {
                "display_name": "Example Lead",
                "role_snapshot": "Synthetic decision owner",
                "designation_basis": "synthetic-test-fixture",
                "verified_on": "2026-07-02",
                "review_after_days": 180,
                "identities": {
                    "display_names": ["Example Lead"],
                    "nvidia_logins": [],
                    "emails": [],
                    "slack_user_ids": [],
                    "github_logins": [],
                },
            }
        },
        "assignments": {
            "river-example-lead": {
                "person_id": "example-lead",
                "persona": "river",
                "level": "primary",
                "enabled": True,
                "scope": {
                    "products": ["nemoclaw"],
                    "topics": ["product strategy"],
                    "claim_types": [],
                },
                "rationale": "Synthetic authority signal.",
            }
        },
    }


class ValidateAuthoritiesTest(unittest.TestCase):
    def validate(
        self, registry: dict[str, object], today: date = TODAY
    ) -> tuple[list[str], list[str]]:
        return validator.validate_registry(copy.deepcopy(registry), today)

    def test_rejects_list_valued_persona_and_level_without_crashing(self) -> None:
        registry = valid_registry()
        assignment = registry["assignments"]["river-example-lead"]
        assignment["persona"] = ["river"]
        assignment["level"] = ["primary"]

        errors, warnings = self.validate(registry)

        self.assertIn(
            "$.assignments.river-example-lead.persona: expected one of "
            "akira, alex, jordan, morgan, parker, quinn, river, robin",
            errors,
        )
        self.assertIn(
            "$.assignments.river-example-lead.level: expected 'primary' or "
            "'supporting'",
            errors,
        )
        self.assertEqual([], warnings)

    def test_accepts_jordan_persona(self) -> None:
        registry = valid_registry()
        registry["assignments"]["river-example-lead"]["persona"] = "jordan"

        errors, warnings = self.validate(registry)

        self.assertEqual([], errors)
        self.assertEqual([], warnings)

    def test_rejects_boolean_schema_version(self) -> None:
        registry = valid_registry()
        registry["schema_version"] = True

        errors, _ = self.validate(registry)

        self.assertIn("$.schema_version: expected the integer 1", errors)

    def test_rejects_future_verification_date_without_overflow(self) -> None:
        registry = valid_registry()
        person = registry["people"]["example-lead"]
        person["verified_on"] = "9999-12-31"
        person["review_after_days"] = 10**1000

        errors, warnings = self.validate(registry)

        self.assertIn(
            "$.people.example-lead.verified_on: date must not be later than "
            "2026-07-29",
            errors,
        )
        self.assertEqual([], warnings)

    def test_extreme_past_date_and_review_interval_do_not_overflow(self) -> None:
        registry = valid_registry()
        person = registry["people"]["example-lead"]
        person["verified_on"] = "0001-01-01"
        person["review_after_days"] = 10**1000

        errors, warnings = self.validate(registry, date.max)

        self.assertEqual([], errors)
        self.assertEqual([], warnings)

        person["review_after_days"] = 1
        errors, warnings = self.validate(registry, date.max)
        self.assertEqual([], errors)
        self.assertEqual(1, len(warnings))
        self.assertIn("stale metadata", warnings[0])

    def test_requires_exact_calendar_date_form(self) -> None:
        for malformed_date in ("20260702", "2026-W27-4", "2026-02-30"):
            with self.subTest(malformed_date=malformed_date):
                registry = valid_registry()
                registry["people"]["example-lead"]["verified_on"] = malformed_date

                errors, _ = self.validate(registry)

                self.assertTrue(
                    any(
                        "$.people.example-lead.verified_on: expected" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_today_argument_requires_exact_calendar_date_form(self) -> None:
        for malformed_date in ("20260729", "2026-W31-3", "2026-02-30"):
            with self.subTest(malformed_date=malformed_date):
                with self.assertRaises(argparse.ArgumentTypeError):
                    validator._argument_date(malformed_date)

    def test_rejects_duplicate_json_object_keys(self) -> None:
        registry_text = """{
          "schema_version": 1,
          "registry_kind": "base",
          "people": {
            "example-lead": {},
            "example-lead": {}
          },
          "assignments": {}
        }"""
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "persona-authorities.json"
            registry_path.write_text(registry_text, encoding="utf-8")
            stdout = io.StringIO()
            argv = [
                "validate_authorities.py",
                str(registry_path),
                "--today",
                TODAY.isoformat(),
                "--json",
            ]

            with mock.patch.object(sys, "argv", argv), redirect_stdout(stdout):
                return_code = validator.main()

        result = json.loads(stdout.getvalue())
        self.assertEqual(1, return_code)
        self.assertFalse(result["valid"])
        self.assertIn(
            "$: duplicate JSON object key 'example-lead'",
            result["errors"],
        )

    def test_disabled_assignment_is_valid_but_not_exempt_from_validation(self) -> None:
        registry = valid_registry()
        assignment = registry["assignments"]["river-example-lead"]
        assignment["enabled"] = False

        errors, warnings = self.validate(registry)

        self.assertEqual([], errors)
        self.assertEqual([], warnings)

        assignment["scope"] = []
        errors, _ = self.validate(registry)
        self.assertIn(
            "$.assignments.river-example-lead.scope: expected an object",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
