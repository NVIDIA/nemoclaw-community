---
name: openshift-llm-deploy
description: Inspect and remove only model-serving resources in the namespace explicitly delegated by the Helm operator.
---

# OpenShift LLM Deploy

Use `OPENSHIFT_LLM_DELETE_ENDPOINT` only for the namespace in `OPENSHIFT_LLM_DELETE_NAMESPACE`. Authenticate with the bearer token at `/sandbox/.hermes/.sre-proxy-token`, and never print, return, log, or send that token anywhere else.

- Parse `OPENSHIFT_LLM_DELETE_ALLOWED_RESOURCES` and proceed only when the exact `apiGroup`, plural `resource`, and `name` tuple is present. This operator allowlist is the authorization boundary.
- Before deletion, list the candidate model resources and verify they were created by this workflow.
- Show the exact resource names and ask the user for explicit confirmation.
- Delete only model-serving resources in the delegated namespace. Never delete namespaces, RBAC, SCC, operators, CRDs, nodes, storage classes, or cluster-scoped resources.
- PVCs and Secrets are excluded unless the chart operator separately enabled those resource types.
- Stop if ownership is ambiguous or the requested namespace differs from `OPENSHIFT_LLM_DELETE_NAMESPACE`.

This permission is separate from the general SRE proxy and does not grant cluster-admin.
