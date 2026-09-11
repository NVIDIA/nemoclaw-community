# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Incident memory and self-learning.

What is learned
---------------
* ``stats[pattern][action]``  attempts / successes / failures -> smoothed success
  rate. Used to rank candidate actions, to *fast-path* proven fixes without an
  LLM call, and to *demote* actions that keep failing for a pattern.
* ``fingerprints[fp]``        per-incident history: occurrences, heal times
  (flapping detection), last action, last notification per event type.
* ``lessons``                 short free-text insights written by the LLM after
  each incident; the most relevant ones are fed back as few-shot context.
* ``incidents``               bounded log of full incident records for audit,
  digests and the ``memory export`` policy suggestions.

Backends: ``file`` (PVC / hostPath / local disk) or ``configmap`` (no storage
class needed; bounded to ~900 KiB). Secrets never enter memory.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import kube as k
from .models import Incident

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
CONFIGMAP_KEY = "memory.json"
CONFIGMAP_LIMIT = 900 * 1024


def _empty() -> Dict[str, Any]:
    return {"version": SCHEMA_VERSION, "incidents": [], "stats": {}, "fingerprints": {}, "lessons": []}


class MemoryBackend:
    def load(self) -> Dict[str, Any]:
        raise NotImplementedError

    def save(self, data: Dict[str, Any]) -> None:
        raise NotImplementedError


class FileBackend(MemoryBackend):
    def __init__(self, path: str):
        self.path = Path(path)

    def load(self) -> Dict[str, Any]:
        if not self.path.is_file():
            return _empty()
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("memory file unreadable (%s); starting fresh", exc)
            return _empty()

    def save(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, self.path)


class ConfigMapBackend(MemoryBackend):
    def __init__(self, client: k.KubeClient, namespace: str, name: str):
        self.client = client
        self.ref = k.ResourceRef("", "v1", "configmaps", namespace, name)

    def load(self) -> Dict[str, Any]:
        try:
            cm = self.client.get(self.ref)
        except k.KubeNotFound:
            return _empty()
        except k.KubeError as exc:
            log.warning("memory configmap unreadable (%s); starting fresh", exc)
            return _empty()
        raw = (cm.get("data") or {}).get(CONFIGMAP_KEY)
        if not raw:
            return _empty()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return _empty()

    def save(self, data: Dict[str, Any]) -> None:
        payload = json.dumps(data, separators=(",", ":"))
        while len(payload) > CONFIGMAP_LIMIT and data["incidents"]:
            data["incidents"] = data["incidents"][len(data["incidents"]) // 4 or 1:]
            payload = json.dumps(data, separators=(",", ":"))
        body = {"apiVersion": "v1", "kind": "ConfigMap",
                "metadata": {"name": self.ref.name, "namespace": self.ref.namespace,
                             "labels": {"app.kubernetes.io/part-of": "sre-autoheal"}},
                "data": {CONFIGMAP_KEY: payload}}
        try:
            self.client.get(self.ref)
            self.client.patch(self.ref, {"data": {CONFIGMAP_KEY: payload}}, k.MERGE_PATCH)
        except k.KubeNotFound:
            self.client.create(k.ResourceRef("", "v1", "configmaps", self.ref.namespace), body)


class NullBackend(MemoryBackend):
    def load(self) -> Dict[str, Any]:
        return _empty()

    def save(self, data: Dict[str, Any]) -> None:
        return None


class Memory:
    def __init__(self, backend: MemoryBackend, config: Dict[str, Any]):
        self.backend = backend
        self.cfg = config
        self.learning = config.get("learning") or {}
        self.data = backend.load()
        if self.data.get("version") != SCHEMA_VERSION:
            self.data = _empty()

    @classmethod
    def build(cls, config: Dict[str, Any], client: Optional[k.KubeClient] = None) -> "Memory":
        backend_name = config.get("backend", "file")
        if backend_name == "configmap" and client is not None:
            ns = config.get("configmap_namespace") or client.current_namespace()
            backend: MemoryBackend = ConfigMapBackend(client, ns, config.get("configmap_name", "sre-autoheal-memory"))
        elif backend_name == "file":
            backend = FileBackend(config.get("path", "/var/lib/sre-autoheal/memory.json"))
        else:
            backend = NullBackend()
        return cls(backend, config)

    def save(self) -> None:
        try:
            self.backend.save(self.data)
        except Exception as exc:  # noqa: BLE001 - memory must never crash the loop
            log.warning("failed to persist memory: %s", exc)

    # -- fingerprints --------------------------------------------------------
    def history(self, fingerprint: str) -> Dict[str, Any]:
        return self.data["fingerprints"].setdefault(fingerprint, {
            "count": 0, "first_seen": time.time(), "last_seen": time.time(),
            "heal_times": [], "last_action_at": None, "last_action": None,
            "last_notified": {}, "pattern_id": None, "subject": None})

    def observe(self, fingerprint: str, pattern_id: str, subject: str) -> Dict[str, Any]:
        h = self.history(fingerprint)
        h["count"] += 1
        h["last_seen"] = time.time()
        h["pattern_id"] = pattern_id
        h["subject"] = subject
        return h

    def mark_action(self, fingerprint: str, action: str) -> None:
        h = self.history(fingerprint)
        h["last_action_at"] = time.time()
        h["last_action"] = action

    def mark_healed(self, fingerprint: str) -> None:
        h = self.history(fingerprint)
        h["heal_times"] = [t for t in h["heal_times"] if t > time.time() - 7 * 86400] + [time.time()]

    def should_notify(self, fingerprint: str, event: str, dedupe_seconds: int) -> bool:
        last = self.history(fingerprint)["last_notified"].get(event)
        return not last or time.time() - last >= dedupe_seconds

    def mark_notified(self, fingerprint: str, event: str) -> None:
        self.history(fingerprint)["last_notified"][event] = time.time()

    # -- stats / learning ----------------------------------------------------
    def action_stats(self, pattern_id: str, action_id: str) -> Dict[str, Any]:
        return self.data["stats"].setdefault(pattern_id, {}).setdefault(action_id, {
            "attempts": 0, "successes": 0, "failures": 0, "last_used": None, "last_outcome": None})

    def record_outcome(self, pattern_id: str, action_id: str, success: bool) -> None:
        s = self.action_stats(pattern_id, action_id)
        s["attempts"] += 1
        s["successes" if success else "failures"] += 1
        s["last_used"] = time.time()
        s["last_outcome"] = "success" if success else "failure"

    def success_rate(self, pattern_id: str, action_id: str) -> Optional[float]:
        s = self.data["stats"].get(pattern_id, {}).get(action_id)
        if not s or not s["attempts"]:
            return None
        # Laplace smoothing keeps one lucky success from looking like certainty.
        return (s["successes"] + 1) / (s["attempts"] + 2)

    def stats_summary(self, pattern_id: str, action_id: str) -> Dict[str, Any]:
        s = self.data["stats"].get(pattern_id, {}).get(action_id)
        if not s or not s["attempts"]:
            return {}
        return {"attempts": s["attempts"], "successes": s["successes"], "failures": s["failures"],
                "success_rate": round(self.success_rate(pattern_id, action_id) or 0, 2)}

    def rank_actions(self, pattern_id: str, candidates: List[str]) -> List[str]:
        """Order candidates by learned success rate; unknowns keep documented order."""
        def key(idx_action):
            idx, action = idx_action
            rate = self.success_rate(pattern_id, action)
            return (-(rate if rate is not None else 0.5), idx)
        return [a for _, a in sorted(enumerate(candidates), key=key)]

    def raw_rate(self, pattern_id: str, action_id: str) -> Optional[float]:
        s = self.data["stats"].get(pattern_id, {}).get(action_id)
        if not s or not s["attempts"]:
            return None
        return s["successes"] / s["attempts"]

    def is_demoted(self, pattern_id: str, action_id: str) -> bool:
        if not self.learning.get("enabled", True):
            return False
        s = self.data["stats"].get(pattern_id, {}).get(action_id)
        if not s:
            return False
        return (s["attempts"] >= int(self.learning.get("demote_min_samples", 4))
                and (self.raw_rate(pattern_id, action_id) or 0) <= float(self.learning.get("demote_max_success_rate", 0.3)))

    def fast_path(self, pattern_id: str, action_id: str) -> bool:
        """True when an action is proven enough to skip the LLM."""
        if not self.learning.get("enabled", True):
            return False
        s = self.data["stats"].get(pattern_id, {}).get(action_id)
        if not s:
            return False
        return (s["attempts"] >= int(self.learning.get("fast_path_min_samples", 5))
                and (self.raw_rate(pattern_id, action_id) or 0) >= float(self.learning.get("fast_path_min_success_rate", 0.9)))

    # -- incidents & lessons -------------------------------------------------
    def add_incident(self, incident: Incident) -> None:
        record = incident.to_dict()
        # Memory lives in a ConfigMap in the release namespace and aggregates
        # incidents from every watched namespace. Log excerpts help the model
        # at diagnosis time but carry no value for learning, so they are never
        # persisted here regardless of the redact_logs setting.
        evidence = (record.get("finding") or {}).get("evidence")
        if isinstance(evidence, dict):
            evidence.pop("logs_tail", None)
        self.data["incidents"].append(record)
        limit = int(self.cfg.get("max_incidents", 2000))
        if len(self.data["incidents"]) > limit:
            self.data["incidents"] = self.data["incidents"][-limit:]

    def add_lesson(self, pattern_id: str, subject: str, lesson: str, outcome: str) -> None:
        lesson = (lesson or "").strip()
        if not lesson:
            return
        self.data["lessons"].append({"ts": time.time(), "pattern_id": pattern_id, "subject": subject,
                                     "lesson": lesson[:500], "outcome": outcome})
        self.data["lessons"] = self.data["lessons"][-500:]

    def similar_incidents(self, pattern_id: str, subject: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Few-shot context: same subject first, then same pattern, newest first."""
        limit = limit or int(self.learning.get("few_shot_examples", 5))
        rows = [i for i in reversed(self.data["incidents"]) if i["finding"]["pattern_id"] == pattern_id]
        same_subject = [i for i in rows if _subject_of(i) == subject]
        others = [i for i in rows if _subject_of(i) != subject]
        chosen = (same_subject + others)[:limit]
        out = []
        for i in chosen:
            out.append({
                "when": time.strftime("%Y-%m-%d %H:%M", time.gmtime(i["started_at"])),
                "subject": _subject_of(i),
                "root_cause": (i.get("diagnosis") or {}).get("root_cause"),
                "action": i.get("action"),
                "decision": i.get("decision"),
                "verified": i.get("verified"),
                "detail": (i.get("verify_detail") or "")[:200],
            })
        return out

    def lessons_for(self, pattern_id: str, limit: int = 5) -> List[str]:
        rows = [l for l in reversed(self.data["lessons"]) if l["pattern_id"] == pattern_id]
        return [f"[{l['outcome']}] {l['lesson']}" for l in rows[:limit]]

    # -- reporting -----------------------------------------------------------
    def summary(self) -> Dict[str, Any]:
        incidents = self.data["incidents"]
        by_decision: Dict[str, int] = {}
        for i in incidents:
            by_decision[i["decision"]] = by_decision.get(i["decision"], 0) + 1
        learned = []
        for pattern_id, actions in self.data["stats"].items():
            for action_id, s in actions.items():
                if s["attempts"]:
                    learned.append({"pattern": pattern_id, "action": action_id, **self.stats_summary(pattern_id, action_id),
                                    "fast_path": self.fast_path(pattern_id, action_id),
                                    "demoted": self.is_demoted(pattern_id, action_id)})
        learned.sort(key=lambda r: (-r["attempts"], r["pattern"]))
        return {"incidents": len(incidents), "by_decision": by_decision, "fingerprints": len(self.data["fingerprints"]),
                "lessons": len(self.data["lessons"]), "learned_actions": learned}

    def export_policy_suggestions(self) -> Dict[str, Any]:
        """Turn learned statistics into operator-reviewable policy suggestions."""
        promote, demote = [], []
        for pattern_id, actions in self.data["stats"].items():
            for action_id, s in actions.items():
                if self.fast_path(pattern_id, action_id):
                    promote.append({"pattern": pattern_id, "action": action_id, **self.stats_summary(pattern_id, action_id),
                                    "suggestion": "proven fix; consider tier override to SAFE or keep fast-path"})
                elif self.is_demoted(pattern_id, action_id):
                    demote.append({"pattern": pattern_id, "action": action_id, **self.stats_summary(pattern_id, action_id),
                                   "suggestion": "keeps failing; add to disabled_actions for this pattern or fix root cause"})
        recurring = [{"fingerprint": fp, "subject": h.get("subject"), "pattern": h.get("pattern_id"),
                      "occurrences": h["count"], "heals_7d": len(h.get("heal_times", []))}
                     for fp, h in self.data["fingerprints"].items() if len(h.get("heal_times", [])) >= 2]
        recurring.sort(key=lambda r: -r["heals_7d"])
        return {"promote": promote, "demote": demote, "recurring_incidents": recurring[:25],
                "recent_lessons": self.data["lessons"][-20:]}


def _subject_of(incident: Dict[str, Any]) -> str:
    f = incident.get("finding", {})
    subject = f.get("owner") or f.get("resource") or {}
    ns = subject.get("namespace")
    return f"{ns + '/' if ns else ''}{str(subject.get('kind', '')).lower()}/{subject.get('name', '')}"
