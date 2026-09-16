# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Allow-listed remediation actions.

Every action the agent can take is defined here with a default risk tier.
The LLM may only *choose* among these ids; it can never invent a command.

SAFE       - executed automatically in ``safe`` and ``assisted`` modes.
MEDIUM     - executed only with an operator approval annotation (assisted mode).
NEVER_AUTO - documented for humans only; the agent drafts the steps.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from . import kube as k
from .models import MEDIUM, NEVER_AUTO, SAFE, ActionResult, ActionSpec, Finding, iso

log = logging.getLogger(__name__)

RESTART_ANNOTATION = "sre-autoheal.nvidia.com/restartedAt"
LAST_ACTION_ANNOTATION = "sre-autoheal.nvidia.com/last-action"

CATALOG: Dict[str, ActionSpec] = {
    "restart_pod": ActionSpec(
        id="restart_pod", tier=SAFE,
        description="Delete a controller-owned pod so its controller recreates it on a fresh node/container "
                    "(clears CrashLoopBackOff backoff, transient image/config/volume mount errors).",
        applies_to=["Deployment", "ReplicaSet", "StatefulSet", "DaemonSet", "Job"],
        params_schema={"pod": "name of the pod to delete (defaults to the finding's pod)"},
        rbac=["pods: delete"]),
    "rollout_restart": ActionSpec(
        id="rollout_restart", tier=SAFE,
        description="Rolling restart of a Deployment/StatefulSet/DaemonSet (same as kubectl rollout restart); "
                    "picks up new ConfigMap/Secret data, clears wedged connections, respects PDB.",
        applies_to=["Deployment", "StatefulSet", "DaemonSet"],
        rbac=["deployments|statefulsets|daemonsets: patch"]),
    "delete_evicted_pods": ActionSpec(
        id="delete_evicted_pods", tier=SAFE,
        description="Remove evicted or terminated failed pods belonging to the current finding.",
        applies_to=["Namespace", "Deployment", "StatefulSet", "DaemonSet", "Job", "Pod"],
        rbac=["pods: delete"]),
    "rollout_undo": ActionSpec(
        id="rollout_undo", tier=MEDIUM,
        description="Roll a Deployment back to its previous ReplicaSet revision (kubectl rollout undo). "
                    "Use when a new revision introduced CrashLoop/ImagePull/Config errors and the previous one was healthy.",
        applies_to=["Deployment"], reversible=True,
        rbac=["deployments: patch", "replicasets: list"]),
    "scale": ActionSpec(
        id="scale", tier=MEDIUM,
        description="Set the replica count of a Deployment/StatefulSet (e.g. add capacity, or scale to zero a runaway job).",
        applies_to=["Deployment", "StatefulSet"],
        params_schema={"replicas": "integer target replica count"},
        rbac=["deployments/scale|statefulsets/scale: patch"]),
    "bump_memory_limit": ActionSpec(
        id="bump_memory_limit", tier=MEDIUM,
        description="Raise the memory limit (and request if it exceeds the new limit) of the OOMKilled container by a factor.",
        applies_to=["Deployment", "StatefulSet", "DaemonSet"],
        params_schema={"container": "container name", "factor": "multiplier, default 1.5, max 4",
                       "max_limit": "hard cap such as 8Gi"},
        rbac=["deployments|statefulsets|daemonsets: patch"]),
    "force_delete_pod": ActionSpec(
        id="force_delete_pod", tier=MEDIUM,
        description="Delete a pod stuck Terminating with grace period 0. Risky for StatefulSets (possible split brain).",
        applies_to=["Deployment", "ReplicaSet", "DaemonSet", "Job", "Pod"],
        params_schema={"pod": "pod name"},
        rbac=["pods: delete"]),
    "cordon_node": ActionSpec(
        id="cordon_node", tier=MEDIUM,
        description="Mark a node unschedulable so new pods avoid it (no drain).",
        applies_to=["Node"], rbac=["nodes: patch"]),
    "uncordon_node": ActionSpec(
        id="uncordon_node", tier=MEDIUM,
        description="Mark a node schedulable again after it recovered.",
        applies_to=["Node"], rbac=["nodes: patch"]),
    "drain_node": ActionSpec(
        id="drain_node", tier=NEVER_AUTO,
        description="Evict all pods from a node (kubectl drain). Human-only: PDBs, local storage and stateful workloads need judgement.",
        applies_to=["Node"], reversible=False),
    "approve_csr": ActionSpec(
        id="approve_csr", tier=NEVER_AUTO,
        description="Approve pending node CSRs (oc adm certificate approve). Human-only: identity decision.",
        applies_to=["CertificateSigningRequest"], reversible=False),
    "fix_image_reference": ActionSpec(
        id="fix_image_reference", tier=NEVER_AUTO,
        description="Correct an image tag/registry or imagePullSecret. Human-only: requires knowing the intended artifact.",
        applies_to=["Deployment", "StatefulSet", "DaemonSet", "Job"], reversible=True),
    "create_missing_config": ActionSpec(
        id="create_missing_config", tier=NEVER_AUTO,
        description="Create the missing ConfigMap/Secret referenced by the pod. Human-only: content unknown to the agent.",
        applies_to=["Deployment", "StatefulSet", "DaemonSet", "Job"], reversible=True),
    "fix_probe": ActionSpec(
        id="fix_probe", tier=NEVER_AUTO,
        description="Adjust liveness/readiness probe path, port, timeout or initialDelay. Human-only.",
        applies_to=["Deployment", "StatefulSet", "DaemonSet"], reversible=True),
    "add_node_capacity": ActionSpec(
        id="add_node_capacity", tier=NEVER_AUTO,
        description="Add nodes / fix autoscaler / adjust requests so pending pods can schedule. Human-only.",
        applies_to=["Deployment", "StatefulSet", "DaemonSet", "Job", "Pod"], reversible=True),
    "fix_storage": ActionSpec(
        id="fix_storage", tier=NEVER_AUTO,
        description="Resolve StorageClass/CSI/PV binding problems. Human-only: data safety.",
        applies_to=["PersistentVolumeClaim", "Deployment", "StatefulSet", "Pod"], reversible=False),
    "control_plane_intervention": ActionSpec(
        id="control_plane_intervention", tier=NEVER_AUTO,
        description="etcd, API server, ClusterOperator, MachineConfigPool or certificate work. Human-only.",
        applies_to=["ClusterOperator", "MachineConfigPool", "Node"], reversible=False),
    "grant_scc_or_rbac": ActionSpec(
        id="grant_scc_or_rbac", tier=NEVER_AUTO,
        description="Bind an SCC / RBAC role so the workload can be admitted. Human-only: privilege decision.",
        applies_to=["Deployment", "StatefulSet", "DaemonSet", "Job"], reversible=True),
    "notify_only": ActionSpec(
        id="notify_only", tier=SAFE,
        description="Take no cluster action; send the diagnosis and suggested steps to operators.",
        applies_to=["*"]),
}


def spec(action_id: str) -> Optional[ActionSpec]:
    return CATALOG.get(action_id)


def catalog_for_llm(subject_kind: str, stats_lookup: Callable[[str], Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for a in CATALOG.values():
        if "*" in a.applies_to or subject_kind in a.applies_to:
            entry = {"id": a.id, "tier": a.tier, "description": a.description}
            if a.params_schema:
                entry["params"] = a.params_schema
            history = stats_lookup(a.id)
            if history:
                entry["history"] = history
            out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
class ActionExecutor:
    def __init__(self, client: k.KubeClient, dry_run: bool = False):
        self.client = client
        self.dry_run = dry_run

    def execute(self, action_id: str, finding: Finding, params: Dict[str, Any]) -> ActionResult:
        handler = getattr(self, f"_do_{action_id}", None)
        if handler is None:
            return ActionResult(False, f"action {action_id} has no executor (human-only)")
        try:
            return handler(finding, params or {})
        except k.KubeForbidden as exc:
            return ActionResult(False, f"RBAC forbids {action_id}: {str(exc)[:200]}")
        except k.KubeError as exc:
            return ActionResult(False, f"{action_id} failed: {str(exc)[:300]}")

    # -- helpers -------------------------------------------------------------
    def _stamp(self) -> Dict[str, str]:
        return {RESTART_ANNOTATION: iso(), LAST_ACTION_ANNOTATION: "sre-autoheal"}

    def _pod_name(self, finding: Finding, params: Dict[str, Any]) -> str:
        # The model may name a pod in ``params``, but pod logs are part of its
        # prompt, so that value is untrusted input. Honour it only when it is
        # one of the pods this finding is actually about; otherwise fall back
        # to the detector's own view and record that the suggestion was ignored.
        candidates = set(finding.related_pods or [])
        if finding.resource.kind == "Pod":
            candidates.add(finding.resource.name)
        requested = params.get("pod")
        if requested:
            requested = str(requested)
            if requested in candidates:
                return requested
            logging.getLogger(__name__).warning(
                "ignoring model-supplied pod %r: not among this finding's pods %s",
                requested, sorted(candidates))
        if finding.resource.kind == "Pod":
            return finding.resource.name
        if finding.related_pods:
            return finding.related_pods[0]
        raise k.KubeError("no pod name available for this finding")

    def _ns(self, finding: Finding) -> str:
        ns = finding.subject.namespace or finding.resource.namespace
        if not ns:
            raise k.KubeError("finding has no namespace")
        return ns

    # -- SAFE ----------------------------------------------------------------
    def _do_restart_pod(self, finding: Finding, params: Dict[str, Any]) -> ActionResult:
        ns = self._ns(finding)
        pod = self._pod_name(finding, params)
        ref = k.ref_for_kind("Pod", ns, pod)
        if self.dry_run:
            return ActionResult(True, f"[dry-run] would delete pod {ns}/{pod}", [f"pod/{ns}/{pod}"], dry_run=True)
        self.client.delete(ref)
        return ActionResult(True, f"deleted pod {ns}/{pod}; controller will recreate it", [f"pod/{ns}/{pod}"],
                            rollback_hint="none needed; controller recreates the pod")

    def _do_rollout_restart(self, finding: Finding, params: Dict[str, Any]) -> ActionResult:
        subject = finding.subject
        if subject.kind not in {"Deployment", "StatefulSet", "DaemonSet"}:
            return ActionResult(False, f"rollout_restart does not apply to {subject.kind}")
        ns = self._ns(finding)
        ref = k.ref_for_kind(subject.kind, ns, subject.name)
        body = {"spec": {"template": {"metadata": {"annotations": self._stamp()}}}}
        if self.dry_run:
            return ActionResult(True, f"[dry-run] would rollout restart {subject.short}", [subject.short], dry_run=True)
        self.client.patch(ref, body, k.STRATEGIC_PATCH)
        return ActionResult(True, f"triggered rolling restart of {subject.short}", [subject.short],
                            rollback_hint="rollout completes on its own; use rollout_undo if the new pods fail")

    def _do_delete_evicted_pods(self, finding: Finding, params: Dict[str, Any]) -> ActionResult:
        ns = self._ns(finding)
        # Policy approved this finding's subject, not every workload in its
        # namespace. Never expand that decision to unrelated failed Pods.
        candidates = set(finding.related_pods or [])
        if finding.resource.kind == "Pod":
            candidates.add(finding.resource.name)
        if not candidates:
            return ActionResult(True, "no pods associated with this finding")
        pods = self.client.list(k.ResourceRef("", "v1", "pods", ns))
        targets = []
        for pod in pods:
            if pod.get("metadata", {}).get("name") not in candidates:
                continue
            status = pod.get("status", {})
            phase = status.get("phase")
            reason = status.get("reason", "")
            if phase == "Failed" and reason in {"Evicted", "Terminated", "NodeAffinity", "Shutdown", "UnexpectedAdmissionError"}:
                targets.append(pod["metadata"]["name"])
        if not targets:
            return ActionResult(True, f"no evicted/failed pods to clean for {finding.subject.short}")
        if self.dry_run:
            return ActionResult(True, f"[dry-run] would delete {len(targets)} evicted pods in {ns}", targets, dry_run=True)
        for name in targets:
            self.client.delete(k.ref_for_kind("Pod", ns, name))
        return ActionResult(True, f"deleted {len(targets)} evicted/failed pods in {ns}: {', '.join(targets[:5])}", targets)

    def _do_notify_only(self, finding: Finding, params: Dict[str, Any]) -> ActionResult:
        return ActionResult(True, "no cluster action taken; operators notified")

    # -- MEDIUM --------------------------------------------------------------
    def _do_scale(self, finding: Finding, params: Dict[str, Any]) -> ActionResult:
        subject = finding.subject
        if subject.kind not in {"Deployment", "StatefulSet"}:
            return ActionResult(False, f"scale does not apply to {subject.kind}")
        try:
            replicas = int(params.get("replicas"))
        except (TypeError, ValueError):
            return ActionResult(False, "scale requires integer 'replicas'")
        if replicas < 0 or replicas > 50:
            return ActionResult(False, f"refusing to scale to {replicas} (allowed 0-50)")
        ns = self._ns(finding)
        ref = k.ref_for_kind(subject.kind, ns, subject.name, subresource="scale")
        current = self.client.get(ref)
        before = current.get("spec", {}).get("replicas")
        if self.dry_run:
            return ActionResult(True, f"[dry-run] would scale {subject.short} {before} -> {replicas}", [subject.short], dry_run=True)
        self.client.patch(ref, {"spec": {"replicas": replicas}}, k.MERGE_PATCH)
        return ActionResult(True, f"scaled {subject.short} from {before} to {replicas}", [subject.short],
                            rollback_hint=f"scale back to {before}")

    def _do_rollout_undo(self, finding: Finding, params: Dict[str, Any]) -> ActionResult:
        subject = finding.subject
        if subject.kind != "Deployment":
            return ActionResult(False, "rollout_undo currently supports Deployments only")
        ns = self._ns(finding)
        dep = self.client.get(k.ref_for_kind("Deployment", ns, subject.name))
        current_rev = dep.get("metadata", {}).get("annotations", {}).get("deployment.kubernetes.io/revision")
        rs_list = self.client.list(k.ResourceRef("apps", "v1", "replicasets", ns))
        owned = []
        for rs in rs_list:
            for owner in rs.get("metadata", {}).get("ownerReferences", []) or []:
                if owner.get("kind") == "Deployment" and owner.get("name") == subject.name:
                    rev = rs.get("metadata", {}).get("annotations", {}).get("deployment.kubernetes.io/revision")
                    if rev and rev != current_rev:
                        owned.append((int(rev), rs))
        if not owned:
            return ActionResult(False, "no previous ReplicaSet revision available to roll back to")
        owned.sort(key=lambda t: t[0])
        prev_rev, prev_rs = owned[-1]
        template = prev_rs["spec"]["template"]
        labels = template.get("metadata", {}).get("labels", {})
        labels.pop("pod-template-hash", None)
        if self.dry_run:
            return ActionResult(True, f"[dry-run] would roll back {subject.short} from revision {current_rev} to {prev_rev}",
                                [subject.short], dry_run=True)
        self.client.patch(k.ref_for_kind("Deployment", ns, subject.name), {"spec": {"template": template}}, k.MERGE_PATCH)
        return ActionResult(True, f"rolled back {subject.short} from revision {current_rev} to {prev_rev}", [subject.short],
                            rollback_hint=f"kubectl rollout undo deployment/{subject.name} -n {ns} --to-revision={current_rev}")

    def _do_bump_memory_limit(self, finding: Finding, params: Dict[str, Any]) -> ActionResult:
        subject = finding.subject
        if subject.kind not in {"Deployment", "StatefulSet", "DaemonSet"}:
            return ActionResult(False, f"bump_memory_limit does not apply to {subject.kind}")
        ns = self._ns(finding)
        factor = float(params.get("factor", 1.5))
        factor = max(1.1, min(factor, 4.0))
        container_name = params.get("container") or finding.evidence.get("container")
        obj = self.client.get(k.ref_for_kind(subject.kind, ns, subject.name))
        containers = obj["spec"]["template"]["spec"].get("containers", [])
        target = None
        for c in containers:
            if not container_name or c["name"] == container_name:
                target = c
                break
        if target is None:
            return ActionResult(False, f"container {container_name!r} not found in {subject.short}")
        limits = target.get("resources", {}).get("limits", {})
        current = limits.get("memory")
        if not current:
            return ActionResult(False, "container has no memory limit; refusing to invent one (set requests/limits manually)")
        new_bytes = int(parse_quantity(current) * factor)
        cap = params.get("max_limit")
        if cap and new_bytes > parse_quantity(cap):
            new_bytes = int(parse_quantity(cap))
        new_value = format_mebibytes(new_bytes)
        requests = target.get("resources", {}).get("requests", {})
        patch_resources: Dict[str, Any] = {"limits": {"memory": new_value}}
        if requests.get("memory") and parse_quantity(requests["memory"]) > new_bytes:
            patch_resources["requests"] = {"memory": new_value}
        body = {"spec": {"template": {"spec": {"containers": [{"name": target["name"], "resources": patch_resources}]}}}}
        if self.dry_run:
            return ActionResult(True, f"[dry-run] would raise memory limit of {subject.short}/{target['name']} {current} -> {new_value}",
                                [subject.short], dry_run=True)
        self.client.patch(k.ref_for_kind(subject.kind, ns, subject.name), body, k.STRATEGIC_PATCH)
        return ActionResult(True, f"raised memory limit of {subject.short} container {target['name']} from {current} to {new_value}",
                            [subject.short], rollback_hint=f"set limits.memory back to {current}")

    def _do_force_delete_pod(self, finding: Finding, params: Dict[str, Any]) -> ActionResult:
        ns = self._ns(finding)
        pod = self._pod_name(finding, params)
        if finding.owner and finding.owner.kind == "StatefulSet" and not params.get("allow_statefulset"):
            return ActionResult(False, "refusing to force-delete a StatefulSet pod without allow_statefulset=true")
        if self.dry_run:
            return ActionResult(True, f"[dry-run] would force delete pod {ns}/{pod}", [f"pod/{ns}/{pod}"], dry_run=True)
        self.client.delete(k.ref_for_kind("Pod", ns, pod), grace_period=0)
        return ActionResult(True, f"force deleted pod {ns}/{pod}", [f"pod/{ns}/{pod}"])

    def _set_unschedulable(self, finding: Finding, value: bool) -> ActionResult:
        node = finding.node or (finding.resource.name if finding.resource.kind == "Node" else None)
        if not node:
            return ActionResult(False, "no node name in finding")
        verb = "cordon" if value else "uncordon"
        if self.dry_run:
            return ActionResult(True, f"[dry-run] would {verb} node {node}", [f"node/{node}"], dry_run=True)
        self.client.patch(k.ref_for_kind("Node", None, node), {"spec": {"unschedulable": value}}, k.MERGE_PATCH)
        return ActionResult(True, f"{verb}ed node {node}", [f"node/{node}"],
                            rollback_hint=f"kubectl {'uncordon' if value else 'cordon'} {node}")

    def _do_cordon_node(self, finding: Finding, params: Dict[str, Any]) -> ActionResult:
        return self._set_unschedulable(finding, True)

    def _do_uncordon_node(self, finding: Finding, params: Dict[str, Any]) -> ActionResult:
        return self._set_unschedulable(finding, False)


# ---------------------------------------------------------------------------
# Quantity helpers (subset of Kubernetes resource.Quantity)
# ---------------------------------------------------------------------------
_SUFFIX = {
    "Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4, "Pi": 1024 ** 5,
    "k": 1000, "M": 1000 ** 2, "G": 1000 ** 3, "T": 1000 ** 4, "P": 1000 ** 5, "m": 0.001,
}


def parse_quantity(value: str) -> float:
    value = str(value).strip()
    for suffix in sorted(_SUFFIX, key=len, reverse=True):
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * _SUFFIX[suffix]
    return float(value)


def format_mebibytes(num_bytes: int) -> str:
    mib = max(1, int(round(num_bytes / (1024 ** 2))))
    if mib >= 1024 and mib % 1024 == 0:
        return f"{mib // 1024}Gi"
    return f"{mib}Mi"
