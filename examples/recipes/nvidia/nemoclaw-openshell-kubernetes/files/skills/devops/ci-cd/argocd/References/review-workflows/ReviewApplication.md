# ReviewApplication Workflow

**Comprehensive review of an ArgoCD application's current state.**

## When to Use

- Checking application health and sync status
- Understanding current deployment state
- Gathering information before making changes

## Workflow Steps

### Step 1: Get Application Overview

```bash
# Basic status
argocd app get <app-name>

# Detailed JSON output
argocd app get <app-name> -o json
```

### Step 2: Check Sync Operation Status

```bash
# Show recent sync operation details
argocd app get <app-name> --show-operation
```

### Step 3: Review Resource Tree

```bash
# List all managed resources with health
argocd app resources <app-name> --tree
```

### Step 4: Check for Issues

```bash
# Extract unhealthy resources
argocd app get <app-name> -o json | jq '.status.resources[] | select(.health.status != "Healthy")'

# Check sync status
argocd app get <app-name> -o json | jq '{syncStatus: .status.sync.status, health: .status.health.status}'
```

## Output Interpretation

| Field | Healthy Values | Warning Values |
|-------|---------------|----------------|
| Sync Status | Synced | OutOfSync, Unknown |
| Health Status | Healthy | Progressing, Degraded, Missing |
| Operation Phase | Succeeded | Running, Failed, Error |

## Common Follow-ups

- **OutOfSync**: Run `DiffManifests` workflow
- **Degraded**: Run `TroubleshootSync` workflow
- **Progressing (stuck)**: Check pod events with kubectl
