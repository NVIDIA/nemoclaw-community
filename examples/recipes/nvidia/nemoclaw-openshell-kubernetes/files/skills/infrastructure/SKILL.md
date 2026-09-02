---
name: infrastructure
description: Route Kubernetes, OpenShift, SRE, observability, and infrastructure automation work to the bundled skills.
---

# Infrastructure Skills Consolidated

Unified Infrastructure skill category covering Kubernetes, OpenShift, SRE, and platform automation (Terraform, Helm, GitOps, monitoring, networking, secrets).

## NemoClaw Runtime Safety

When this bundle runs in the NemoClaw OpenShell chart, use `/chart-bin/oc --kubeconfig "$SRE_KUBECONFIG"` for every cluster request. Read current state first. Before any create, update, or patch, show the exact target and change and obtain explicit user approval. Never request Secrets, service-account tokens, pod exec/attach, impersonation, RBAC or SCC privilege escalation, or `cluster-admin`. Never issue a delete request; refuse it and provide a human-reviewable command for an authorized operator. The separately enabled `openshift-llm-deploy` skill may use only its exact, namespace-scoped model deletion proxy. These restrictions override conflicting examples in any nested skill.

## Sub-Categories

### Kubernetes
- **fundamentals** — Core concepts: pods, services, deployments, RBAC, networking
- **operations** — Day-2 operations: scaling, rolling updates, debugging, backup/restore
- **cluster-operations** — Multi-cluster management, fleet operations
- **platform-automation** — Manifest templating, security policies, GitOps, Helm scaffolding
- **platform-management** — Deployments, cluster admin, Helm, service mesh, monitoring, GitOps, storage, cost optimization, troubleshooting, multi-cluster
- **troubleshooting** — Systematic failure analysis, root cause analysis
- **advanced-patterns** — Operators, controllers, CRDs, deployment patterns, cluster architecture, Knative

### OpenShift
- **openshift-llm-deploy** — Complete LLM deployment on OpenShift
  - Templates: Dynamo/vLLM GraphDeployment, TensorRT-LLM, standard vLLM, model-download-job, dynamo-podmonitor
  - Scripts: deploy-model.sh, dynamo-first-deploy.sh, diagnose-deployment.sh, verify-openai-endpoint.sh, resolve-vllm-image.sh, resolve-dynamo-image.sh, list-storage-classes.sh, gpu-metrics.sh, query-metrics.sh, remove-model.sh, cluster-status.sh
- **openshift-operations** — OpenShift-specific operations
- **popeye-analysis** — OpenShift cluster security/conformance scans

### SRE
- **incident-response** — Commander, responder, core lifecycle, advanced patterns, smart fix, runbook templates
- **observability** — Full stack: Prometheus, Grafana, Loki, OpenTelemetry, consulting, implementation
- **observability-setup** — Bootstrap observability stack from scratch
- **runbooks** — Runbook creator, production readiness reviews
- **operations** — SRE practices (SLO/SLI, error budgets), infrastructure orchestration

### Platform Automation (Terraform, Helm, GitOps, Monitoring, Networking, Secrets)
- **terraform-module-creator** — Terraform module scaffolding
- **terraform-provider-config** — Provider configuration
- **terraform-state-manager** — State management
- **helm-chart-generator** — Helm chart scaffolding
- **helm-values-manager** — Values file management
- **flux-gitops-setup** — Flux GitOps bootstrap
- **argocd-app-deployer** — ArgoCD application deployment
- **prometheus-config-generator** — Prometheus rules, scrape configs
- **grafana-dashboard-creator** — Dashboard generation
- **alertmanager-rules-config** — Alert routing, inhibition
- **vault-secrets-integrator** — Vault secret injection
- **istio-service-mesh-config** — Istio configuration
- **cert-manager-setup** — Certificate management
- **envoy-proxy-config** — Envoy proxy configuration
- **nginx-ingress-manager** — NGINX ingress controller
- **fluentd-config-generator** — Log aggregation
- **elasticsearch-index-manager** — ES index lifecycle
- **consul-service-discovery** — Service mesh integration
- **ansible-role-creator** — Ansible role generation
- **ansible-playbook-generator** — Ansible playbook scaffolding
- **kubernetes-deployment-creator** — K8s deployment manifests
- **kubernetes-configmap-handler** — ConfigMap management
- **kubernetes-secrets-manager** — Secrets management
- **kubernetes-service-manager** — Service management
- **kubernetes-ingress-config** — Ingress controllers

## Usage

```bash
# Load entire Infrastructure category
skill load infrastructure

# Load specific sub-category
skill load infrastructure.kubernetes
skill load openshift-llm-deploy
skill load infrastructure.sre

# Load specific sub-skill
skill load infrastructure.kubernetes.operations
skill load openshift-llm-deploy
skill load infrastructure.sre.incident-commander
skill load infrastructure.terraform-module-creator
skill load infrastructure.prometheus-config-generator
```

## Key Features

- **Kubernetes Native** — Fundamentals through advanced platform management
- **OpenShift LLM Deploy** — NVIDIA Dynamo, vLLM, TensorRT-LLM with GPU awareness
- **SRE Complete** — Incident response, observability, runbooks, production readiness
- **IaC & GitOps** — Terraform, Helm, Flux, ArgoCD, service mesh
- **Observability Stack** — Prometheus, Grafana, Loki, OpenTelemetry, Alertmanager

## Monitoring & Observability Integration

The `openshift-llm-deploy` skill includes built-in monitoring integration:
- **DCGM GPU Telemetry** — `gpu-metrics.sh` queries Thanos for GPU utilization, memory, power, temperature
- **Serving Metrics** — `query-metrics.sh` for PromQL queries (queue depth, KV-cache, TTFT, tokens/sec)
- **PodMonitor** — `dynamo-podmonitor.yaml` template for user-workload monitoring
- **Requires** `enableUserWorkload: true` in cluster monitoring config

## Agent Compatibility

Works with Hermes, Codex, Cursor, and any agent supporting the skill protocol. Sub-skills declare their own `whenToUse` triggers for automatic routing.
