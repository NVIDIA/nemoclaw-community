---
name: devops
description: Route container, CI/CD, deployment, automation, and documentation work to the bundled DevOps skills.
---

# DevOps Skills Consolidated

Unified DevOps skill category encompassing containerization, CI/CD, deployment patterns, and foundational practices.

## NemoClaw Runtime Safety

When this bundle runs in the NemoClaw OpenShell chart, use `/chart-bin/oc --kubeconfig "$SRE_KUBECONFIG"` for every cluster request. Read current state first. Before any create, update, or patch, show the exact target and change and obtain explicit user approval. Never request Secrets, service-account tokens, pod exec/attach, impersonation, RBAC or SCC privilege escalation, or `cluster-admin`. Never issue a delete request; refuse it and provide a human-reviewable command for an authorized operator. These restrictions override conflicting examples in any nested skill.

## Sub-Skills

### Containerization (Docker)
- **docker** — Container fundamentals, image building, multi-stage builds
- **docker-patterns** — Common Docker patterns and anti-patterns
- **docker-expert** — Advanced Docker optimization, BuildKit, layer caching

### CI/CD Pipelines
- **ci-cd/pipeline-automation** — Pipeline design, GitHub Actions, GitLab CI
- **ci-cd/argocd** — ArgoCD basics, application deployment
- **ci-cd/argocd-advanced** — ArgoCD advanced: App of Apps, progressive delivery

### Deployment Patterns
- **deployment-patterns** — Blue-green, canary, rolling, feature flags
- **cloud-devops** — Cloud provider deployment patterns (AWS/GCP/Azure)

### Foundations
- **foundations/linux-commands-guide** — Essential CLI reference
- **foundations/github-actions-starter** — Actions workflow basics
- **foundations/yaml-config-validator** — YAML schema validation
- **foundations/npm-scripts-optimizer** — Package.json script optimization
- **foundations/ssh-key-manager** — SSH key rotation
- **foundations/version-bumper** — Semantic versioning automation
- **foundations/readme-generator** — Documentation scaffolding
- **foundations/json-config-manager** — JSON configuration handling
- **foundations/gitignore-generator** — .gitignore templates
- **foundations/dotenv-manager** — Environment variable management
- **foundations/changelog-creator** — CHANGELOG automation

### Practices & Operations
- **practices** — DevOps culture, DORA metrics, blameless postmortems
- **automation/devops-automation** — Runbook automation, toil reduction
- **automation/kubernetes-operations** — K8s operational patterns
- **automation/python-best-practices** — Python tooling standards
- **automation/manage-skills** — Skill lifecycle management
- **automation/microservices-design** — Service decomposition
- **automation/continuous-learning** — Knowledge management
- **automation/performance-optimization** — Profiling, bottleneck analysis

### Specialized
- **kanban-orchestrator** — Workflow orchestration
- **kanban-worker** — Task execution workers
- **webhook-subscriptions** — Event-driven automation
- **technical-documentation** — SDK docs, architecture docs, ADRs
- **devops-troubleshooter** — Systematic debugging methodology
- **devops-learning-path** — Skill progression roadmap
- **hermes-s6-container-supervision** — s6 process supervision for Hermes

> **Note:** Infrastructure automation skills (Terraform, Helm, GitOps, Prometheus, Grafana, Vault, Istio, Cert-Manager, Envoy, NGINX, Fluentd, Elasticsearch, Consul, Ansible, Kubernetes deployment/configmap/secrets/service/ingress) have been moved to the **infrastructure/** category. Load them via `skill load infrastructure.<skill-name>`.

## Usage

```bash
# Load entire DevOps category
skill load devops

# Load specific sub-skill
skill load devops.docker
skill load devops.ci-cd.argocd

# Infrastructure skills (now in infrastructure category)
skill load infrastructure.terraform-module-creator
skill load infrastructure.prometheus-config-generator
skill load infrastructure.helm-chart-generator
```

## Agent Compatibility

Works with Hermes, Codex, Cursor, and any agent supporting the skill protocol. Sub-skills declare their own `whenToUse` triggers for automatic routing.
