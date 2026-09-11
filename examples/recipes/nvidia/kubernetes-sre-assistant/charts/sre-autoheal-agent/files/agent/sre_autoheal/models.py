# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Shared data types."""
from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

SAFE = "SAFE"
MEDIUM = "MEDIUM"
NEVER_AUTO = "NEVER_AUTO"
TIERS = (SAFE, MEDIUM, NEVER_AUTO)

SEVERITIES = ("critical", "high", "medium", "low", "info")


def now_ts() -> float:
    return time.time()


def iso(ts: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts if ts is not None else time.time()))


@dataclass
class Resource:
    kind: str
    name: str
    namespace: Optional[str] = None
    api_version: str = ""

    def __str__(self) -> str:
        return f"{self.kind}/{self.name}" + (f" (ns {self.namespace})" if self.namespace else "")

    @property
    def short(self) -> str:
        return f"{self.namespace + '/' if self.namespace else ''}{self.kind.lower()}/{self.name}"


@dataclass
class Finding:
    """One detected problem. Pod-level findings roll up to their controller."""

    pattern_id: str
    severity: str
    resource: Resource
    summary: str
    owner: Optional[Resource] = None
    node: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    detected_at: float = field(default_factory=now_ts)
    platform: str = "both"
    # Extra pods affected by the same owner-level problem.
    related_pods: List[str] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        subject = self.owner or self.resource
        key = "|".join([self.pattern_id, subject.namespace or "", subject.kind, subject.name])
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]

    @property
    def subject(self) -> Resource:
        return self.owner or self.resource

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["fingerprint"] = self.fingerprint
        data["detected_at_iso"] = iso(self.detected_at)
        return data


@dataclass
class ActionSpec:
    id: str
    tier: str
    description: str
    applies_to: List[str]  # subject kinds
    params_schema: Dict[str, Any] = field(default_factory=dict)
    reversible: bool = True
    rbac: List[str] = field(default_factory=list)


@dataclass
class Diagnosis:
    root_cause: str
    confidence: float
    action: Optional[str]
    params: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    human_steps: List[str] = field(default_factory=list)
    lesson: str = ""
    escalate_reason: str = ""
    source: str = "rules"  # rules | llm | learned

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ActionResult:
    ok: bool
    detail: str
    changed: List[str] = field(default_factory=list)
    dry_run: bool = False
    rollback_hint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Incident:
    """Full record of one detect -> diagnose -> act -> verify pass."""

    id: str
    fingerprint: str
    finding: Dict[str, Any]
    diagnosis: Optional[Dict[str, Any]]
    decision: str  # healed | heal_failed | escalated | approval_needed | observed | skipped
    decision_reason: str
    action: Optional[str] = None
    action_result: Optional[Dict[str, Any]] = None
    verified: Optional[bool] = None
    verify_detail: str = ""
    started_at: float = field(default_factory=now_ts)
    finished_at: Optional[float] = None
    cluster: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
