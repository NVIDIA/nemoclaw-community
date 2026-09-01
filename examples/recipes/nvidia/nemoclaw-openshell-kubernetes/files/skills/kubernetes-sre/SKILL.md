---
name: kubernetes-sre
description: Inspect Kubernetes or OpenShift resources and perform only the mutations exposed by the chart-managed SRE API proxy.
---

# Kubernetes SRE

Use `KUBERNETES_SRE_API` as the Kubernetes API base URL. Authenticate each request with `Authorization: Bearer $(cat /sandbox/.hermes/.sre-proxy-token)`. Never print, return, log, or send that token anywhere else; the proxy replaces it with its own Kubernetes ServiceAccount credential.

1. Inspect current state before proposing any mutation.
2. Prefer `GET` discovery, status, events, and logs. In safe mode, mutate only the `/scale` subresource of a namespaced Deployment or StatefulSet; full workload patches are forbidden.
3. Never send `DELETE` or request deletion through another workload. The proxy rejects DELETE and the service account has no delete verbs.
4. If asked to delete, refuse and provide the exact resource identity plus a human-reviewable `kubectl delete ...` command. Do not grant RBAC, SCC, `cluster-admin`, impersonation, or service-account tokens.
5. Treat `broad-no-delete` as dangerous: create/update/patch can still cause outages or privilege escalation. Require explicit user confirmation for each mutation and show the exact API object delta first.

The base URL is an authenticated HTTP endpoint inside the OpenShell-enforced sandbox network policy. Typical discovery paths are `/api/v1/namespaces` and `/apis/apps/v1/deployments`.
