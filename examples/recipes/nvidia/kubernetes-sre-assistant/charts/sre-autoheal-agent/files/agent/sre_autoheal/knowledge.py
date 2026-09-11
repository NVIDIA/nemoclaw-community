# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Failure-pattern knowledge base.

Patterns live in ``knowledge/failure_patterns.yaml`` (or the pre-rendered
``.json``). Each pattern documents detection signals, root causes, diagnostic
commands, remediation candidates with risk tiers, and verification. The
engine uses it to (a) rank candidate actions before asking the LLM and (b)
give the LLM grounded, pattern-specific context instead of free-form guessing.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import load_structured_file

log = logging.getLogger(__name__)

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "knowledge"


class Knowledge:
    def __init__(self, patterns: List[Dict[str, Any]], posture_checks: List[Dict[str, Any]], source: str = ""):
        self.patterns: Dict[str, Dict[str, Any]] = {p["id"]: p for p in patterns}
        self.posture_checks = posture_checks
        self.source = source

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Knowledge":
        candidates: List[Path] = []
        if path:
            candidates.append(Path(path))
        env_path = os.environ.get("SRE_AUTOHEAL_KNOWLEDGE")
        if env_path:
            candidates.append(Path(env_path))
        candidates += [DEFAULT_DIR / "failure_patterns.json", DEFAULT_DIR / "failure_patterns.yaml"]
        for candidate in candidates:
            if candidate.is_file():
                try:
                    data = load_structured_file(str(candidate))
                except RuntimeError as exc:
                    log.warning("skipping %s: %s", candidate, exc)
                    continue
                return cls(data.get("patterns", []), data.get("posture_checks", []), str(candidate))
        log.warning("no knowledge base found; running with empty pattern set")
        return cls([], [])

    def pattern(self, pattern_id: str) -> Dict[str, Any]:
        return self.patterns.get(pattern_id, {"id": pattern_id, "title": pattern_id, "remediation": []})

    def candidate_actions(self, pattern_id: str) -> List[Dict[str, Any]]:
        """Remediation entries for a pattern in documented priority order."""
        return list(self.pattern(pattern_id).get("remediation", []))

    def summary_for_llm(self, pattern_id: str) -> Dict[str, Any]:
        p = self.pattern(pattern_id)
        return {
            "id": p.get("id"),
            "title": p.get("title"),
            "root_causes": p.get("root_causes", []),
            "diagnostics": p.get("diagnostics", []),
            "remediation": p.get("remediation", []),
            "verification": p.get("verification", ""),
            "notes": p.get("notes", ""),
        }

    def render_json(self) -> str:
        return json.dumps({"patterns": list(self.patterns.values()), "posture_checks": self.posture_checks}, indent=2)
