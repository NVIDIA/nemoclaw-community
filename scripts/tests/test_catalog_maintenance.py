# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Focused tests for catalog maintenance age policy."""

from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from scripts.catalog_maintenance import (
    DEFAULT_POLICY_PATH,
    MaintenancePolicyError,
    compute_status,
    load_policy,
)


class CatalogMaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_policy()

    def _policy_file(self, value: object) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "policy.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def _policy_value(self) -> dict[str, int]:
        return json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))

    def test_default_policy_has_five_monotonic_bands(self) -> None:
        self.assertEqual(
            [band.id for band in self.policy.bands],
            [
                "current",
                "review-soon",
                "review-due",
                "review-overdue",
                "review-critical",
            ],
        )
        self.assertEqual(
            [band.minimum_days for band in self.policy.bands], [0, 30, 60, 120, 240]
        )
        styles = (Path(__file__).parents[2] / "site/styles.css").read_text(
            encoding="utf-8"
        )
        for band in self.policy.bands:
            self.assertIn(f".maintenance-tone-{band.tone}", styles)

    def test_every_age_boundary(self) -> None:
        cases = {
            0: "current",
            29: "current",
            30: "review-soon",
            59: "review-soon",
            60: "review-due",
            119: "review-due",
            120: "review-overdue",
            239: "review-overdue",
            240: "review-critical",
            900: "review-critical",
        }
        for age, expected in cases.items():
            with self.subTest(age=age):
                # Use date arithmetic so leap years cannot distort the boundary.
                today = dt.date(2026, 8, 31)
                committed = today - dt.timedelta(days=age)
                self.assertEqual(
                    compute_status(self.policy, committed_on=committed, today=today).id,
                    expected,
                )

    def test_latest_review_or_commit_controls_age(self) -> None:
        reviewed = compute_status(
            self.policy,
            committed_on="2025-01-01",
            reviewed_on="2026-08-15",
            today="2026-08-31",
        )
        committed = compute_status(
            self.policy,
            committed_on="2026-08-20",
            reviewed_on="2025-01-01",
            today="2026-08-31",
        )
        self.assertEqual(reviewed.id, "current")
        self.assertEqual(committed.id, "current")
        self.assertEqual(
            reviewed.summary,
            "Latest committed change or focused review was 16 days ago.",
        )
        self.assertEqual(
            committed.summary,
            "Latest committed change or focused review was 11 days ago.",
        )

    def test_explicit_deprecation_is_immediate_and_serializable(self) -> None:
        status = compute_status(
            self.policy,
            committed_on="2026-08-31",
            today="2026-08-31",
            lifecycle="Deprecated",
        )
        self.assertEqual(
            status.to_dict(),
            {
                "id": "deprecated",
                "label": "Deprecated",
                "summary": "Explicitly deprecated by lifecycle metadata.",
                "tone": "red",
            },
        )
        json.dumps(status.to_dict())

    def test_dates_are_strict_valid_and_not_future(self) -> None:
        for value in ("2026-8-01", "20260801", "2026-02-30", "", 20260801):
            with self.subTest(value=value):
                with self.assertRaises(MaintenancePolicyError):
                    compute_status(
                        self.policy,
                        committed_on=value,  # type: ignore[arg-type]
                        today="2026-08-31",
                    )
        with self.assertRaisesRegex(MaintenancePolicyError, "after today"):
            compute_status(self.policy, committed_on="2026-09-01", today="2026-08-31")
        with self.assertRaisesRegex(MaintenancePolicyError, "after today"):
            compute_status(
                self.policy,
                committed_on="2026-08-01",
                reviewed_on="2026-09-01",
                today="2026-08-31",
            )

    def test_policy_rejects_shape_and_threshold_errors(self) -> None:
        invalid: list[object] = [[]]
        missing_status = self._policy_value()
        del missing_status["review-soon"]
        invalid.append(missing_status)
        unknown_status = self._policy_value()
        unknown_status["unknown"] = 10
        invalid.append(unknown_status)
        non_monotonic = self._policy_value()
        non_monotonic["review-due"] = 30
        invalid.append(non_monotonic)
        boolean_days = self._policy_value()
        boolean_days["review-soon"] = True  # type: ignore[assignment]
        invalid.append(boolean_days)

        for index, value in enumerate(invalid):
            with self.subTest(index=index):
                with self.assertRaises(MaintenancePolicyError):
                    load_policy(self._policy_file(value))

    def test_policy_rejects_bad_json_and_unknown_lifecycle(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "bad.json"
        path.write_text("{", encoding="utf-8")
        with self.assertRaises(MaintenancePolicyError):
            load_policy(path)
        for lifecycle in ("Stable", "Unknown"):
            with self.subTest(lifecycle=lifecycle):
                with self.assertRaisesRegex(
                    MaintenancePolicyError, "Unsupported lifecycle"
                ):
                    compute_status(
                        self.policy,
                        committed_on="2026-08-01",
                        today="2026-08-31",
                        lifecycle=lifecycle,
                    )


if __name__ == "__main__":
    unittest.main()
