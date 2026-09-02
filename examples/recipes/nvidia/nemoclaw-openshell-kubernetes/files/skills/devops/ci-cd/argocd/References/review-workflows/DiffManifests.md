# DiffManifests Workflow

**Compare live cluster state against desired state in Git.**

## When to Use

- Understanding why an app is OutOfSync
- Reviewing what changes will be applied during sync
- Detecting configuration drift
- Validating changes before deployment

## Workflow Steps

### Step 1: Basic Diff

```bash
# Show diff between live and desired state
argocd app diff <app-name>
```

Output shows:
- `===` Lines that match
- `---` Lines only in live (will be removed)
- `+++` Lines only in desired (will be added)

### Step 2: Diff with Local Changes (Pre-commit Review)

```bash
# For Helm/Kustomize apps (server-side generation)
argocd app diff <app-name> --local <repo-root> --server-side-generate

# For plain manifests
argocd app diff <app-name> --local <path-to-manifests>
```

### Step 3: Review Specific Resources

```bash
# Get live manifest for specific resource
argocd app manifests <app-name> --source live | grep -A 50 "kind: Deployment"

# Get desired manifest
argocd app manifests <app-name> | grep -A 50 "kind: Deployment"
```

### Step 4: Check Ignored Differences

Some differences may be intentionally ignored:

```bash
# View ignoreDifferences configuration
argocd app get <app-name> -o json | jq '.spec.ignoreDifferences'
```

## Common Diff Scenarios

### Scenario: Immutable Field Changes

```bash
# Error: cannot change immutable field
# Solution: May need to delete and recreate resource
argocd app sync <app-name> --replace --resource <group>:<kind>:<name>
```

### Scenario: Cluster-Generated Fields

Fields like `metadata.resourceVersion`, `status`, `metadata.uid` are cluster-managed. These should be in `ignoreDifferences`:

```yaml
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas  # If using HPA
```

## Verifying Changes Before Sync

```bash
# Dry-run to see what would happen
argocd app sync <app-name> --dry-run

# Then actual sync if satisfied
argocd app sync <app-name>
```
