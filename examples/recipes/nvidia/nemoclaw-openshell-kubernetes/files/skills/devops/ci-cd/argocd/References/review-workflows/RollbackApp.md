# RollbackApp Workflow

**Safely rollback an ArgoCD application to a previous version.**

## When to Use

- Bad deployment caused issues
- Need to revert to known-good state
- Testing rollback procedures

## Prerequisites

- Know the application name
- Have appropriate permissions for rollback

## Workflow Steps

### Step 1: View Deployment History

```bash
# List deployment history
argocd app history <app-name>
```

Output example:
```
ID  DATE                           REVISION
0   2025-01-13 10:00:00 +0000 UTC  abc1234 (HEAD)
1   2025-01-12 15:30:00 +0000 UTC  def5678 (v1.2.0)
2   2025-01-11 09:00:00 +0000 UTC  789abcd (v1.1.0)
```

- **ID 0** = Current deployment
- Higher IDs = Older deployments

### Step 2: Review Target State (Optional but Recommended)

Before rolling back, understand what you're reverting to:

```bash
# Get current app details
argocd app get <app-name>

# Check what manifest the target revision had
argocd app manifests <app-name> --revision <commit-sha>
```

### Step 3: Perform Rollback

```bash
# Interactive rollback (with confirmation)
argocd app rollback <app-name> <history-id>

# Non-interactive rollback
argocd app rollback <app-name> <history-id> --yes

# Rollback with timeout (wait for completion)
argocd app rollback <app-name> <history-id> --timeout 300
```

### Step 4: Verify Rollback Success

```bash
# Check app status
argocd app get <app-name>

# Verify resources are healthy
argocd app resources <app-name> --tree

# Check sync status shows the rolled-back revision
argocd app get <app-name> -o json | jq '{revision: .status.sync.revision, health: .status.health.status}'
```

## Important Considerations

### Rollback vs Re-sync

**Rollback** (`argocd app rollback`):
- Deploys a specific historical revision
- App will show OutOfSync (live != Git HEAD)
- Good for emergency recovery

**Re-sync to tag/commit** (`argocd app sync --revision`):
- Syncs to specific Git ref
- Updates app's target revision config
- Better for controlled version management

```bash
# Sync to specific tag
argocd app sync <app-name> --revision v1.1.0

# Sync to specific commit
argocd app sync <app-name> --revision abc1234
```

### Auto-Sync Warning

If app has auto-sync enabled, rollback will be immediately overwritten:

```bash
# Check sync policy
argocd app get <app-name> -o json | jq '.spec.syncPolicy'

# Disable auto-sync before rollback if needed
argocd app set <app-name> --sync-policy none

# After rollback, re-enable if desired
argocd app set <app-name> --sync-policy automated
```

## Rollback Scenarios

### Scenario 1: Emergency Rollback

```bash
# Quick rollback to last known good (usually ID 1)
argocd app rollback <app-name> 1 --yes

# Verify immediately
argocd app get <app-name>
```

### Scenario 2: Rollback with Auto-Sync

```bash
# 1. Disable auto-sync
argocd app set <app-name> --sync-policy none

# 2. Rollback
argocd app rollback <app-name> 1 --yes

# 3. Verify
argocd app get <app-name>

# 4. Fix the issue in Git, then re-enable
argocd app set <app-name> --sync-policy automated
```

### Scenario 3: Multi-Source App Rollback

For apps with multiple sources, you may need to sync specific source revisions:

```bash
# Sync specific revisions per source
argocd app sync <app-name> \
  --revisions <chart-version> --source-positions 1 \
  --revisions <values-commit> --source-positions 2
```

## Post-Rollback Actions

1. **Document the incident** - Note why rollback was needed
2. **Fix forward in Git** - Revert bad changes in the repository
3. **Re-enable auto-sync** - If disabled
4. **Notify team** - Communicate the rollback
