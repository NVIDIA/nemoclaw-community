# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Orchestration: detect -> diagnose -> decide -> act -> verify -> learn -> notify."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from . import actions, kube as k
from .config import Config
from .detect import Detector, Snapshot, redact
from .knowledge import Knowledge
from .llm import LLMClient, LLMUnavailable
from .memory import Memory
from .models import MEDIUM, Diagnosis, Finding, Incident, Resource, iso
from .notify import Message, Section, Notifier, build_message, cluster_health_line
from .policy import Decision, Policy
from .verify import subject_healthy, verify_resolved
from .storage import StorageController

log = logging.getLogger(__name__)

# Actions that change the *spec* of a controller object; GitOps/operator owners revert these.
SPEC_MUTATING = {"rollout_undo", "bump_memory_limit", "scale"}


class Engine:
    def __init__(self, config: Config, client: k.KubeClient, knowledge: Knowledge, memory: Memory,
                 notifier: Notifier, llm: Optional[LLMClient], sleep: Callable[[float], None] = time.sleep):
        self.config = config
        self.client = client
        self.knowledge = knowledge
        self.memory = memory
        self.notifier = notifier
        self.llm = llm
        self.sleep = sleep
        self.policy = Policy(config.section("policy"), config.section("scope"))
        self.policy._action_times = [t for t in memory.data.get("action_times", []) if t >= time.time() - 3600]
        self.dry_run = bool(config.get("policy.dry_run", False))
        self.executor = actions.ActionExecutor(client, dry_run=self.dry_run)
        self.cluster_summary: Dict[str, Any] = {}
        self.last_cycle: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    @classmethod
    def build(cls, config: Config, client: Optional[k.KubeClient] = None) -> "Engine":
        cluster_cfg = config.section("cluster")
        client = client or k.KubeClient.build(cluster_cfg.get("transport", "auto"), cluster_cfg.get("kubectl_binary", ""),
                                              int(cluster_cfg.get("request_timeout_seconds", 30)))
        knowledge = Knowledge.load()
        memory = Memory.build(config.section("memory"), client)
        notifier = Notifier.build(config.section("notify"), lambda env: config.secret(env) if env else None)
        llm = None
        llm_cfg = config.section("llm")
        if llm_cfg.get("enabled", True) and (llm_cfg.get("provider") or "openai") != "none":
            try:
                llm = LLMClient(llm_cfg, config.secret(llm_cfg.get("api_key_env", ""), llm_cfg.get("api_key_file", "")))
                log.info("LLM provider=%s model=%s", llm.provider, llm.model)
            except LLMUnavailable as exc:
                log.warning("LLM disabled: %s (falling back to rule-based diagnosis)", exc)
        return cls(config, client, knowledge, memory, notifier, llm)

    # ------------------------------------------------------------------
    def describe_cluster(self, snap: Snapshot) -> Dict[str, Any]:
        unhealthy = 0
        pending = 0
        for pod in snap.pods:
            phase = pod.get("status", {}).get("phase")
            if phase == "Pending":
                pending += 1
            for cs in pod.get("status", {}).get("containerStatuses", []) or []:
                if (cs.get("state") or {}).get("waiting"):
                    unhealthy += 1
                    break
        summary = {
            "platform": snap.platform,
            "version": self.client.server_version(),
            "server": getattr(self.client.transport, "api_server", "kubectl-context"),
            "identity": self.cluster_summary.get("identity") or self.client.whoami(),
            "nodes": len(snap.nodes),
            "nodes_not_ready": sum(1 for n in snap.nodes if not any(c.get("type") == "Ready" and c.get("status") == "True"
                                                                    for c in (n.get("status") or {}).get("conditions", []))),
            "pods": len(snap.pods),
            "unhealthy_pods": unhealthy,
            "pending_pods": pending,
            "degraded_operators": sum(1 for co in snap.clusteroperators if any(
                (c.get("type") == "Degraded" and c.get("status") == "True") or (c.get("type") == "Available" and c.get("status") == "False")
                for c in (co.get("status") or {}).get("conditions", []))),
            "snapshot_errors": snap.errors,
        }
        return summary

    # ------------------------------------------------------------------
    def run_cycle(self, namespaces: Optional[List[str]] = None, act: bool = True) -> Dict[str, Any]:
        started = time.time()
        self.policy.new_cycle()
        scope = self.config.section("scope")
        detection_cfg = self.config.section("detection")
        ns_filter = namespaces or (scope.get("include_namespaces") or None)
        # If only a few namespaces are included, list them directly; else list cluster-wide and filter.
        list_namespaces = ns_filter if ns_filter and not any("*" in n for n in ns_filter) and len(ns_filter) <= 20 else None
        snap = Snapshot.load(self.client, namespaces=list_namespaces, cluster_scope=bool(scope.get("include_cluster_scope", True)),
                             events_lookback=int(detection_cfg.get("events_lookback_seconds", 1800)))
        self.cluster_summary = self.describe_cluster(snap)
        detector = Detector(snap, detection_cfg, self.policy.namespace_in_scope, client=self.client, policy_cfg=self.config.section("policy"))
        findings = detector.run()
        observation_complete = not snap.errors and len(findings) < int(detection_cfg.get("max_findings_per_cycle", 50))
        if namespaces:
            findings = [f for f in findings if f.subject.namespace in namespaces or f.subject.namespace is None]
        # Only a complete observation can close a persisted retry/grace episode.
        active = {f.fingerprint for f in findings}
        if observation_complete:
            for fp, history in self.memory.data["fingerprints"].items():
                subject_ns = (history.get("subject") or "").split("/", 1)[0]
                if fp not in active and (not ns_filter or subject_ns in ns_filter) and self.policy.namespace_in_scope(subject_ns):
                    subject = history.get("episode_subject")
                    if subject and subject.get("kind") in {"Deployment", "StatefulSet", "DaemonSet", "Pod", "Node", "PersistentVolumeClaim"}:
                        prior = Finding(history.get("pattern_id") or "unknown", "medium", Resource(**subject), "prior episode")
                        if not subject_healthy(self.client, prior, snap)[0]:
                            continue
                    for key in ("transient_first_seen", "remediation_attempts", "remediation_limit", "retry_after"):
                        history.pop(key, None)
        self.cluster_summary["open_findings"] = sum(1 for f in findings if f.severity != "info")
        incidents: List[Incident] = []
        posture = [f for f in findings if f.pattern_id.startswith("posture-")]
        for finding in findings:
            if finding.pattern_id.startswith("posture-"):
                continue
            try:
                incidents.append(self.handle_finding(finding, snap, act=act))
            except Exception as exc:  # noqa: BLE001 - one incident must not kill the loop
                log.exception("unhandled error while handling %s: %s", finding.subject.short, exc)
        if posture and self.notifier.wants("posture"):
            self._notify_posture(posture)
        storage_records = []
        if self.config.get("storage.enabled", False):
            try:
                storage_namespaces = [ns for ns in (list_namespaces or []) if self.policy.namespace_in_scope(ns)]
                writes_allowed = (not snap.errors and not self.dry_run
                                  and not self.config.get("policy.paused", False)
                                  and self.config.get("policy.mode") in {"safe", "assisted"})
                storage_records = StorageController(
                    self.config.section("storage"), self.client, self.memory,
                    self.notifier, storage_namespaces, policy=self.policy,
                ).run_cycle(act=act, writes_allowed=writes_allowed)
                self.memory.data.pop("storage_collector_error", None)
            except Exception as exc:
                log.warning("storage controller withheld action: %s", type(exc).__name__)
                storage_records = [{"outcome": "controller_error", "detail": type(exc).__name__}]
                self._notify_storage_collector_error(type(exc).__name__)
        self.memory.save()
        self.last_cycle = {
            "started_at": iso(started), "duration_seconds": round(time.time() - started, 1),
            "cluster": self.cluster_summary, "findings": len(findings),
            "incidents": [i.to_dict() for i in incidents], "posture_findings": len(posture),
            "storage": storage_records,
        }
        return self.last_cycle

    def _notify_storage_collector_error(self, error_type):
        """Three failed observations before escalation; retry delivery, not resize."""
        state = self.memory.data.setdefault("storage_collector_error", {"count": 0, "sinks": {}})
        state["count"] += 1
        if state["count"] < 3 or not self.notifier.wants("escalated"):
            return
        message = Message("escalated", "Storage monitoring unavailable - human review needed", [
            Section("text", "Observed evidence", f"Three consecutive storage collection cycles failed ({error_type}). Storage recovery cannot be verified; no new expansion was authorized by this failed collection."),
            Section("text", "Admin checks", "Check agent logs, scoped namespace configuration, Kubernetes read permissions, metrics endpoint reachability and authentication. Inspect exact PVC capacity and resize conditions before retrying. This is a collector failure, not a confirmed storage root cause.")
        ], "high", {})
        now = time.time()
        for sink in self.notifier.sinks:
            status = state["sinks"].setdefault(sink.name, {"ok": False, "attempts": 0, "last": 0})
            if status["ok"] or status["attempts"] >= 3 or (status["attempts"] and now - status["last"] < 60):
                continue
            status.update(attempts=status["attempts"] + 1, last=now)
            try:
                status["ok"] = bool(sink.send(message))
            except Exception:
                status["ok"] = False

    # ------------------------------------------------------------------
    def handle_finding(self, finding: Finding, snap: Snapshot, act: bool = True) -> Incident:
        fp = finding.fingerprint
        history = self.memory.observe(fp, finding.pattern_id, finding.subject.short)
        history["episode_subject"] = {"kind": finding.subject.kind, "name": finding.subject.name, "namespace": finding.subject.namespace}
        incident = Incident(id=uuid.uuid4().hex[:12], fingerprint=fp, finding=finding.to_dict(), diagnosis=None,
                            decision="observed", decision_reason="", cluster=self.cluster_summary.get("server", ""))
        labels, annotations = snap.workload_labels(finding.subject)

        if finding.pattern_id in {"service-no-endpoints", "pod-config-error"}:
            transient = finding.pattern_id == "service-no-endpoints" or any(
                term in str(finding.evidence.get("cause") or finding.summary).lower()
                for term in ("deadline exceeded", "timeout", "rst_stream"))
            if transient:
                first = history.setdefault("transient_first_seen", time.time())
                grace = max(0, int(self.config.get("detection.transient_grace_seconds", 300)))
                if time.time() - first < grace:
                    incident.decision_reason = "transient recovery grace window; re-observe next cycle before diagnosis or action"
                    incident.finished_at = time.time()
                    self.memory.add_incident(incident)
                    self.memory.save()
                    return incident

        diagnosis = self.diagnose(finding, history)
        action_id = diagnosis.action

        # GitOps / operator ownership: spec mutations get reverted -> route to humans.
        managed_by = (finding.evidence.get("management") or {}).get("managed_by")
        if action_id in SPEC_MUTATING and managed_by in {"argocd", "flux", "operator"}:
            diagnosis.human_steps = [f"Workload is {managed_by}-managed: apply the change ({action_id} {json.dumps(diagnosis.params)}) "
                                     f"in Git / the owning CR instead of patching the live object."] + diagnosis.human_steps
            decision = Decision(False, "escalate", f"{action_id} would be reverted by {managed_by}; change must go through the owner", self.policy.tier_for(action_id))
        else:
            decision = self.policy.decide(finding, action_id, labels, annotations, history)
        if snap.errors and decision.allowed:
            decision = Decision(False, "observe", "incomplete cluster evidence; writes withheld", decision.tier)
        attempts = history.get("remediation_attempts", 0)
        if action_id and attempts >= history.get("remediation_limit", 3):
            decision = Decision(False, "heal_failed", "remediation attempt budget exhausted for this unresolved episode", decision.tier)
        elif history.get("retry_after", 0) > time.time() and decision.allowed:
            decision = Decision(False, "skip", "retry backoff active; re-observe next cycle", decision.tier)
        if not act and decision.outcome == "execute":
            decision = Decision(False, "observe", "detection-only run (act=False)", decision.tier)

        incident.decision_reason = decision.reason
        incident.action = action_id if action_id and action_id != "notify_only" else None
        incident.diagnosis = diagnosis.to_dict()

        if decision.outcome == "execute" and action_id:
            self._execute_and_verify(incident, finding, diagnosis, decision)
        elif decision.outcome == "approval_needed":
            incident.decision = "approval_needed"
        elif decision.outcome == "skip":
            incident.decision = "skipped"
        elif decision.outcome == "observe":
            incident.decision = "observed"
        elif decision.outcome == "heal_failed":
            incident.decision = "heal_failed"
        else:
            incident.decision = "escalated"

        incident.finished_at = time.time()
        self.memory.add_incident(incident)
        if diagnosis.lesson:
            self.memory.add_lesson(finding.pattern_id, finding.subject.short, diagnosis.lesson, incident.decision)
        self._notify(incident, finding, decision, history)
        return incident

    # ------------------------------------------------------------------
    def diagnose(self, finding: Finding, history: Dict[str, Any]) -> Diagnosis:
        pattern = self.knowledge.pattern(finding.pattern_id)
        candidates = self.knowledge.candidate_actions(finding.pattern_id)
        subject_kind = finding.subject.kind
        allowed: List[str] = []
        for c in candidates:
            spec = actions.spec(c["action"])
            if spec and ("*" in spec.applies_to or subject_kind in spec.applies_to):
                allowed.append(c["action"])
        if "notify_only" not in allowed:
            allowed.append("notify_only")
        ranked = self.memory.rank_actions(finding.pattern_id, allowed)
        demoted = [a for a in ranked if self.memory.is_demoted(finding.pattern_id, a)]
        usable = [a for a in ranked if a not in demoted] or ["notify_only"]

        # Rule-based default: first documented (learned-ranked) candidate.
        default_action = usable[0]
        rule_diag = Diagnosis(
            root_cause=f"{pattern.get('title', finding.pattern_id)}: {finding.evidence.get('cause') or finding.summary}",
            confidence=0.5 if default_action != "notify_only" else 0.3,
            action=default_action if default_action != "notify_only" else None,
            rationale="rule-based default from the knowledge base" + (f"; ranked by learned success rates" if self.memory.data["stats"].get(finding.pattern_id) else ""),
            human_steps=list(pattern.get("diagnostics", []))[:6],
            source="rules",
        )
        if default_action == "bump_memory_limit":
            rule_diag.params = {"container": finding.evidence.get("container"), "factor": 1.5}

        # Learned fast path: proven action -> skip the LLM.
        if default_action != "notify_only" and self.memory.fast_path(finding.pattern_id, default_action):
            rule_diag.source = "learned"
            rule_diag.confidence = self.memory.success_rate(finding.pattern_id, default_action) or 0.9
            rule_diag.rationale = f"learned fast path: {default_action} resolved {finding.pattern_id} " \
                                  f"{self.memory.stats_summary(finding.pattern_id, default_action)}"
            return rule_diag

        if self.llm is None:
            return rule_diag

        payload = {
            "cluster": {k_: v for k_, v in self.cluster_summary.items() if k_ not in {"snapshot_errors"}},
            "finding": self._finding_for_llm(finding),
            "pattern": self.knowledge.summary_for_llm(finding.pattern_id),
            "allowed_actions": actions.catalog_for_llm(subject_kind, lambda a: self.memory.stats_summary(finding.pattern_id, a)),
            "allowed_action_ids": usable,
            "demoted_actions": demoted,
            "incident_history": {"occurrences": history.get("count"), "heals_in_window": len(history.get("heal_times", [])),
                                 "last_action": history.get("last_action"),
                                 "last_action_at": iso(history["last_action_at"]) if history.get("last_action_at") else None},
            "similar_incidents": self.memory.similar_incidents(finding.pattern_id, finding.subject.short),
            "lessons": self.memory.lessons_for(finding.pattern_id),
            "policy": {"mode": self.config.get("policy.mode"), "environment": self.config.get("notify.environment"),
                       "tiers": {a: self.policy.tier_for(a) for a in usable}},
        }
        try:
            diag = self.llm.diagnose(payload, usable)
        except LLMUnavailable as exc:
            log.warning("LLM diagnosis unavailable (%s); using rules", exc)
            rule_diag.rationale += f"; LLM unavailable: {str(exc)[:120]}"
            return rule_diag
        # Agreement with a rule is not evidence that a low-confidence mutation is safe.
        min_conf = float(self.config.get("policy.min_llm_confidence", 0.6))
        if diag.action and diag.confidence < min_conf:
            diag.escalate_reason = (diag.escalate_reason or "") + f" low confidence ({diag.confidence:.2f}) for action {diag.action}"
            diag.action = None
        if diag.action == "bump_memory_limit" and "container" not in diag.params and finding.evidence.get("container"):
            diag.params["container"] = finding.evidence["container"]
        if not diag.human_steps:
            diag.human_steps = rule_diag.human_steps
        return diag

    def _finding_for_llm(self, finding: Finding) -> Dict[str, Any]:
        data = finding.to_dict()
        evidence = dict(data.get("evidence") or {})
        if self.config.get("llm.redact_logs", False):
            evidence.pop("logs_tail", None)
        elif evidence.get("logs_tail"):
            evidence["logs_tail"] = redact(str(evidence["logs_tail"]))[-int(self.config.get("llm.max_evidence_chars", 12000)) // 3:]
        data["evidence"] = evidence
        return data

    # ------------------------------------------------------------------
    def _execute_and_verify(self, incident: Incident, finding: Finding, diagnosis: Diagnosis, decision: Decision) -> None:
        action_id = diagnosis.action or ""
        # Server-side dry run first for approval-tier actions (catches RBAC/validation before the real call).
        if decision.tier == MEDIUM and not self.dry_run:
            probe = actions.ActionExecutor(self.client, dry_run=True).execute(action_id, finding, diagnosis.params)
            if not probe.ok:
                incident.decision = "heal_failed"
                incident.decision_reason = f"pre-flight failed: {probe.detail}"
                incident.action_result = probe.to_dict()
                self.memory.record_outcome(finding.pattern_id, action_id, False)
                return
        history = self.memory.history(finding.fingerprint)
        # Repeating an action is distinct from retrying the model. Only ordinary
        # Deployment pod restarts are retryable; never repeat quorum/StatefulSet,
        # force deletion, node operations or spec mutations automatically.
        retry_safe = action_id == "restart_pod" and finding.subject.kind == "Deployment"
        limit = max(1, min(3, int(self.config.get("policy.max_heal_attempts", 3)))) if retry_safe else 1
        if not self.dry_run:
            history["remediation_limit"] = limit
            history["remediation_attempts"] = history.get("remediation_attempts", 0) + 1
            self.policy.record_action()
            self.memory.data["action_times"] = list(self.policy._action_times)
            self.memory.mark_action(finding.fingerprint, action_id)
            # Reserve the attempt durably BEFORE a write; restart must not reset
            # retry or hourly budgets. Persistence failure is fail-closed.
            try:
                self.memory.backend.save(self.memory.data)
            except Exception:
                incident.decision = "heal_failed"
                incident.decision_reason = "cannot persist remediation budget; no action executed"
                return
        result = self.executor.execute(action_id, finding, diagnosis.params)
        incident.action_result = result.to_dict()
        incident.action_result["attempt"] = history.get("remediation_attempts", 0)
        incident.action_result["max_attempts"] = limit
        if not result.ok:
            # An ambiguous or rejected write must not be blindly replayed.
            history["remediation_limit"] = history.get("remediation_attempts", 1)
            incident.decision = "heal_failed"
            incident.decision_reason = f"action failed: {result.detail}"
            self.memory.record_outcome(finding.pattern_id, action_id, False)
            return
        if self.dry_run or result.dry_run:
            incident.decision = "observed"
            incident.decision_reason = f"dry-run: {result.detail}"
            incident.verified = None
            return
        verify_cfg = self.config.section("verify")
        ok, detail = verify_resolved(self.client, finding, verify_cfg, self.config.section("detection"), self.policy.namespace_in_scope,
                                     timeout=int(verify_cfg.get("timeout_seconds", 300)), poll=int(verify_cfg.get("poll_seconds", 15)),
                                     sleep=self.sleep)
        incident.verified = ok
        incident.verify_detail = detail
        self.memory.record_outcome(finding.pattern_id, action_id, ok)
        if ok:
            incident.decision = "healed"
            incident.decision_reason = f"{action_id} executed and verified"
            self.memory.mark_healed(finding.fingerprint)
            history.pop("retry_after", None)
        else:
            if retry_safe and history.get("remediation_attempts", 0) < limit:
                history["retry_after"] = time.time() + max(0, int(self.config.get("policy.retry_delay_seconds", 60)))
                incident.decision = "retry_pending"
                incident.decision_reason = f"attempt {history['remediation_attempts']}/{limit} not verified; fresh detection and all policy gates required next cycle: {detail}"
            else:
                incident.decision = "heal_failed"
                incident.decision_reason = f"{action_id} executed but the symptom persists: {detail}"

    # ------------------------------------------------------------------
    def _notify(self, incident: Incident, finding: Finding, decision: Decision, history: Dict[str, Any]) -> None:
        event = incident.decision
        if event in {"skipped", "retry_pending"}:
            return
        if event == "observed" and not (self.dry_run and self.notifier.wants("observed")):
            if not self.notifier.wants("observed"):
                return
        if not self.notifier.wants(event):
            return
        dedupe = int(self.config.get("notify.dedupe_seconds", 21600))
        if event != "healed" and not self.memory.should_notify(finding.fingerprint, event, dedupe):
            return
        context = {
            "environment": self.config.get("notify.environment"),
            "cluster_name": self.config.get("notify.cluster_name"),
            "runbook_base_url": self.config.get("notify.runbook_base_url"),
            "cluster_health": cluster_health_line(self.cluster_summary),
            "history_note": f"seen {history.get('count')}x; healed {len(history.get('heal_times', []))}x in the last 7 days"
                            + (f"; last action {history.get('last_action')} at {iso(history['last_action_at'])}" if history.get("last_action_at") else ""),
        }
        if event == "approval_needed" and incident.action:
            annotation = self.config.get("policy.approval_annotation", "sre-autoheal.nvidia.com/approve")
            subject = finding.subject
            ns_flag = f" -n {subject.namespace}" if subject.namespace else ""
            context["approval_command"] = f"kubectl annotate {subject.kind.lower()}/{subject.name}{ns_flag} {annotation}={incident.action} --overwrite"
        message = build_message(incident, event, context, self.cluster_summary)
        results = self.notifier.send(message)
        if any(ok for name, ok in results.items() if name != "stdout"):
            self.memory.mark_notified(finding.fingerprint, event)
        log.info("notified %s for %s via %s", event, finding.subject.short, results)

    def _notify_posture(self, posture: List[Finding]) -> None:
        fake = Incident(id=uuid.uuid4().hex[:12], fingerprint="posture", finding={
            "pattern_id": "posture-workload-hardening", "severity": "info", "summary": f"{len(posture)} workloads with hardening gaps",
            "resource": {"kind": "Cluster", "name": self.cluster_summary.get("server", "cluster"), "namespace": None},
            "owner": None, "detected_at_iso": iso(), "evidence": {}}, diagnosis={"root_cause": "preventive audit", "human_steps": [
                f"{f.subject.short}: " + "; ".join(f.evidence.get("issues", [])[:3]) for f in posture[:15]], "source": "rules"},
            decision="observed", decision_reason="posture audit (never acted on)")
        if self.memory.should_notify("posture", "posture", int(self.config.get("notify.posture_dedupe_seconds", 86400))):
            self.notifier.send(build_message(fake, "posture", {"environment": self.config.get("notify.environment")}, self.cluster_summary))
            self.memory.mark_notified("posture", "posture")

    # ------------------------------------------------------------------
    def preflight(self) -> Dict[str, Any]:
        """Check identity, platform, LLM reachability and the RBAC each action needs."""
        report: Dict[str, Any] = {"identity": self.client.whoami(), "platform": self.client.platform(),
                                  "version": self.client.server_version(), "transport": self.client.transport.name,
                                  "knowledge": self.knowledge.source, "patterns": len(self.knowledge.patterns),
                                  "llm": {"enabled": self.llm is not None, "provider": getattr(self.llm, "provider", None),
                                          "model": getattr(self.llm, "model", None)},
                                  "memory_backend": type(self.memory.backend).__name__, "mode": self.config.get("policy.mode"),
                                  "dry_run": self.dry_run}
        self.cluster_summary["identity"] = report["identity"]
        probe_ns = (self.config.get("scope.include_namespaces") or [self.client.current_namespace()])[0]
        checks = {
            "read pods": ("list", "pods", "", probe_ns, ""),
            "read pod logs": ("get", "pods", "", probe_ns, "log"),
            "read events": ("list", "events", "", probe_ns, ""),
            "read deployments": ("list", "deployments", "apps", probe_ns, ""),
            "read nodes": ("list", "nodes", "", "", ""),
            "restart_pod / delete_evicted_pods (delete pods)": ("delete", "pods", "", probe_ns, ""),
            "rollout_restart / rollout_undo / bump_memory_limit (patch deployments)": ("patch", "deployments", "apps", probe_ns, ""),
            "scale (patch deployments/scale)": ("patch", "deployments", "apps", probe_ns, "scale"),
            "cordon_node (patch nodes)": ("patch", "nodes", "", "", ""),
        }
        if self.config.get("memory.backend") == "configmap":
            checks["memory configmap (patch named configmap)"] = (
                "patch", "configmaps", "", self.config.get("memory.configmap_namespace") or self.client.current_namespace(), "",
                self.config.get("memory.configmap_name", "sre-autoheal-memory"))
        rbac = {}
        for label, attrs in checks.items():
            verb, resource, group, ns, sub = attrs[:5]
            name = attrs[5] if len(attrs) > 5 else ""
            rbac[label] = self.client.can_i(verb, resource, group, ns, sub, name)
        report["rbac"] = rbac
        if self.llm is not None:
            try:
                sample = self.llm.complete("Reply with the single word OK.", "healthcheck")
                report["llm"]["reachable"] = "ok" in sample.lower()
            except LLMUnavailable as exc:
                report["llm"]["reachable"] = False
                report["llm"]["error"] = str(exc)[:200]
        return report

    # ------------------------------------------------------------------
    def run_forever(self, interval: Optional[int] = None) -> None:
        interval = interval or int(self.config.get("detection.interval_seconds", 60))
        log.info("starting watch loop every %ss (mode=%s dry_run=%s)", interval, self.config.get("policy.mode"), self.dry_run)
        while True:
            started = time.time()
            try:
                result = self.run_cycle()
                log.info("cycle done in %ss: %s findings, %s incidents", result["duration_seconds"], result["findings"], len(result["incidents"]))
            except k.KubeError as exc:
                log.error("cycle failed: %s", exc)
            except Exception as exc:  # noqa: BLE001
                log.exception("cycle crashed: %s", exc)
            elapsed = time.time() - started
            self.sleep(max(5.0, interval - elapsed))
