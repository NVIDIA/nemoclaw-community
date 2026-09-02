# TroubleshootSync Workflow

**Diagnose and resolve ArgoCD sync failures.**

## When to Use

- Sync operation failed
- App stuck in "Syncing" state
- Resources not deploying as expected
- Mysterious OutOfSync status

## Workflow Steps

### Step 1: Get Sync Operation Details

```bash
# Show sync operation status
argocd app get <app-name> --show-operation

# Get detailed operation state
argocd app get <app-name> -o json | jq '.status.operationState'
```

### Step 2: Identify Failed Resources

```bash
# List resources with their sync status
argocd app resources <app-name> --tree

# Filter for problematic resources
argocd app get <app-name> -o json | jq '.status.resources[] | select(.status != "Synced" or .health.status != "Healthy")'
```

### Step 3: Check Sync Result Messages

```bash
# Get sync result with error messages
argocd app get <app-name> -o json | jq '.status.operationState.syncResult'

# Check resource-level messages
argocd app get <app-name> -o json | jq '.status.operationState.syncResult.resources[] | select(.message != null)'
```

### Step 4: Refresh from Git

Sometimes the issue is stale Git state:

```bash
# Hard refresh from Git
argocd app get <app-name> --refresh --hard-refresh
```

## Common Sync Issues & Solutions

### Issue 1: "cannot patch ... field is immutable"

**Cause**: Trying to change an immutable field (like Service ClusterIP)

**Solution**:
```bash
# Option 1: Replace the resource
argocd app sync <app-name> --resource :Service:<name> --replace

# Option 2: Delete and let it recreate
kubectl delete service <name> -n <namespace>
argocd app sync <app-name>
```

### Issue 2: "exceeded quota"

**Cause**: Resource quota exceeded in namespace

**Solution**:
```bash
# Check quotas
kubectl describe resourcequota -n <namespace>

# Either increase quota or reduce resource requests
```

### Issue 3: "webhook denied the request"

**Cause**: Admission webhook rejected the resource

**Solution**:
```bash
# Check webhook configurations
kubectl get validatingwebhookconfigurations
kubectl get mutatingwebhookconfigurations

# Review webhook logs
kubectl logs -n <webhook-namespace> -l <webhook-labels>
```

### Issue 4: "context deadline exceeded"

**Cause**: Sync timeout (default 180s)

**Solution**:
```bash
# Increase timeout
argocd app sync <app-name> --timeout 600

# Or sync specific resources first
argocd app sync <app-name> --resource :ConfigMap:*
argocd app sync <app-name> --resource :Secret:*
argocd app sync <app-name>
```

### Issue 5: App Stuck in "Progressing"

**Cause**: Usually a Deployment not reaching ready state

**Solution**:
```bash
# Find progressing resources
argocd app get <app-name> -o json | jq '.status.resources[] | select(.health.status == "Progressing")'

# Check pod status
kubectl get pods -n <namespace> -l app.kubernetes.io/instance=<app-name>

# Check events
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | tail -20

# Check pod logs
argocd app logs <app-name>
```

## Force Sync Options (Use Carefully)

```bash
# Force sync - replaces resources
argocd app sync <app-name> --force

# Force with prune - also deletes orphaned resources
argocd app sync <app-name> --force --prune

# Skip schema validation
argocd app sync <app-name> --validate=false
```

## Resetting App State

If sync is completely stuck:

```bash
# Terminate current operation
argocd app terminate-op <app-name>

# Wait a moment, then try sync again
argocd app sync <app-name>
```
