# AppManage Workflow

Manage ArgoCD Applications - create, sync, delete, and monitor.

## Quick Commands

| Action | Command |
|--------|---------|
| List apps | `argocd app list` |
| Get app | `argocd app get <name>` |
| Sync app | `argocd app sync <name>` |
| Delete app | `argocd app delete <name>` |
| App status | `argocd app get <name> -o json \| jq '.status.health.status'` |

## List Applications

```bash
# List all applications
argocd app list

# List with specific output
argocd app list -o wide
argocd app list -o json
argocd app list -o yaml

# Filter by project
argocd app list -p default

# Filter by label
argocd app list -l team=platform
```

## Get Application Details

```bash
# Get app details
argocd app get <app-name>

# Get as JSON (for scripting)
argocd app get <app-name> -o json

# Get specific fields
argocd app get <app-name> -o json | jq '.status.sync.status'
argocd app get <app-name> -o json | jq '.status.health.status'

# Get resources
argocd app resources <app-name>
```

## Create Application

### From CLI

```bash
# Basic application
argocd app create <app-name> \
  --repo https://github.com/org/repo.git \
  --path manifests \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace <namespace>

# With Helm values
argocd app create <app-name> \
  --repo https://charts.example.com \
  --helm-chart <chart-name> \
  --revision <version> \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace <namespace> \
  --values values.yaml

# With project
argocd app create <app-name> \
  --project <project-name> \
  --repo https://github.com/org/repo.git \
  --path manifests \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace <namespace>
```

### From File

```bash
# Create from YAML file
argocd app create -f application.yaml

# Example Application YAML
cat <<EOF > application.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/repo.git
    targetRevision: HEAD
    path: manifests
  destination:
    server: https://kubernetes.default.svc
    namespace: my-namespace
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
EOF
```

## Sync Application

```bash
# Basic sync
argocd app sync <app-name>

# Sync with prune (remove orphans)
argocd app sync <app-name> --prune

# Force sync (replace resources)
argocd app sync <app-name> --force

# Dry run (preview changes)
argocd app sync <app-name> --dry-run

# Sync specific resources only
argocd app sync <app-name> --resource :Deployment:my-deployment

# Sync with retry
argocd app sync <app-name> --retry-limit 5 --retry-backoff-duration 5s

# Async sync (don't wait)
argocd app sync <app-name> --async
```

## Wait for Application

```bash
# Wait for sync
argocd app wait <app-name> --sync

# Wait for health
argocd app wait <app-name> --health

# Wait with timeout
argocd app wait <app-name> --timeout 300

# Wait for specific operation
argocd app wait <app-name> --operation
```

## Edit Application

```bash
# Edit interactively
argocd app edit <app-name>

# Patch application
argocd app patch <app-name> --patch '{"spec":{"source":{"targetRevision":"v1.2.0"}}}'

# Set parameters
argocd app set <app-name> --parameter image.tag=v2.0.0
argocd app set <app-name> --values-literal-file values-override.yaml

# Unset parameters
argocd app unset <app-name> --parameter image.tag
```

## Delete Application

```bash
# Delete with cascade (delete resources)
argocd app delete <app-name> --yes

# Delete without cascade (keep resources)
argocd app delete <app-name> --cascade=false --yes

# Confirm deletion pending
argocd app confirm-deletion <app-name>
```

## Application History & Rollback

```bash
# View deployment history
argocd app history <app-name>

# Rollback to previous revision
argocd app rollback <app-name> <revision-id>

# Example: rollback to revision 5
argocd app rollback my-app 5
```

## Diff & Manifests

```bash
# Show diff between target and live
argocd app diff <app-name>

# Get rendered manifests
argocd app manifests <app-name>

# Get manifests as JSON
argocd app manifests <app-name> -o json
```

## Resource Management

```bash
# List resources
argocd app resources <app-name>

# Get specific resource
argocd app get-resource <app-name> --resource-name <name> --kind <kind>

# Patch resource
argocd app patch-resource <app-name> --resource-name <name> --kind <kind> --patch '{"spec":{}}'

# Delete resource
argocd app delete-resource <app-name> --resource-name <name> --kind <kind>
```

## Actions

```bash
# List available actions
argocd app actions list <app-name>

# Run action
argocd app actions run <app-name> <action-name>

# Example: restart deployment
argocd app actions run <app-name> restart --resource-name <deployment-name> --kind Deployment
```
