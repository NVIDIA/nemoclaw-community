"""Immutable fixture loading and isolated state for each agent session."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any


class EnterpriseWorld:
    """A session-local copy of a frozen enterprise fixture world."""

    def __init__(self, fixture: dict[str, Any]) -> None:
        self._fixture = copy.deepcopy(fixture)
        self.state = copy.deepcopy(fixture)
        self._fault_counts: dict[str, int] = {}
        self.approvals: dict[str, dict[str, Any]] = {}
        self.outbox: list[dict[str, Any]] = []

    @classmethod
    def from_path(cls, path: str | Path) -> EnterpriseWorld:
        return cls(json.loads(Path(path).read_text()))

    @classmethod
    def default(cls, fixture_path: str | Path | None = None) -> EnterpriseWorld:
        fixture_path = Path(
            fixture_path
            or os.environ.get("PA_STYLE_WORLD_FIXTURE")
            or Path(__file__).parents[2] / "fixtures" / "world-v1.json"
        )
        return cls.from_path(fixture_path)

    def connector_status(self, connector: str) -> dict[str, str]:
        status = self.state["connector_status"].get(connector)
        if status is None:
            return {"status": "unknown", "connector": connector}
        return {"connector": connector, **status}

    def consume_fault(self, tool: str, arguments: dict[str, Any]) -> dict[str, str] | None:
        """Return a configured deterministic fault once per matching session."""
        for fault in self.state.get("faults", []):
            if fault["tool"] != tool or any(arguments.get(k) != v for k, v in fault["when"].items()):
                continue
            key = f"{tool}:{json.dumps(fault['when'], sort_keys=True)}"
            count = self._fault_counts.get(key, 0)
            if count < fault.get("max_occurrences_per_session", 1):
                self._fault_counts[key] = count + 1
                return fault["error"]
        return None
