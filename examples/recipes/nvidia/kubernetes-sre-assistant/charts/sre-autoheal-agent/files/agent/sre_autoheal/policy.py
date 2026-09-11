# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Safety policy: decides whether a proposed action may run right now.

The policy is deliberately boring and deterministic. The LLM proposes, the
policy disposes. Gates, in order:

1. global pause / observe mode
2. namespace allow/deny lists and opt-out label
3. action enabled and known; tier (with overrides)
4. rate limits (per cycle, per hour) and per-fingerprint cooldown
5. flapping protection (same fingerprint healed too often -> escalate)
6. MEDIUM tier requires an approval annotation on the subject resource
7. NEVER_AUTO is never executed
"""
from __future__ import annotations

import fnmatch
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import actions
from .models import MEDIUM, NEVER_AUTO, SAFE, Finding

log = logging.getLogger(__name__)


@dataclass
class Decision:
    allowed: bool
    outcome: str  # execute | approval_needed | escalate | observe | skip
    reason: str
    tier: str = ""


class Policy:
    def __init__(self, config: Dict[str, Any], scope: Dict[str, Any]):
        self.cfg = config
        self.scope = scope
        self._actions_this_cycle = 0
        self._action_times: List[float] = []

    # -- scope ---------------------------------------------------------------
    def namespace_in_scope(self, namespace: Optional[str]) -> bool:
        if namespace is None:
            return bool(self.scope.get("include_cluster_scope", True))
        include = self.scope.get("include_namespaces") or []
        exclude = self.scope.get("exclude_namespaces") or []
        if include and not any(fnmatch.fnmatch(namespace, pat) for pat in include):
            return False
        return not any(fnmatch.fnmatch(namespace, pat) for pat in exclude)

    def labels_allow_remediation(self, labels: Dict[str, str]) -> bool:
        opt_out = self.scope.get("opt_out_label") or ""
        if opt_out and "=" in opt_out:
            key, value = opt_out.split("=", 1)
            if labels.get(key) == value:
                return False
        opt_in = self.scope.get("opt_in_label") or ""
        if opt_in:
            if "=" in opt_in:
                key, value = opt_in.split("=", 1)
                return labels.get(key) == value
            return opt_in in labels
        return True

    # -- tiers ---------------------------------------------------------------
    def tier_for(self, action_id: str) -> str:
        override = (self.cfg.get("tier_overrides") or {}).get(action_id)
        if override in (SAFE, MEDIUM, NEVER_AUTO):
            return override
        spec = actions.spec(action_id)
        return spec.tier if spec else NEVER_AUTO

    # -- rate limiting -------------------------------------------------------
    def new_cycle(self) -> None:
        self._actions_this_cycle = 0

    def record_action(self) -> None:
        self._actions_this_cycle += 1
        self._action_times.append(time.time())

    def _hourly_count(self) -> int:
        cutoff = time.time() - 3600
        self._action_times = [t for t in self._action_times if t >= cutoff]
        return len(self._action_times)

    # -- main decision -------------------------------------------------------
    def decide(self, finding: Finding, action_id: Optional[str], subject_labels: Dict[str, str],
               subject_annotations: Dict[str, str], history: Dict[str, Any]) -> Decision:
        mode = self.cfg.get("mode", "assisted")
        if self.cfg.get("paused"):
            return Decision(False, "observe", "agent is paused by configuration")
        if not action_id or action_id == "notify_only":
            return Decision(False, "escalate", "no automatic action available for this diagnosis", tier="")
        tier = self.tier_for(action_id)
        if action_id in (self.cfg.get("disabled_actions") or []):
            return Decision(False, "escalate", f"action {action_id} is disabled by policy", tier)
        if mode == "observe":
            return Decision(False, "observe", "observe mode: reporting only", tier)
        if not self.namespace_in_scope(finding.subject.namespace):
            return Decision(False, "observe", f"namespace {finding.subject.namespace} is outside remediation scope", tier)
        if not self.labels_allow_remediation(subject_labels):
            return Decision(False, "escalate", "workload opted out of auto-heal via label", tier)
        if tier == NEVER_AUTO:
            return Decision(False, "escalate", f"action {action_id} is human-only (NEVER_AUTO)", tier)

        # Flapping: healed repeatedly in the window -> stop and escalate.
        heal_times = [t for t in history.get("heal_times", []) if t >= time.time() - int(self.cfg.get("flap_window_seconds", 21600))]
        if len(heal_times) >= int(self.cfg.get("flap_threshold", 3)):
            return Decision(False, "escalate",
                            f"flapping: healed {len(heal_times)} times in the last "
                            f"{int(self.cfg.get('flap_window_seconds', 21600)) // 3600}h; a human needs to find the root cause", tier)
        last_action = history.get("last_action_at")
        cooldown = int(self.cfg.get("cooldown_seconds", 600))
        if last_action and time.time() - last_action < cooldown:
            remaining = int(cooldown - (time.time() - last_action))
            return Decision(False, "skip", f"cooldown active for {remaining}s after the previous action", tier)
        if self._actions_this_cycle >= int(self.cfg.get("max_actions_per_cycle", 5)):
            return Decision(False, "skip", "per-cycle action budget exhausted", tier)
        if self._hourly_count() >= int(self.cfg.get("max_actions_per_hour", 20)):
            return Decision(False, "escalate", "hourly action budget exhausted", tier)

        if tier == MEDIUM:
            if mode != "assisted":
                return Decision(False, "escalate", f"{action_id} is MEDIUM tier and mode={mode} does not allow it", tier)
            annotation = self.cfg.get("approval_annotation", "sre-autoheal.nvidia.com/approve")
            approval = (subject_annotations or {}).get(annotation, "")
            if approval and approval in {"*", "all", action_id, finding.fingerprint}:
                return Decision(True, "execute", f"approved via annotation {annotation}={approval}", tier)
            return Decision(False, "approval_needed",
                            f"{action_id} is MEDIUM tier; add annotation {annotation}={action_id} "
                            f"(or ={finding.fingerprint}) on {finding.subject.short} to approve", tier)
        return Decision(True, "execute", f"{action_id} is SAFE tier", tier)
