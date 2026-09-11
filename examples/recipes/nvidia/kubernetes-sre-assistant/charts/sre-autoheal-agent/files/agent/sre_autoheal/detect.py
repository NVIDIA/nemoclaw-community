# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Cluster snapshot and rule-based detectors.

Detection is deterministic and cheap: it only reads status fields and recent
events, then rolls pod-level symptoms up to the owning controller so one
Deployment with ten crash-looping replicas produces one incident, not ten.
The LLM is consulted afterwards, per finding, with this evidence attached.
"""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from . import kube as k
from .models import Finding, Resource

log = logging.getLogger(__name__)

IMAGE_PULL_REASONS = {"ImagePullBackOff", "ErrImagePull", "InvalidImageName", "ErrImageNeverPull", "RegistryUnavailable"}
CONFIG_REASONS = {"CreateContainerConfigError", "CreateContainerError"}
RUN_REASONS = {"RunContainerError", "ContainerCannotRun", "StartError"}
EVICTED_REASONS = {"Evicted", "Terminated", "NodeAffinity", "Shutdown", "UnexpectedAdmissionError", "NodeLost"}


def parse_time(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def age_seconds(value: Optional[str], now: Optional[float] = None) -> float:
    ts = parse_time(value)
    if ts is None:
        return 0.0
    return max(0.0, (now or time.time()) - ts)


def condition(obj: Dict[str, Any], ctype: str) -> Dict[str, Any]:
    for cond in (obj.get("status") or {}).get("conditions", []) or []:
        if cond.get("type") == ctype:
            return cond
    return {}


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------
@dataclass
class Snapshot:
    platform: str
    pods: List[Dict[str, Any]] = field(default_factory=list)
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    deployments: List[Dict[str, Any]] = field(default_factory=list)
    replicasets: List[Dict[str, Any]] = field(default_factory=list)
    statefulsets: List[Dict[str, Any]] = field(default_factory=list)
    daemonsets: List[Dict[str, Any]] = field(default_factory=list)
    jobs: List[Dict[str, Any]] = field(default_factory=list)
    pvcs: List[Dict[str, Any]] = field(default_factory=list)
    services: List[Dict[str, Any]] = field(default_factory=list)
    endpoints: List[Dict[str, Any]] = field(default_factory=list)
    hpas: List[Dict[str, Any]] = field(default_factory=list)
    pdbs: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    clusteroperators: List[Dict[str, Any]] = field(default_factory=list)
    machineconfigpools: List[Dict[str, Any]] = field(default_factory=list)
    csrs: List[Dict[str, Any]] = field(default_factory=list)
    taken_at: float = field(default_factory=time.time)
    errors: List[str] = field(default_factory=list)
    _rs_owner: Dict[Tuple[str, str], Resource] = field(default_factory=dict)
    _events_index: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = field(default_factory=dict)

    @classmethod
    def load(cls, client: k.KubeClient, namespaces: Optional[List[str]] = None, cluster_scope: bool = True,
             events_lookback: int = 1800) -> "Snapshot":
        snap = cls(platform=client.platform())
        ns_list: List[Optional[str]] = list(namespaces) if namespaces else [None]

        def fetch(attr: str, ref: k.ResourceRef, namespaced: bool = True, optional: bool = False) -> None:
            items: List[Dict[str, Any]] = []
            targets = ns_list if namespaced else [None]
            for ns in targets:
                r = k.ResourceRef(ref.group, ref.version, ref.resource, ns if namespaced else None)
                try:
                    items.extend(client.list(r))
                except k.KubeError as exc:
                    if not optional:
                        snap.errors.append(f"{ref.resource}: {str(exc)[:160]}")
            setattr(snap, attr, items)

        fetch("pods", k.PODS)
        fetch("deployments", k.DEPLOYMENTS)
        fetch("replicasets", k.REPLICASETS)
        fetch("statefulsets", k.STATEFULSETS)
        fetch("daemonsets", k.DAEMONSETS)
        fetch("jobs", k.JOBS)
        fetch("pvcs", k.PVCS)
        fetch("services", k.SERVICES)
        fetch("endpoints", k.ENDPOINTS, optional=True)
        fetch("hpas", k.HPAS, optional=True)
        fetch("pdbs", k.PDBS, optional=True)
        fetch("events", k.EVENTS)
        if cluster_scope:
            fetch("nodes", k.NODES, namespaced=False)
            fetch("csrs", k.CSRS, namespaced=False, optional=True)
            if snap.platform == "openshift":
                fetch("clusteroperators", k.CLUSTEROPERATORS, namespaced=False, optional=True)
                fetch("machineconfigpools", k.MACHINECONFIGPOOLS, namespaced=False, optional=True)
        cutoff = time.time() - events_lookback
        snap.events = [e for e in snap.events if (parse_time(e.get("lastTimestamp") or e.get("eventTime")
                                                             or (e.get("series") or {}).get("lastObservedTime")
                                                             or e.get("firstTimestamp")) or 0) >= cutoff]
        snap._index()
        return snap

    def _index(self) -> None:
        for rs in self.replicasets:
            meta = rs.get("metadata", {})
            for owner in meta.get("ownerReferences", []) or []:
                if owner.get("controller"):
                    self._rs_owner[(meta.get("namespace", ""), meta.get("name", ""))] = Resource(
                        owner.get("kind", ""), owner.get("name", ""), meta.get("namespace"), owner.get("apiVersion", ""))
        idx: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
        for ev in self.events:
            obj = ev.get("involvedObject") or {}
            idx[(obj.get("namespace") or "", obj.get("kind") or "", obj.get("name") or "")].append(ev)
        self._events_index = idx

    # -- helpers -------------------------------------------------------------
    def owner_of(self, obj: Dict[str, Any]) -> Optional[Resource]:
        meta = obj.get("metadata", {})
        ns = meta.get("namespace")
        for owner in meta.get("ownerReferences", []) or []:
            if not owner.get("controller"):
                continue
            kind, name = owner.get("kind", ""), owner.get("name", "")
            if kind == "ReplicaSet":
                parent = self._rs_owner.get((ns or "", name))
                return parent or Resource("ReplicaSet", name, ns, owner.get("apiVersion", ""))
            return Resource(kind, name, ns, owner.get("apiVersion", ""))
        return None

    def events_for(self, namespace: str, kind: str, name: str, limit: int = 8) -> List[Dict[str, Any]]:
        rows = self._events_index.get((namespace or "", kind, name), [])
        rows = sorted(rows, key=lambda e: parse_time(e.get("lastTimestamp") or e.get("eventTime") or e.get("firstTimestamp")) or 0,
                      reverse=True)
        out = []
        for ev in rows[:limit]:
            out.append({"type": ev.get("type"), "reason": ev.get("reason"), "count": ev.get("count") or 1,
                        "message": (ev.get("message") or "")[:400],
                        "last": ev.get("lastTimestamp") or ev.get("eventTime")})
        return out

    def workload(self, ref: Resource) -> Optional[Dict[str, Any]]:
        pool = {"Deployment": self.deployments, "StatefulSet": self.statefulsets, "DaemonSet": self.daemonsets,
                "Job": self.jobs, "ReplicaSet": self.replicasets}.get(ref.kind, [])
        for obj in pool:
            meta = obj.get("metadata", {})
            if meta.get("name") == ref.name and meta.get("namespace") == ref.namespace:
                return obj
        return None

    def workload_labels(self, ref: Resource) -> Tuple[Dict[str, str], Dict[str, str]]:
        obj = self.workload(ref)
        if obj is None and ref.kind == "Pod":
            for pod in self.pods:
                m = pod.get("metadata", {})
                if m.get("name") == ref.name and m.get("namespace") == ref.namespace:
                    obj = pod
                    break
        if obj is None and ref.kind == "Node":
            for node in self.nodes:
                if node.get("metadata", {}).get("name") == ref.name:
                    obj = node
                    break
        meta = (obj or {}).get("metadata", {})
        return dict(meta.get("labels") or {}), dict(meta.get("annotations") or {})

    def management(self, ref: Resource) -> Dict[str, Any]:
        """How the workload is managed: gitops/helm/operator/manual + recent-change hints.

        Spec changes made directly to a GitOps- or operator-managed object get
        reverted by the controller, so the engine routes those to humans.
        """
        obj = self.workload(ref)
        if not obj:
            return {"managed_by": "unknown"}
        meta = obj.get("metadata", {})
        labels, annotations = meta.get("labels") or {}, meta.get("annotations") or {}
        managed = "manual"
        if "argocd.argoproj.io/instance" in labels or any(k_.startswith("argocd.argoproj.io/") for k_ in annotations):
            managed = "argocd"
        elif any(k_.startswith("kustomize.toolkit.fluxcd.io/") or k_.startswith("helm.toolkit.fluxcd.io/") for k_ in labels):
            managed = "flux"
        elif labels.get("app.kubernetes.io/managed-by", "").lower() == "helm" or "meta.helm.sh/release-name" in annotations:
            managed = "helm"
        elif any(o.get("controller") for o in meta.get("ownerReferences", []) or []):
            owner = [o for o in meta.get("ownerReferences", []) if o.get("controller")][0]
            managed = "operator"
            return {"managed_by": managed, "owner": f"{owner.get('kind')}/{owner.get('name')}",
                    "revision": annotations.get("deployment.kubernetes.io/revision")}
        info = {"managed_by": managed, "revision": annotations.get("deployment.kubernetes.io/revision")}
        if managed == "helm":
            info["helm_release"] = annotations.get("meta.helm.sh/release-name") or labels.get("app.kubernetes.io/instance")
        if managed == "argocd":
            info["argocd_app"] = labels.get("argocd.argoproj.io/instance")
        # Recent change hint: newest ReplicaSet creation time.
        newest = None
        for rs in self.replicasets:
            o = self.owner_of(rs)
            if o and o.kind == ref.kind and o.name == ref.name and rs.get("metadata", {}).get("namespace") == ref.namespace:
                ts = parse_time(rs.get("metadata", {}).get("creationTimestamp"))
                if ts and (newest is None or ts > newest):
                    newest = ts
        if newest:
            info["last_rollout_age_seconds"] = int(time.time() - newest)
        pdbs = []
        template_labels = (obj.get("spec", {}).get("template", {}).get("metadata", {}).get("labels") or {})
        for pdb in self.pdbs:
            if pdb.get("metadata", {}).get("namespace") != ref.namespace:
                continue
            sel = (pdb.get("spec", {}).get("selector") or {}).get("matchLabels") or {}
            if sel and all(template_labels.get(k_) == v for k_, v in sel.items()):
                pdbs.append({"name": pdb["metadata"]["name"], "disruptions_allowed": (pdb.get("status") or {}).get("disruptionsAllowed")})
        info["pdbs"] = pdbs
        return info

    def workload_availability(self, ref: Resource) -> Dict[str, Any]:
        obj = self.workload(ref)
        if not obj:
            return {}
        spec, status = obj.get("spec", {}), obj.get("status", {})
        desired = spec.get("replicas", status.get("desiredNumberScheduled", 1))
        ready = status.get("readyReplicas", status.get("numberReady", 0)) or 0
        return {"desired": desired, "ready": ready, "available": status.get("availableReplicas", ready),
                "updated": status.get("updatedReplicas"), "unavailable": status.get("unavailableReplicas")}


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------
class Detector:
    def __init__(self, snapshot: Snapshot, cfg: Dict[str, Any], scope_check: Callable[[Optional[str]], bool],
                 client: Optional[k.KubeClient] = None, policy_cfg: Optional[Dict[str, Any]] = None):
        self.snap = snapshot
        self.cfg = cfg
        self.in_scope = scope_check
        self.client = client
        self.policy_cfg = policy_cfg or {}
        self.now = time.time()

    def run(self, include_posture: Optional[bool] = None) -> List[Finding]:
        findings: List[Finding] = []
        findings += self.detect_pods()
        findings += self.detect_workloads(findings)
        findings += self.detect_jobs()
        findings += self.detect_nodes()
        findings += self.detect_pvcs()
        findings += self.detect_hpas()
        findings += self.detect_services()
        findings += self.detect_csrs()
        if self.snap.platform == "openshift":
            findings += self.detect_openshift()
        if include_posture if include_posture is not None else self.cfg.get("include_posture_audit", True):
            findings += self.posture_audit()
        limit = int(self.cfg.get("max_findings_per_cycle", 50))
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        findings.sort(key=lambda f: (order.get(f.severity, 5), f.subject.short))
        return findings[:limit]

    # -- pods ----------------------------------------------------------------
    def detect_pods(self) -> List[Finding]:
        grouped: Dict[Tuple[str, str], Finding] = {}
        for pod in self.snap.pods:
            meta = pod.get("metadata", {})
            ns = meta.get("namespace")
            if not self.in_scope(ns):
                continue
            for finding in self._pod_findings(pod):
                key = (finding.pattern_id, finding.subject.short)
                if key in grouped:
                    grouped[key].related_pods.append(finding.resource.name)
                    grouped[key].evidence.setdefault("affected_pods", 1)
                    grouped[key].evidence["affected_pods"] += 1
                else:
                    finding.evidence.setdefault("affected_pods", 1)
                    grouped[key] = finding
        out = list(grouped.values())
        for f in out:
            if f.owner:
                avail = self.snap.workload_availability(f.owner)
                f.evidence["management"] = self.snap.management(f.owner)
                if avail:
                    f.evidence["availability"] = avail
                    desired = avail.get("desired") or 0
                    ready = avail.get("ready") or 0
                    if desired and ready == 0 and f.severity in {"high", "medium"}:
                        f.severity = "critical"
                    elif desired and ready / desired < float(self.policy_cfg.get("unavailable_ratio_high", 0.5)) and f.severity == "medium":
                        f.severity = "high"
        return out

    def _pod_findings(self, pod: Dict[str, Any]) -> Iterable[Finding]:
        meta, spec, status = pod.get("metadata", {}), pod.get("spec", {}), pod.get("status", {})
        ns, name = meta.get("namespace"), meta.get("name")
        owner = self.snap.owner_of(pod)
        res = Resource("Pod", name, ns, "v1")
        node = spec.get("nodeName")
        phase = status.get("phase")
        events = self.snap.events_for(ns, "Pod", name)
        base_evidence = {"phase": phase, "node": node, "events": events, "pod": name,
                         "pod_age_seconds": int(age_seconds(meta.get("creationTimestamp"), self.now))}
        min_restarts = int(self.cfg.get("crashloop_min_restarts", 3))

        # Stuck terminating
        if meta.get("deletionTimestamp") and age_seconds(meta["deletionTimestamp"], self.now) > int(self.cfg.get("stuck_terminating_min_age_seconds", 900)):
            yield Finding("pod-stuck-terminating", "medium", res, f"pod {ns}/{name} stuck Terminating for "
                          f"{int(age_seconds(meta['deletionTimestamp'], self.now) // 60)} min", owner, node,
                          {**base_evidence, "finalizers": meta.get("finalizers", [])})
            return

        # Evicted / failed pods
        if phase == "Failed" and status.get("reason") in EVICTED_REASONS:
            yield Finding("pod-evicted", "low", res, f"pod {ns}/{name} {status.get('reason')}: {(status.get('message') or '')[:120]}",
                          owner, node, {**base_evidence, "reason": status.get("reason"), "message": status.get("message")})
            return

        if phase == "Succeeded":
            return

        # Pending pods
        if phase == "Pending":
            sched = condition(pod, "PodScheduled")
            age = age_seconds(meta.get("creationTimestamp"), self.now)
            if sched.get("status") == "False" and age > int(self.cfg.get("pending_pod_min_age_seconds", 300)):
                msg = sched.get("message") or ""
                pattern = "pod-pending-volume" if re.search(r"persistentvolumeclaim|volume node affinity|unbound", msg, re.I) \
                    else "pod-pending-unschedulable"
                yield Finding(pattern, "high", res, f"pod {ns}/{name} unschedulable: {msg[:160]}", owner, node,
                              {**base_evidence, "reason": sched.get("reason"), "message": msg,
                               "requests": _pod_requests(spec), "node_selector": spec.get("nodeSelector"),
                               "tolerations": spec.get("tolerations"), "unschedulable_for_seconds": int(age),
                               "cause": classify_unschedulable(msg)})
                return
            # Scheduled but not running: inspect container waiting reasons and events
            if sched.get("status") == "True" and age > int(self.cfg.get("pending_pod_min_age_seconds", 300)):
                reasons = {e["reason"] for e in events}
                if reasons & {"FailedMount", "FailedAttachVolume", "FailedMapVolume", "VolumeResizeFailed"}:
                    yield Finding("pod-pending-volume", "high", res, f"pod {ns}/{name} cannot mount volumes", owner, node,
                                  {**base_evidence, "volumes": [v.get("name") for v in spec.get("volumes", [])]})
                    return

        for cs, is_init in _container_statuses(status):
            waiting = (cs.get("state") or {}).get("waiting") or {}
            terminated_last = (cs.get("lastState") or {}).get("terminated") or {}
            terminated_now = (cs.get("state") or {}).get("terminated") or {}
            reason = waiting.get("reason", "")
            restarts = cs.get("restartCount", 0) or 0
            evidence = {**base_evidence, "container": cs.get("name"), "image": cs.get("image"), "init_container": is_init,
                        "restart_count": restarts, "waiting_reason": reason, "waiting_message": (waiting.get("message") or "")[:400],
                        "last_exit_code": terminated_last.get("exitCode", terminated_now.get("exitCode")),
                        "last_termination_reason": terminated_last.get("reason", terminated_now.get("reason")),
                        "last_termination_message": (terminated_last.get("message") or terminated_now.get("message") or "")[:400]}
            if reason in IMAGE_PULL_REASONS:
                yield Finding("pod-imagepull-failure", "high", res, f"{ns}/{name} cannot pull image {cs.get('image')}: {reason}",
                              owner, node, {**evidence, "cause": classify_image_pull(waiting.get("message") or "", events)})
                continue
            if reason in CONFIG_REASONS:
                yield Finding("pod-config-error", "high", res, f"{ns}/{name} {reason}: {(waiting.get('message') or '')[:120]}",
                              owner, node, {**evidence, "missing": _missing_ref(waiting.get("message") or "")})
                continue
            if reason in RUN_REASONS:
                yield Finding("pod-run-container-error", "high", res, f"{ns}/{name} {reason}: {(waiting.get('message') or '')[:120]}",
                              owner, node, {**evidence, "logs_tail": self._logs(ns, name, cs.get("name"), previous=True)})
                continue
            # Only a *recent* OOM counts: a pod that OOMed once an hour ago and has been
            # running fine since is not an incident (the kill is remembered in lastState forever).
            oom_recent = terminated_now.get("reason") == "OOMKilled" or (
                terminated_last.get("reason") == "OOMKilled"
                and age_seconds(terminated_last.get("finishedAt"), self.now) <= int(self.cfg.get("events_lookback_seconds", 1800)))
            if oom_recent and restarts >= 1:
                limits = _container_resources(spec, cs.get("name"))
                yield Finding("pod-oomkilled", "high", res, f"{ns}/{name} container {cs.get('name')} OOMKilled ({restarts} restarts)",
                              owner, node, {**evidence, "resources": limits, "logs_tail": self._logs(ns, name, cs.get("name"), previous=True)})
                continue
            # Between back-offs a crash-looping container briefly shows state.terminated
            # (STATUS "Error") instead of waiting CrashLoopBackOff; treat both the same.
            crashing = reason == "CrashLoopBackOff" or (
                bool(terminated_now) and (terminated_now.get("exitCode") or 0) != 0 and not waiting)
            if crashing and restarts >= min_restarts:
                probe_events = [e for e in events if e["reason"] == "Unhealthy" and "Liveness" in (e["message"] or "")]
                pattern = "pod-probe-failing" if probe_events else ("pod-init-failure" if is_init else "pod-crashloopbackoff")
                yield Finding(pattern, "high", res, f"{ns}/{name} container {cs.get('name')} in CrashLoopBackOff ({restarts} restarts, exit {evidence['last_exit_code']})",
                              owner, node, {**evidence, "probe_events": probe_events[:3], "cause": classify_exit(evidence),
                                            "logs_tail": self._logs(ns, name, cs.get("name"), previous=True)})
                continue
            if reason in {"CrashLoopBackOff", "Error"} and is_init:
                yield Finding("pod-init-failure", "high", res, f"{ns}/{name} init container {cs.get('name')} failing ({restarts} restarts)",
                              owner, node, {**evidence, "logs_tail": self._logs(ns, name, cs.get("name"), previous=True)})
                continue
            # Running but never/not ready: readiness probe
            if phase == "Running" and not is_init and cs.get("started") and not cs.get("ready"):
                ready_cond = condition(pod, "Ready")
                not_ready_for = age_seconds(ready_cond.get("lastTransitionTime"), self.now)
                readiness_events = [e for e in events if e["reason"] == "Unhealthy" and "Readiness" in (e["message"] or "")]
                if readiness_events and not_ready_for > int(self.cfg.get("pending_pod_min_age_seconds", 300)):
                    yield Finding("pod-probe-failing", "medium", res, f"{ns}/{name} not Ready for {int(not_ready_for // 60)} min: readiness probe failing",
                                  owner, node, {**evidence, "probe_events": readiness_events[:3], "probe_kind": "readiness",
                                                "logs_tail": self._logs(ns, name, cs.get("name"))})

    def _logs(self, ns: str, pod: str, container: str, previous: bool = False) -> str:
        """Tail of the failing container's logs.

        For a container that is currently waiting (CrashLoopBackOff), the plain
        log request already returns the last terminated instance; ``previous``
        then points at an instance the runtime may have garbage-collected. Try
        the requested mode first and fall back to the other one.
        """
        if not self.client:
            return ""
        tail = int(self.cfg.get("log_tail_lines", 40))
        for mode in (previous, not previous):
            text = self.client.pod_logs(ns, pod, container, tail=tail, previous=mode)
            if text and not text.startswith("unable to retrieve container logs") and not text.startswith("<logs unavailable"):
                return redact(text)[-4000:]
        return text[:200] if text else ""

    # -- workloads -----------------------------------------------------------
    def detect_workloads(self, existing: List[Finding]) -> List[Finding]:
        out: List[Finding] = []
        covered = {f.subject.short for f in existing}
        for dep in self.snap.deployments:
            meta, spec, status = dep.get("metadata", {}), dep.get("spec", {}), dep.get("status", {})
            ns, name = meta.get("namespace"), meta.get("name")
            if not self.in_scope(ns):
                continue
            res = Resource("Deployment", name, ns, "apps/v1")
            desired = spec.get("replicas", 1) or 0
            if desired == 0:
                continue
            events = self.snap.events_for(ns, "Deployment", name)
            avail = self.snap.workload_availability(res)
            progressing = condition(dep, "Progressing")
            replica_failure = condition(dep, "ReplicaFailure")
            if replica_failure.get("status") == "True":
                msg = replica_failure.get("message") or ""
                rs_events = []
                for rs in self.snap.replicasets:
                    o = self.snap.owner_of(rs)
                    if o and o.kind == "Deployment" and o.name == name and rs.get("metadata", {}).get("namespace") == ns:
                        rs_events += self.snap.events_for(ns, "ReplicaSet", rs["metadata"]["name"], 4)
                text = msg + " " + " ".join(e["message"] or "" for e in rs_events)
                if re.search(r"security context constraint|SecurityContextConstraints|unable to validate against any", text, re.I):
                    pattern, sev = "pod-scc-denied", "high"
                elif re.search(r"exceeded quota|forbidden", text, re.I):
                    pattern, sev = "workload-replica-failure", "high"
                else:
                    pattern, sev = "workload-replica-failure", "high"
                out.append(Finding(pattern, sev, res, f"{ns}/deployment/{name} cannot create pods: {msg[:160]}", None, None,
                                   {"message": msg, "replicaset_events": rs_events[:4], "events": events, "availability": avail,
                                    "cause": classify_replica_failure(text)}))
                continue
            if progressing.get("status") == "False" and progressing.get("reason") == "ProgressDeadlineExceeded":
                if res.short in covered:
                    continue  # pod-level finding already explains it
                out.append(Finding("workload-rollout-stuck", "high", res,
                                   f"{ns}/deployment/{name} rollout stuck: {(progressing.get('message') or '')[:140]}", None, None,
                                   {"message": progressing.get("message"), "events": events, "availability": avail,
                                    "revision": meta.get("annotations", {}).get("deployment.kubernetes.io/revision"),
                                    "image": [c.get("image") for c in spec.get("template", {}).get("spec", {}).get("containers", [])]}))
                continue
            if (avail.get("available") or 0) == 0 and res.short not in covered \
                    and age_seconds(meta.get("creationTimestamp"), self.now) > int(self.cfg.get("rollout_stuck_min_age_seconds", 600)):
                out.append(Finding("workload-unavailable", "high", res, f"{ns}/deployment/{name} has 0/{desired} available replicas",
                                   None, None, {"availability": avail, "events": events, "conditions": status.get("conditions")}))
        for sts in self.snap.statefulsets:
            meta, spec, status = sts.get("metadata", {}), sts.get("spec", {}), sts.get("status", {})
            ns, name = meta.get("namespace"), meta.get("name")
            if not self.in_scope(ns):
                continue
            res = Resource("StatefulSet", name, ns, "apps/v1")
            desired = spec.get("replicas", 1) or 0
            if desired and (status.get("readyReplicas") or 0) == 0 and res.short not in covered \
                    and age_seconds(meta.get("creationTimestamp"), self.now) > int(self.cfg.get("rollout_stuck_min_age_seconds", 600)):
                out.append(Finding("workload-unavailable", "high", res, f"{ns}/statefulset/{name} has 0/{desired} ready replicas",
                                   None, None, {"availability": self.snap.workload_availability(res),
                                                "events": self.snap.events_for(ns, "StatefulSet", name)}))
        return out

    def detect_jobs(self) -> List[Finding]:
        out = []
        for job in self.snap.jobs:
            meta = job.get("metadata", {})
            ns, name = meta.get("namespace"), meta.get("name")
            if not self.in_scope(ns):
                continue
            failed = condition(job, "Failed")
            if failed.get("status") == "True":
                owner = self.snap.owner_of(job)
                out.append(Finding("job-failed", "low", Resource("Job", name, ns, "batch/v1"),
                                   f"{ns}/job/{name} failed: {failed.get('reason')} {(failed.get('message') or '')[:100]}", owner, None,
                                   {"reason": failed.get("reason"), "message": failed.get("message"),
                                    "failed": job.get("status", {}).get("failed"), "events": self.snap.events_for(ns, "Job", name)}))
        return out

    # -- nodes ---------------------------------------------------------------
    def detect_nodes(self) -> List[Finding]:
        out = []
        min_age = int(self.cfg.get("node_not_ready_min_age_seconds", 300))
        for node in self.snap.nodes:
            meta = node.get("metadata", {})
            name = meta.get("name")
            res = Resource("Node", name, None, "v1")
            ready = condition(node, "Ready")
            events = self.snap.events_for("", "Node", name)
            info = (node.get("status") or {}).get("nodeInfo", {})
            base = {"events": events, "kubelet": info.get("kubeletVersion"), "os": info.get("osImage"),
                    "unschedulable": node.get("spec", {}).get("unschedulable", False),
                    "taints": node.get("spec", {}).get("taints", []), "roles": [l for l in meta.get("labels", {}) if l.startswith("node-role")]}
            if ready.get("status") != "True" and age_seconds(ready.get("lastTransitionTime"), self.now) > min_age:
                out.append(Finding("node-not-ready", "critical", res, f"node {name} {ready.get('status', 'Unknown')} "
                                   f"({ready.get('reason')}) for {int(age_seconds(ready.get('lastTransitionTime'), self.now) // 60)} min",
                                   None, name, {**base, "reason": ready.get("reason"), "message": ready.get("message"),
                                                "pods_on_node": sum(1 for p in self.snap.pods if p.get("spec", {}).get("nodeName") == name)}))
                continue
            pressures = [c for c in ("MemoryPressure", "DiskPressure", "PIDPressure") if condition(node, c).get("status") == "True"]
            if pressures:
                out.append(Finding("node-pressure", "high", res, f"node {name} under {', '.join(pressures)}", None, name,
                                   {**base, "pressures": pressures, "allocatable": (node.get("status") or {}).get("allocatable"),
                                    "messages": [condition(node, c).get("message") for c in pressures]}))
        return out

    # -- storage -------------------------------------------------------------
    def detect_pvcs(self) -> List[Finding]:
        out = []
        for pvc in self.snap.pvcs:
            meta = pvc.get("metadata", {})
            ns, name = meta.get("namespace"), meta.get("name")
            if not self.in_scope(ns):
                continue
            if pvc.get("status", {}).get("phase") == "Pending" and age_seconds(meta.get("creationTimestamp"), self.now) > int(self.cfg.get("pvc_pending_min_age_seconds", 300)):
                events = self.snap.events_for(ns, "PersistentVolumeClaim", name)
                reasons = {e["reason"] for e in events}
                wait_consumer = reasons <= {"WaitForFirstConsumer", "WaitForPodScheduled"} and bool(reasons)
                severity = "info" if wait_consumer else "high"
                out.append(Finding("pvc-pending", severity, Resource("PersistentVolumeClaim", name, ns, "v1"),
                                   f"{ns}/pvc/{name} Pending for {int(age_seconds(meta.get('creationTimestamp'), self.now) // 60)} min"
                                   + (" (waiting for first consumer)" if wait_consumer else ""), None, None,
                                   {"storage_class": pvc.get("spec", {}).get("storageClassName"), "access_modes": pvc.get("spec", {}).get("accessModes"),
                                    "requested": (pvc.get("spec", {}).get("resources") or {}).get("requests"), "events": events,
                                    "wait_for_first_consumer": wait_consumer}))
        return out

    # -- autoscaling ---------------------------------------------------------
    def detect_hpas(self) -> List[Finding]:
        out = []
        for hpa in self.snap.hpas:
            meta = hpa.get("metadata", {})
            ns, name = meta.get("namespace"), meta.get("name")
            if not self.in_scope(ns):
                continue
            active = condition(hpa, "ScalingActive")
            able = condition(hpa, "AbleToScale")
            if active.get("status") == "False" and active.get("reason") in {"FailedGetResourceMetric", "FailedGetExternalMetric",
                                                                             "FailedGetObjectMetric", "InvalidMetricSourceType", "FailedGetScale"}:
                target = hpa.get("spec", {}).get("scaleTargetRef", {})
                out.append(Finding("hpa-metrics-unavailable", "medium", Resource("HorizontalPodAutoscaler", name, ns, "autoscaling/v2"),
                                   f"{ns}/hpa/{name} cannot scale: {active.get('reason')}",
                                   Resource(target.get("kind", ""), target.get("name", ""), ns) if target.get("name") else None, None,
                                   {"reason": active.get("reason"), "message": active.get("message"), "able_to_scale": able,
                                    "current_replicas": hpa.get("status", {}).get("currentReplicas"),
                                    "events": self.snap.events_for(ns, "HorizontalPodAutoscaler", name)}))
        return out

    # -- services ------------------------------------------------------------
    def detect_services(self) -> List[Finding]:
        out = []
        pods_by_ns: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for pod in self.snap.pods:
            pods_by_ns[pod.get("metadata", {}).get("namespace", "")].append(pod)
        for svc in self.snap.services:
            meta, spec = svc.get("metadata", {}), svc.get("spec", {})
            ns, name = meta.get("namespace"), meta.get("name")
            selector = spec.get("selector") or {}
            if not selector or not self.in_scope(ns) or spec.get("type") == "ExternalName":
                continue
            matching = [p for p in pods_by_ns.get(ns, []) if all((p.get("metadata", {}).get("labels") or {}).get(k_) == v for k_, v in selector.items())]
            if matching:
                continue
            if age_seconds(meta.get("creationTimestamp"), self.now) < int(self.cfg.get("rollout_stuck_min_age_seconds", 600)):
                continue
            # No pod matches the selector at all -> likely selector/label mismatch (or scaled to zero)
            out.append(Finding("service-no-endpoints", "medium", Resource("Service", name, ns, "v1"),
                               f"{ns}/service/{name} selector {selector} matches no pods", None, None,
                               {"selector": selector, "ports": spec.get("ports"),
                                "candidate_label_sets": _nearby_label_sets(pods_by_ns.get(ns, []), selector)}))
        return out

    def detect_csrs(self) -> List[Finding]:
        pending = []
        for csr in self.snap.csrs:
            conds = (csr.get("status") or {}).get("conditions") or []
            if not conds:
                meta = csr.get("metadata", {})
                if age_seconds(meta.get("creationTimestamp"), self.now) > 600:
                    pending.append({"name": meta.get("name"), "requestor": csr.get("spec", {}).get("username"),
                                    "signer": csr.get("spec", {}).get("signerName"),
                                    "age_min": int(age_seconds(meta.get("creationTimestamp"), self.now) // 60)})
        if not pending:
            return []
        return [Finding("cluster-csr-pending", "medium", Resource("CertificateSigningRequest", pending[0]["name"], None, "certificates.k8s.io/v1"),
                        f"{len(pending)} CertificateSigningRequest(s) pending approval for >10 min", None, None,
                        {"pending": pending[:20], "count": len(pending)})]

    # -- OpenShift -----------------------------------------------------------
    def detect_openshift(self) -> List[Finding]:
        out = []
        for co in self.snap.clusteroperators:
            name = co.get("metadata", {}).get("name")
            degraded = condition(co, "Degraded")
            available = condition(co, "Available")
            progressing = condition(co, "Progressing")
            if degraded.get("status") == "True" or available.get("status") == "False":
                out.append(Finding("ocp-clusteroperator-degraded", "critical", Resource("ClusterOperator", name, None, "config.openshift.io/v1"),
                                   f"clusteroperator/{name} Degraded={degraded.get('status')} Available={available.get('status')}: "
                                   f"{(degraded.get('message') or available.get('message') or '')[:160]}", None, None,
                                   {"degraded": degraded, "available": available, "progressing": progressing,
                                    "versions": (co.get("status") or {}).get("versions"),
                                    "related_namespaces": [r.get("name") for r in (co.get("status") or {}).get("relatedObjects", []) if r.get("resource") == "namespaces"]},
                                   platform="openshift"))
        for mcp in self.snap.machineconfigpools:
            name = mcp.get("metadata", {}).get("name")
            degraded = condition(mcp, "Degraded")
            updating = condition(mcp, "Updating")
            status = mcp.get("status") or {}
            if degraded.get("status") == "True" or (status.get("degradedMachineCount") or 0) > 0:
                out.append(Finding("ocp-mcp-degraded", "critical", Resource("MachineConfigPool", name, None, "machineconfiguration.openshift.io/v1"),
                                   f"machineconfigpool/{name} degraded ({status.get('degradedMachineCount')} machines): "
                                   f"{(condition(mcp, 'NodeDegraded').get('message') or degraded.get('message') or '')[:160]}", None, None,
                                   {"machine_count": status.get("machineCount"), "ready": status.get("readyMachineCount"),
                                    "updated": status.get("updatedMachineCount"), "degraded": status.get("degradedMachineCount"),
                                    "updating": updating, "node_degraded": condition(mcp, "NodeDegraded"),
                                    "render_degraded": condition(mcp, "RenderDegraded")}, platform="openshift"))
            elif updating.get("status") == "True" and age_seconds(updating.get("lastTransitionTime"), self.now) > 3 * 3600:
                out.append(Finding("ocp-mcp-degraded", "high", Resource("MachineConfigPool", name, None, "machineconfiguration.openshift.io/v1"),
                                   f"machineconfigpool/{name} Updating for >3h ({status.get('updatedMachineCount')}/{status.get('machineCount')} updated)",
                                   None, None, {"updating": updating, "machine_count": status.get("machineCount"),
                                                "updated": status.get("updatedMachineCount"), "ready": status.get("readyMachineCount")},
                                   platform="openshift"))
        return out

    # -- posture audit (preventive, notify-only) ------------------------------
    def posture_audit(self) -> List[Finding]:
        out = []
        pdb_selectors = [(p.get("metadata", {}).get("namespace"), (p.get("spec", {}).get("selector") or {}).get("matchLabels") or {}) for p in self.snap.pdbs]
        for dep in self.snap.deployments:
            meta, spec = dep.get("metadata", {}), dep.get("spec", {})
            ns, name = meta.get("namespace"), meta.get("name")
            if not self.in_scope(ns):
                continue
            tmpl = spec.get("template", {}).get("spec", {})
            containers = tmpl.get("containers", [])
            issues = []
            for c in containers:
                image = c.get("image") or ""
                if image.endswith(":latest") or (":" not in image.rsplit("/", 1)[-1] and "@" not in image):
                    issues.append(f"container {c['name']} uses mutable/untagged image {image}")
                resources = c.get("resources") or {}
                if not (resources.get("requests") or {}).get("memory") or not (resources.get("limits") or {}).get("memory"):
                    issues.append(f"container {c['name']} lacks memory request/limit")
                if not (resources.get("requests") or {}).get("cpu"):
                    issues.append(f"container {c['name']} lacks cpu request")
                if not c.get("readinessProbe"):
                    issues.append(f"container {c['name']} has no readinessProbe")
            replicas = spec.get("replicas", 1)
            if replicas == 1:
                issues.append("single replica (no redundancy during node drain or crash)")
            labels = spec.get("template", {}).get("metadata", {}).get("labels") or {}
            if replicas and replicas > 1 and not any(ns_ == ns and sel and all(labels.get(k_) == v for k_, v in sel.items()) for ns_, sel in pdb_selectors):
                issues.append("multi-replica workload without a PodDisruptionBudget")
            if issues:
                out.append(Finding("posture-workload-hardening", "info", Resource("Deployment", name, ns, "apps/v1"),
                                   f"{ns}/deployment/{name}: {len(issues)} hardening gap(s)", None, None, {"issues": issues}))
        return out


# ---------------------------------------------------------------------------
# Classification helpers (turn raw messages into stable "cause" labels)
# ---------------------------------------------------------------------------
def classify_unschedulable(msg: str) -> str:
    m = msg.lower()
    if "insufficient nvidia.com/gpu" in m or "insufficient" in m and "gpu" in m:
        return "insufficient-gpu"
    if "insufficient memory" in m:
        return "insufficient-memory"
    if "insufficient cpu" in m:
        return "insufficient-cpu"
    if "untolerated taint" in m or "taint" in m:
        return "taint-not-tolerated"
    if "affinity" in m or "anti-affinity" in m:
        return "affinity-rules"
    if "node selector" in m or "didn't match pod's node affinity/selector" in m:
        return "node-selector-mismatch"
    if "volume node affinity conflict" in m:
        return "volume-node-affinity"
    if "persistentvolumeclaim" in m or "unbound" in m:
        return "pvc-not-bound"
    if "too many pods" in m:
        return "node-pod-limit"
    if "unschedulable" in m or "cordon" in m:
        return "nodes-cordoned"
    if "no nodes available" in m:
        return "no-nodes"
    return "unknown"


def classify_image_pull(msg: str, events: List[Dict[str, Any]]) -> str:
    text = (msg + " " + " ".join(e.get("message") or "" for e in events)).lower()
    if "unauthorized" in text or "authentication required" in text or "401" in text or "403" in text or "denied" in text:
        return "registry-auth"
    if "not found" in text or "manifest unknown" in text or "404" in text:
        return "image-or-tag-not-found"
    if "invalid reference" in text or "invalidimagename" in text:
        return "invalid-image-name"
    if "timeout" in text or "i/o timeout" in text or "dial tcp" in text or "no such host" in text or "connection refused" in text:
        return "registry-unreachable"
    if "toomanyrequests" in text or "rate limit" in text:
        return "registry-rate-limit"
    if "x509" in text or "certificate" in text:
        return "registry-tls"
    if "no space left" in text or "disk" in text:
        return "node-disk-full"
    return "unknown"


def classify_exit(evidence: Dict[str, Any]) -> str:
    code = evidence.get("last_exit_code")
    reason = (evidence.get("last_termination_reason") or "").lower()
    if reason == "oomkilled" or code == 137:
        return "oom-or-sigkill"
    if code == 1:
        return "application-error"
    if code == 2:
        return "misuse-or-config"
    if code == 126 or code == 127:
        return "command-not-found-or-not-executable"
    if code == 139:
        return "segfault"
    if code == 143:
        return "sigterm"
    if code == 0:
        return "exited-cleanly-not-a-daemon"
    return "unknown"


def classify_replica_failure(text: str) -> str:
    t = text.lower()
    if "security context constraint" in t or "unable to validate against any" in t:
        return "scc-denied"
    if "exceeded quota" in t:
        return "resource-quota"
    if "limitrange" in t or "limit range" in t or "must be less than or equal to" in t or "minimum" in t:
        return "limit-range"
    if "admission webhook" in t or "denied the request" in t:
        return "admission-webhook"
    if "forbidden" in t:
        return "rbac-or-psa"
    if "serviceaccount" in t and "not found" in t:
        return "missing-serviceaccount"
    return "unknown"


def _missing_ref(msg: str) -> Dict[str, Any]:
    m = re.search(r'(configmap|secret) "([^"]+)" not found', msg, re.I)
    if m:
        return {"kind": m.group(1).lower(), "name": m.group(2)}
    m = re.search(r"couldn't find key (\S+) in (ConfigMap|Secret) (\S+)", msg, re.I)
    if m:
        return {"kind": m.group(2).lower(), "name": m.group(3), "key": m.group(1)}
    return {}


def _container_statuses(status: Dict[str, Any]) -> Iterable[Tuple[Dict[str, Any], bool]]:
    for cs in status.get("initContainerStatuses") or []:
        yield cs, True
    for cs in status.get("containerStatuses") or []:
        yield cs, False


def _pod_requests(spec: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for c in spec.get("containers", []):
        out[c.get("name")] = c.get("resources") or {}
    return out


def _container_resources(spec: Dict[str, Any], container: Optional[str]) -> Dict[str, Any]:
    for c in spec.get("containers", []) + spec.get("initContainers", []):
        if c.get("name") == container:
            return c.get("resources") or {}
    return {}


def _nearby_label_sets(pods: List[Dict[str, Any]], selector: Dict[str, str], limit: int = 3) -> List[Dict[str, str]]:
    scored = []
    for pod in pods:
        labels = pod.get("metadata", {}).get("labels") or {}
        overlap = sum(1 for k_, v in selector.items() if k_ in labels)
        if overlap:
            scored.append((overlap, {k_: labels[k_] for k_ in selector if k_ in labels}))
    scored.sort(key=lambda t: -t[0])
    seen, out = set(), []
    for _, labels in scored:
        key = tuple(sorted(labels.items()))
        if key not in seen:
            seen.add(key)
            out.append(labels)
        if len(out) >= limit:
            break
    return out


_REDACT_PATTERNS = [
    (re.compile(r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._\-]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:api[_-]?key|token|password|passwd|secret)\s*[=:]\s*)[^\s,;\"']+"), r"\1[REDACTED]"),
    (re.compile(r"hf_[A-Za-z0-9]{20,}"), "[REDACTED_HF_TOKEN]"),
    (re.compile(r"nvapi-[A-Za-z0-9_\-]{20,}"), "[REDACTED_NVAPI_KEY]"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"), "[REDACTED_SLACK_TOKEN]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "[REDACTED_JWT]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED_PRIVATE_KEY]"),
]


def redact(text: str) -> str:
    """Strip credential-looking strings before logs reach memory, the LLM or Slack."""
    if not text:
        return text
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
