---
name: sre-openshift-operations
description: Safely investigate OpenShift cluster, node, operator, upgrade, and workload problems using read-only evidence before approved remediation.
---

# OpenShift Operations

Use this skill for OpenShift node health, operator degradation, upgrade
readiness, or workload troubleshooting.

1. Identify the cluster, namespace, workload, and impact. Confirm whether a
   maintenance window or active incident applies.
2. Inspect cluster operators, nodes, events, workloads, and recent changes with
   read-only commands first.
3. Distinguish control-plane, node, operator, networking, storage, and
   application failures. Capture evidence before proposing remediation.
4. For upgrades, validate preconditions, blockers, disruption budget, rollback
   or pause criteria, and the expected verification signal.
5. Ask for explicit approval before any restart, drain, scaling action, upgrade,
   or configuration mutation.

This is original Hermes guidance informed by the requested OpenShift operations
plugin layout from `redhat-community-ai-tools/claude-plugins`.
