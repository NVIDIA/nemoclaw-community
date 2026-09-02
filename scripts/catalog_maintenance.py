#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Load catalog maintenance policy and compute deterministic age status."""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_POLICY_PATH = Path(__file__).with_name("catalog-maintenance.json")
STATUS_DETAILS = (
    ("current", "Current", "green"),
    ("review-soon", "Review soon", "light-orange"),
    ("review-due", "Review due", "orange"),
    ("review-overdue", "Review overdue", "dark-orange"),
    ("review-critical", "Review critical", "red"),
)
DEPRECATED_STATUS = ("deprecated", "Deprecated", "red")
STATUS_IDS = tuple(status_id for status_id, _label, _tone in STATUS_DETAILS)
LIFECYCLES = {"Active", "Deprecated"}
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


class MaintenancePolicyError(ValueError):
    """Raised when policy or status inputs are invalid."""


@dataclass(frozen=True)
class MaintenanceBand:
    id: str
    minimum_days: int
    label: str
    tone: str


@dataclass(frozen=True)
class MaintenancePolicy:
    bands: tuple[MaintenanceBand, ...]


@dataclass(frozen=True)
class MaintenanceStatus:
    id: str
    label: str
    summary: str
    tone: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serializable representation."""

        return asdict(self)


def load_policy(path: str | Path = DEFAULT_POLICY_PATH) -> MaintenancePolicy:
    """Load and strictly validate the five ordered maintenance age bands."""

    policy_path = Path(path)
    try:
        thresholds = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MaintenancePolicyError(
            f"Unable to load {policy_path}: {error}"
        ) from error
    if not isinstance(thresholds, dict) or set(thresholds) != set(STATUS_IDS):
        raise MaintenancePolicyError(
            "Policy must contain exactly the canonical maintenance status IDs."
        )

    bands: list[MaintenanceBand] = []
    for status_id, label, tone in STATUS_DETAILS:
        days = thresholds[status_id]
        if isinstance(days, bool) or not isinstance(days, int) or days < 0:
            raise MaintenancePolicyError(
                "Policy thresholds must be nonnegative integers."
            )
        bands.append(MaintenanceBand(status_id, days, label, tone))
    minimums = [band.minimum_days for band in bands]
    if minimums[0] != 0 or any(a >= b for a, b in zip(minimums, minimums[1:])):
        raise MaintenancePolicyError("Band thresholds must start at zero and increase.")
    return MaintenancePolicy(tuple(bands))


def _date(value: dt.date | str, field: str) -> dt.date:
    if type(value) is dt.date:
        return value
    if not isinstance(value, str) or ISO_DATE.fullmatch(value) is None:
        raise MaintenancePolicyError(f"{field} must use YYYY-MM-DD.")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as error:
        raise MaintenancePolicyError(f"{field} is not a valid date.") from error


def compute_status(
    policy: MaintenancePolicy,
    *,
    committed_on: dt.date | str,
    today: dt.date | str,
    reviewed_on: dt.date | str | None = None,
    lifecycle: str = "Active",
) -> MaintenanceStatus:
    """Compute status from the latest activity date using an injected today."""

    if lifecycle not in LIFECYCLES:
        raise MaintenancePolicyError(f"Unsupported lifecycle: {lifecycle!r}.")
    current_day = _date(today, "today")
    committed = _date(committed_on, "committed_on")
    reviewed = _date(reviewed_on, "reviewed_on") if reviewed_on is not None else None
    if committed > current_day or (reviewed is not None and reviewed > current_day):
        raise MaintenancePolicyError("Maintenance dates cannot be after today.")

    if lifecycle == "Deprecated":
        status_id, label, tone = DEPRECATED_STATUS
        return MaintenanceStatus(
            status_id,
            label,
            "Explicitly deprecated by lifecycle metadata.",
            tone,
        )

    activity = max(committed, reviewed) if reviewed is not None else committed
    age = (current_day - activity).days
    band = next(
        candidate
        for candidate in reversed(policy.bands)
        if age >= candidate.minimum_days
    )
    summary = (
        "Latest committed change or focused review was "
        f"{age} day{'s' if age != 1 else ''} ago."
    )
    return MaintenanceStatus(band.id, band.label, summary, band.tone)
