# ReviewResources Workflow

**Inspect resources managed by an ArgoCD application.**

## When to Use

- Understanding what resources an app manages
- Checking specific resource health
- Debugging resource-level issues
- Auditing managed resources

## Workflow Steps

### Step 1: List All Managed Resources

```bash
# Simple list
argocd app resources <app-name>

# Tree view with health status
argocd app resources <app-name> --tree
```

### Step 2: Get Resource Details

```bash
# Get specific resource manifest (live state)
argocd app get-resource <app-name> \
  --kind <kind> \
  --name <name> \
  --namespace <namespace>

# With group (for CRDs)
argocd app get-resource <app-name> \
  --group argoproj.io \
  --kind Rollout \
  --name <name>
```

### Step 3: Filter Resources

```bash
# Get all Deployments
argocd app get <app-name> -o json | jq '.status.resources[] | select(.kind == "Deployment")'

# Get unhealthy resources
argocd app get <app-name> -o json | jq '.status.resources[] | select(.health.status != "Healthy")'

# Get resources with sync issues
argocd app get <app-name> -o json | jq '.status.resources[] | select(.status != "Synced")'
```

### Step 4: View Resource Manifests

```bash
# Desired manifests (from Git)
argocd app manifests <app-name>

# Live manifests (from cluster)
argocd app manifests <app-name> --source live

# Pipe to specific resource type
argocd app manifests <app-name> | grep -A 50 "kind: ConfigMap"
```

## Resource Health States

| Status | Meaning | Action |
|--------|---------|--------|
| **Healthy** | Resource is functioning correctly | None needed |
| **Progressing** | Resource is changing state | Wait or investigate if stuck |
| **Degraded** | Resource has issues | Investigate immediately |
| **Suspended** | Resource is paused | May be intentional |
| **Missing** | Resource doesn't exist in cluster | Check sync status |
| **Unknown** | Health cannot be determined | Check resource definition |

## Resource Sync States

| Status | Meaning |
|--------|---------|
| **Synced** | Live matches desired |
| **OutOfSync** | Live differs from desired |
| **Unknown** | Sync status cannot be determined |

## Common Resource Inspection Commands

### Inspect Deployments

```bash
# List deployment status
argocd app get <app-name> -o json | jq '.status.resources[] | select(.kind == "Deployment") | {name: .name, health: .health.status, sync: .status}'

# Get specific deployment manifest
argocd app get-resource <app-name> \
  --kind Deployment \
  --name <deployment-name> \
  --namespace <namespace>
```

### Inspect ConfigMaps/Secrets

```bash
# List ConfigMaps
argocd app get <app-name> -o json | jq '.status.resources[] | select(.kind == "ConfigMap")'

# Note: Secret values are not shown in manifests command for security
```

### Inspect Services

```bash
# List Services
argocd app get <app-name> -o json | jq '.status.resources[] | select(.kind == "Service") | {name: .name, status: .status}'
```

### Inspect Custom Resources

```bash
# Get CRD resources (e.g., Argo Rollouts)
argocd app get-resource <app-name> \
  --group argoproj.io \
  --kind Rollout \
  --name <rollout-name>

# Get Ingress resources
argocd app get-resource <app-name> \
  --group networking.k8s.io \
  --kind Ingress \
  --name <ingress-name>
```

## Troubleshooting Resource Issues

### Resource Shows "Missing"

```bash
# Check if resource exists in cluster
kubectl get <kind> <name> -n <namespace>

# Check desired manifest
argocd app manifests <app-name> | grep -A 20 "name: <resource-name>"

# Try sync
argocd app sync <app-name> --resource <group>:<kind>:<name>
```

### Resource Shows "OutOfSync"

```bash
# See the diff
argocd app diff <app-name>

# Check for ignoreDifferences
argocd app get <app-name> -o json | jq '.spec.ignoreDifferences'
```

### Resource Shows "Degraded"

```bash
# Get resource details
argocd app get-resource <app-name> --kind <kind> --name <name>

# Check events with kubectl
kubectl describe <kind> <name> -n <namespace>
kubectl get events -n <namespace> --field-selector involvedObject.name=<name>
```

## Bulk Resource Operations

```bash
# Count resources by kind
argocd app get <app-name> -o json | jq '.status.resources | group_by(.kind) | map({kind: .[0].kind, count: length})'

# Export all resources to file
argocd app manifests <app-name> --source live > live-manifests.yaml
argocd app manifests <app-name> > desired-manifests.yaml
```
