# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Goal-based verification: re-observe the cluster, do not trust the action.

An action "worked" only when the triggering signal is gone AND the subject is
healthy (controller ready == desired, node Ready, PVC Bound, ...). The check is
re-run until success or timeout.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Optional, Tuple

from . import kube as k
from .detect import Detector, Snapshot, condition
from .models import Finding

log = logging.getLogger(__name__)


def subject_healthy(client: k.KubeClient, finding: Finding, snap: Snapshot) -> Tuple[bool, str]:
    subject = finding.subject
    if subject.kind in {"Deployment", "StatefulSet", "DaemonSet"}:
        avail = snap.workload_availability(subject)
        if not avail:
            return False, f"{subject.short} not found in snapshot"
        desired = avail.get("desired") or 0
        ready = avail.get("ready") or 0
        if desired == 0:
            return True, f"{subject.short} scaled to zero"
        ok = ready >= desired
        return ok, f"{subject.short} ready {ready}/{desired}"
    if subject.kind == "Node":
        for node in snap.nodes:
            if node.get("metadata", {}).get("name") == subject.name:
                ready = condition(node, "Ready").get("status") == "True"
                pressures = [c for c in ("MemoryPressure", "DiskPressure", "PIDPressure") if condition(node, c).get("status") == "True"]
                return ready and not pressures, f"node {subject.name} Ready={ready} pressures={pressures}"
        return False, f"node {subject.name} not found"
    if subject.kind == "PersistentVolumeClaim":
        for pvc in snap.pvcs:
            m = pvc.get("metadata", {})
            if m.get("name") == subject.name and m.get("namespace") == subject.namespace:
                phase = pvc.get("status", {}).get("phase")
                return phase == "Bound", f"pvc {subject.short} phase={phase}"
        return False, "pvc not found"
    if subject.kind == "Pod":
        for pod in snap.pods:
            m = pod.get("metadata", {})
            if m.get("name") == subject.name and m.get("namespace") == subject.namespace:
                ready = condition(pod, "Ready").get("status") == "True"
                return ready, f"pod {subject.short} Ready={ready} phase={pod.get('status', {}).get('phase')}"
        # Pod gone: fine when the action was a cleanup
        return finding.pattern_id in {"pod-evicted", "pod-stuck-terminating"}, f"pod {subject.short} no longer exists"
    # Namespace-level cleanups etc.
    return True, "no subject-level health check applies"


def verify_resolved(client: k.KubeClient, finding: Finding, cfg: Dict[str, Any], detection_cfg: Dict[str, Any],
                    scope_check: Callable[[Optional[str]], bool], timeout: int, poll: int,
                    sleep: Callable[[float], None] = time.sleep) -> Tuple[bool, str]:
    """Poll until the finding's fingerprint disappears and the subject is healthy."""
    deadline = time.time() + timeout
    namespaces = [finding.subject.namespace] if finding.subject.namespace else None
    last_detail = "not checked"
    # Give the controller a moment before the first look.
    sleep(min(poll, 10))
    while True:
        try:
            snap = Snapshot.load(client, namespaces=namespaces, cluster_scope=finding.subject.namespace is None,
                                 events_lookback=int(detection_cfg.get("events_lookback_seconds", 1800)))
        except k.KubeError as exc:
            last_detail = f"snapshot failed: {exc}"
            snap = None
        if snap is not None:
            # Fresh pods restarting a couple of times right after a restart are expected;
            # use a relaxed detector threshold so we do not immediately re-flag them.
            relaxed = dict(detection_cfg)
            relaxed["crashloop_min_restarts"] = max(int(detection_cfg.get("crashloop_min_restarts", 3)), 1)
            relaxed["include_posture_audit"] = False
            findings = Detector(snap, relaxed, scope_check, client=None).run(include_posture=False)
            still_present = any(f.fingerprint == finding.fingerprint for f in findings)
            healthy, detail = subject_healthy(client, finding, snap)
            last_detail = detail + ("; symptom still present" if still_present else "; symptom cleared")
            if healthy and not still_present:
                return True, last_detail
        if time.time() >= deadline:
            return False, f"timeout after {timeout}s: {last_detail}"
        sleep(poll)
