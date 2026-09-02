# Troubleshoot Workflow

Debug and troubleshoot ArgoCD applications - logs, diff, history, rollback.

## Kubeconfig Reference

All kubectl commands in this workflow use the example-app-hub cluster kubeconfig:
```bash
export KUBECONFIG=~/.kube/aks-rg-example-hub-config
# Or use: kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config ...
```

## Quick Diagnostics

| Issue | Command |
|-------|---------|
| App status | `argocd app get <name>` |
| Sync issues | `argocd app diff <name>` |
| Pod logs | `argocd app logs <name>` |
| History | `argocd app history <name>` |
| Rollback | `argocd app rollback <name> <id>` |

## Application Status Check

```bash
# Get full application status
argocd app get <app-name>

# Get health status only
argocd app get <app-name> -o json | jq '.status.health'

# Get sync status only
argocd app get <app-name> -o json | jq '.status.sync'

# Get conditions (errors/warnings)
argocd app get <app-name> -o json | jq '.status.conditions'

# Get operation state
argocd app get <app-name> -o json | jq '.status.operationState'

# List all resources and their status
argocd app resources <app-name>
```

## Application Logs

```bash
# Get logs from all pods
argocd app logs <app-name>

# Follow logs (live)
argocd app logs <app-name> --follow

# Get logs from specific container
argocd app logs <app-name> -c <container-name>

# Get logs from specific group/kind/name
argocd app logs <app-name> --group "" --kind Deployment --name <deployment-name>

# Get logs since timestamp
argocd app logs <app-name> --since-time "2024-01-01T00:00:00Z"

# Get logs for specific duration
argocd app logs <app-name> --since 1h

# Get previous container logs (crashed pods)
argocd app logs <app-name> --previous

# Tail last N lines
argocd app logs <app-name> --tail 100
```

## Diff & Manifests

### Show Diff

```bash
# Show diff between live and target state
argocd app diff <app-name>

# Show diff with local manifests
argocd app diff <app-name> --local /path/to/manifests

# Show diff for specific revision
argocd app diff <app-name> --revision <git-sha>

# Diff with server-side dry run
argocd app diff <app-name> --server-side-generate
```

### Get Manifests

```bash
# Get rendered manifests
argocd app manifests <app-name>

# Get as JSON
argocd app manifests <app-name> -o json

# Get source manifests (from git)
argocd app manifests <app-name> --source

# Get live manifests (from cluster)
argocd app manifests <app-name> --live
```

## History & Rollback

### View History

```bash
# View deployment history
argocd app history <app-name>

# Get specific revision details
argocd app history <app-name> --revision <id>
```

### Rollback

```bash
# Rollback to specific revision
argocd app rollback <app-name> <revision-id>

# Rollback with prune
argocd app rollback <app-name> <revision-id> --prune

# Example: rollback to revision 5
argocd app rollback grafana 5
```

## Sync Troubleshooting

### Check Sync Status

```bash
# Get sync result
argocd app get <app-name> -o json | jq '.status.sync'

# Get sync operation result
argocd app get <app-name> -o json | jq '.status.operationState.syncResult'

# List out-of-sync resources
argocd app get <app-name> -o json | jq '.status.resources[] | select(.status != "Synced")'
```

### Force Sync

```bash
# Hard refresh (clear cache)
argocd app get <app-name> --hard-refresh

# Force sync with replace
argocd app sync <app-name> --force

# Sync specific out-of-sync resources
argocd app sync <app-name> --resource :Deployment:my-deployment

# Retry failed sync
argocd app sync <app-name> --retry-limit 5 --retry-backoff-duration 10s
```

### Terminate Operation

```bash
# Terminate running sync operation
argocd app terminate-op <app-name>
```

## Resource Troubleshooting

### Get Resource Details

```bash
# List all resources
argocd app resources <app-name>

# Get specific resource
argocd app get-resource <app-name> \
  --resource-name <name> \
  --kind <kind> \
  --namespace <namespace>

# Get resource as JSON
argocd app get-resource <app-name> \
  --resource-name <name> \
  --kind Deployment \
  -o json
```

### Patch Resource

```bash
# Patch resource directly
argocd app patch-resource <app-name> \
  --resource-name <name> \
  --kind Deployment \
  --patch '{"spec":{"replicas":3}}'
```

### Delete Resource

```bash
# Delete stuck resource
argocd app delete-resource <app-name> \
  --resource-name <name> \
  --kind <kind>

# Force delete
argocd app delete-resource <app-name> \
  --resource-name <name> \
  --kind <kind> \
  --force
```

## Common Issues & Solutions

### Sync Failed - Resource Already Exists

```bash
# Check for orphaned resources
argocd app get <app-name> -o json | jq '.status.resources[] | select(.status == "OutOfSync")'

# Force replace
argocd app sync <app-name> --force --replace
```

### Out of Sync - Hooks Pending

```bash
# Skip hooks
argocd app sync <app-name> --skip-hooks

# Or delete pending hooks
argocd app delete-resource <app-name> --kind Job --resource-name <hook-job-name>
```

### Health Degraded

```bash
# Check pod status
argocd app logs <app-name>

# Get events (example-app-hub)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config get events -n <namespace> --sort-by='.lastTimestamp'

# Describe failing pods (example-app-hub)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config describe pod -n <namespace> -l app.kubernetes.io/instance=<app-name>
```

### ComparisonError

```bash
# Hard refresh to clear cache
argocd app get <app-name> --hard-refresh

# Check repo server (example-app-hub)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -f
```

### Permission Denied

```bash
# Check project permissions
argocd proj get <project-name>

# Verify destinations
argocd proj get <project-name> -o json | jq '.spec.destinations'

# Check cluster access
argocd cluster get <cluster-server>
```

## ArgoCD Server Logs

```bash
# Application controller logs (example-app-hub)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f

# Repo server logs (example-app-hub)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -f

# API server logs (example-app-hub)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config logs -n argocd -l app.kubernetes.io/name=argocd-server -f

# ApplicationSet controller logs (example-app-hub)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller -f

# Filter for specific app (example-app-hub)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f | grep <app-name>
```

## Health Check Scripts

### Check All Apps Health

```bash
# List unhealthy apps
argocd app list -o json | jq '.[] | select(.status.health.status != "Healthy") | {name: .metadata.name, health: .status.health.status, sync: .status.sync.status}'

# List out-of-sync apps
argocd app list -o json | jq '.[] | select(.status.sync.status != "Synced") | {name: .metadata.name, health: .status.health.status, sync: .status.sync.status}'
```

### Quick Health Summary

```bash
#!/bin/bash
echo "=== ArgoCD Application Health Summary ==="
echo ""
echo "Total Apps: $(argocd app list -o json | jq length)"
echo "Healthy: $(argocd app list -o json | jq '[.[] | select(.status.health.status == "Healthy")] | length')"
echo "Degraded: $(argocd app list -o json | jq '[.[] | select(.status.health.status == "Degraded")] | length')"
echo "Synced: $(argocd app list -o json | jq '[.[] | select(.status.sync.status == "Synced")] | length')"
echo "OutOfSync: $(argocd app list -o json | jq '[.[] | select(.status.sync.status == "OutOfSync")] | length')"
```

## Notifications & Webhooks

```bash
# Check notification controller (example-app-hub)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config logs -n argocd -l app.kubernetes.io/name=argocd-notifications-controller -f

# Test webhook
curl -X POST https://argocd.example.com/api/webhook \
  -H "Content-Type: application/json" \
  -d '{"ref": "refs/heads/main"}'
```
