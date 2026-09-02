---
name: kubernetes
description: Route Kubernetes architecture, operations, troubleshooting, and platform-management work to bundled skills.
---

# Kubernetes Skills Consolidated

Unified Kubernetes skill category covering fundamentals, operations, troubleshooting, platform management, and advanced patterns.

## NemoClaw Runtime Safety

Use `/chart-bin/oc --kubeconfig "$SRE_KUBECONFIG"` for cluster requests. Inspect first and require explicit approval before create, update, or patch. Never read Secrets or service-account tokens, use pod exec/attach, impersonate identities, grant RBAC/SCC privileges, or issue DELETE. Refuse deletion requests and provide an exact human-run command for an authorized operator. These restrictions override conflicting nested examples.

## Sub-Skills

### Fundamentals
- **fundamentals/k8s** — Core concepts: pods, services, deployments, RBAC, networking

### Operations
- **operations** — Day-2 operations: scaling, rolling updates, debugging, backup/restore
- **cluster-operations** — Multi-cluster management, fleet operations
  - **cluster-operations/orchestrator** — Cluster lifecycle orchestration
  - **cluster-operations/k8s-operations** — Operational runbooks
  - **cluster-operations/k8s-troubleshooting** — Cluster-level debugging
  - **cluster-operations/observability** — Cluster monitoring
  - **cluster-operations/k8s-gitops** — GitOps at cluster level
  - **cluster-operations/cluster-dev-guidelines** — Developer guidelines
  - **cluster-operations/k8s-security** — Cluster hardening
  - **cluster-operations/openshift-popeye-analysis** — Popeye cluster scans

### Platform Automation
- **platform-automation/k8s-manifest-generator** — Manifest templating
- **platform-automation/k8s-security-policies** — PSP/OPA/Gatekeeper
- **platform-automation/gitops-workflow** — ArgoCD/Flux patterns
- **platform-automation/helm-chart-scaffolding** — Chart development

### Platform Management
- **platform-management/deployments** — Deployment strategies
- **platform-management/cluster-admin** — Admin tasks, certificates, etcd
- **platform-management/helm** — Helm 3 patterns, dependencies
- **platform-management/docker-containers** — Container runtime config
- **platform-management/service-mesh** — Istio/Linkerd/Cilium
- **platform-management/monitoring** — Prometheus Operator, rules
- **platform-management/gitops** — Repository structure, sync policies
- **platform-management/storage-networking** — CSI, CNI, Ingress
- **platform-management/cost-optimization** — VPA, HPA, cluster autoscaler
- **platform-management/troubleshooting** — Systematic cluster debugging
- **platform-management/multi-cluster** — Cluster federation

### Troubleshooting
- **kubernetes-troubleshooting** — Systematic failure analysis methodology
- **failure-analysis** — Root cause analysis for pod/node/cluster failures

### Advanced Patterns
- **kubernetes-patterns** — Operators, controllers, CRDs, admission webhooks
- **kubernetes-deployment** — Advanced deployment patterns
- **kubernetes-architect** — Cluster architecture design, HA, topology
- **kubernetes-skill** — Comprehensive K8s skill (assets, docs, references)
- **knative** — Serverless on K8s: Serving, Eventing, Functions

## Usage

```bash
# Load entire Kubernetes category
skill load kubernetes

# Load specific sub-skill
skill load kubernetes.operations
skill load kubernetes.platform-management.service-mesh
skill load kubernetes.kubernetes-patterns
skill load kubernetes.knative
```

## Agent Compatibility

Works with Hermes, Codex, Cursor, and any agent supporting the skill protocol. Sub-skills declare their own `whenToUse` triggers for automatic routing.
