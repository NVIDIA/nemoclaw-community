---
name: argocd-review
description: ArgoCD application review and troubleshooting via CLI. USE WHEN argocd app, sync status, health check, application diff, rollback, deployment history, GitOps troubleshooting. Provides commands for reviewing applications, comparing live vs desired state, and diagnosing sync failures.
---

# ArgoCDReview - ArgoCD CLI Review & Troubleshooting

**Comprehensive ArgoCD CLI commands for reviewing applications, diagnosing issues, and managing deployments.**

This skill provides structured commands for inspecting ArgoCD application state, comparing live manifests against Git, reviewing deployment history, and troubleshooting sync failures.

---

## Prerequisites

- ArgoCD CLI installed (`argocd`)
- Logged into ArgoCD server: `argocd login <server>`
- Context set if using multiple clusters

```bash
# Verify connection
argocd version
argocd account get-user-info
```

---

## Quick Reference Commands

### Application Status Overview

```bash
# List all applications with status
argocd app list

# Get detailed app status (health, sync, resources)
argocd app get <app-name>

# Get app status as JSON (for scripting)
argocd app get <app-name> -o json

# Wide output with more columns
argocd app list -o wide
```

### Health & Sync Status

```bash
# Check sync status only
argocd app get <app-name> --show-operation

# List all OutOfSync applications
argocd app list --sync-status OutOfSync

# List all Degraded applications
argocd app list --health-status Degraded

# List applications by project
argocd app list --project <project-name>
```

---

## Workflow Routing

| Workflow | Trigger | File |
|----------|---------|------|
| **ReviewApplication** | "review app", "check app status", "app health" | `Workflows/ReviewApplication.md` |
| **DiffManifests** | "diff app", "compare live vs desired", "what changed" | `Workflows/DiffManifests.md` |
| **TroubleshootSync** | "sync failed", "why not syncing", "sync errors" | `Workflows/TroubleshootSync.md` |
| **RollbackApp** | "rollback", "revert deployment", "previous version" | `Workflows/RollbackApp.md` |
| **ReviewResources** | "list resources", "app resources", "managed resources" | `Workflows/ReviewResources.md` |

---

## Core Review Operations

### 1. Application Diff (Live vs Desired)

Compare what's deployed vs what Git says should be deployed:

```bash
# Show diff between live state and Git
argocd app diff <app-name>

# Show diff with local manifests
argocd app diff <app-name> --local <repo-path>

# Server-side manifest generation (recommended for Helm/Kustomize)
argocd app diff <app-name> --local <repo-root> --server-side-generate
```

### 2. View Application Manifests

```bash
# Show desired manifests (from Git)
argocd app manifests <app-name>

# Show live manifests (from cluster)
argocd app manifests <app-name> --source live

# Get specific resource manifest
argocd app get-resource <app-name> \
  --kind Deployment \
  --name <deployment-name> \
  --namespace <namespace>
```

### 3. Deployment History

```bash
# View deployment history
argocd app history <app-name>

# Output example:
# ID  DATE                           REVISION
# 0   2025-01-10 10:00:00 +0000 UTC  abc1234 (HEAD)
# 1   2025-01-09 15:30:00 +0000 UTC  def5678 (v1.2.0)
# 2   2025-01-08 09:00:00 +0000 UTC  789abcd (v1.1.0)
```

### 4. Resource Tree & Details

```bash
# Show resource tree
argocd app resources <app-name>

# Show resource tree with health status
argocd app resources <app-name> --tree

# Get specific resource details
argocd app get-resource <app-name> \
  --resource-name <resource> \
  --kind <kind>
```

---

## Sync Operations

### Safe Sync (Preview First)

```bash
# Preview what would sync (dry-run)
argocd app sync <app-name> --dry-run

# Sync single application
argocd app sync <app-name>

# Sync and wait for completion
argocd app sync <app-name> --wait

# Sync specific resources only
argocd app sync <app-name> --resource :Service:my-service
argocd app sync <app-name> --resource apps:Deployment:my-deployment
```

### Selective Sync

```bash
# Sync by label selector
argocd app sync -l app.kubernetes.io/instance=my-app

# Sync multiple apps
argocd app sync app1 app2 app3

# Sync excluding specific resources
argocd app sync <app-name> --resource '!apps:Deployment:skip-this'
```

### Force Sync (Use with Caution)

```bash
# Force sync (replaces resources)
argocd app sync <app-name> --force

# Force sync with prune (deletes removed resources)
argocd app sync <app-name> --prune --force

# Sync with replace strategy
argocd app sync <app-name> --replace
```

---

## Rollback Operations

```bash
# View history first
argocd app history <app-name>

# Rollback to specific history ID
argocd app rollback <app-name> <history-id>

# Rollback without confirmation
argocd app rollback <app-name> <history-id> --yes

# Rollback and wait for completion
argocd app rollback <app-name> <history-id> --timeout 300
```

---

## Troubleshooting Commands

### Sync Failure Diagnosis

```bash
# Get detailed sync operation status
argocd app get <app-name> --show-operation

# View sync operation result
argocd app get <app-name> -o json | jq '.status.operationState'

# Check for resource errors
argocd app resources <app-name> --tree | grep -E "(Degraded|Progressing|Missing)"
```

### Application Logs

```bash
# View logs for app's pods
argocd app logs <app-name>

# Follow logs
argocd app logs <app-name> -f

# Logs for specific container
argocd app logs <app-name> \
  --container <container-name>

# Logs for specific group/kind
argocd app logs <app-name> \
  --kind Deployment \
  --name <deployment-name>
```

### Resource Events

```bash
# Get Kubernetes events for app resources
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | grep <app-name>
```

---

## Common Diagnostic Scenarios

### Scenario 1: App Stuck in "Progressing"

```bash
# 1. Check what's progressing
argocd app resources <app-name> --tree

# 2. Find stuck resources (usually Deployments)
argocd app get <app-name> -o json | jq '.status.resources[] | select(.health.status == "Progressing")'

# 3. Check pod events
kubectl describe deployment <deployment-name> -n <namespace>
kubectl get pods -n <namespace> | grep <app-name>
```

### Scenario 2: App Shows "OutOfSync" but Won't Sync

```bash
# 1. Check diff
argocd app diff <app-name>

# 2. Check for ignored differences
argocd app get <app-name> -o json | jq '.spec.ignoreDifferences'

# 3. Check sync policy
argocd app get <app-name> -o json | jq '.spec.syncPolicy'

# 4. Force refresh from Git
argocd app get <app-name> --refresh
```

### Scenario 3: Health Status "Degraded"

```bash
# 1. Find unhealthy resources
argocd app resources <app-name> --tree

# 2. Get resource details
argocd app get-resource <app-name> \
  --kind <kind> \
  --name <name>

# 3. Check pod status
kubectl get pods -n <namespace> -l app.kubernetes.io/instance=<app-name>
kubectl describe pod <pod-name> -n <namespace>
```

---

## Multi-Source Applications

For applications with multiple sources:

```bash
# Sync with specific source revisions
argocd app sync <app-name> \
  --revisions v1.0.0 --source-positions 1 \
  --revisions v2.0.0 --source-positions 2

# Sync by source name
argocd app sync <app-name> \
  --revisions v1.0.0 --source-names helm-chart \
  --revisions main --source-names values-repo
```

---

## Best Practices Checklist

- [ ] Always run `argocd app diff` before syncing
- [ ] Use `--dry-run` for sync operations in production
- [ ] Check deployment history before rollback
- [ ] Review resource tree when troubleshooting health
- [ ] Use JSON output for scripting: `-o json`
- [ ] Set appropriate timeouts for sync operations

---

## Examples

**Example 1: Review failing application**
```
User: "Why is my-app not healthy?"
→ Run argocd app get my-app --show-operation
→ Check argocd app resources my-app --tree
→ Identify Degraded resources
→ Investigate with kubectl describe
```

**Example 2: Compare live vs desired state**
```
User: "What changed in production?"
→ Run argocd app diff my-app
→ Shows line-by-line diff
→ Identify configuration drift
```

**Example 3: Rollback after bad deployment**
```
User: "Rollback my-app to previous version"
→ Run argocd app history my-app
→ Identify target history ID
→ Run argocd app rollback my-app <id>
→ Verify with argocd app get my-app
```

---

## Related Tools

- **kubectl**: For direct cluster inspection
- **k9s**: Interactive Kubernetes dashboard
- **stern**: Multi-pod log tailing
- **kubectx/kubens**: Context and namespace switching
