---
name: argocd
description: Complete ArgoCD CLI and REST API skill for GitOps automation. Use when working with ArgoCD for: (1) Managing Applications - create, sync, delete, rollback, get status, wait for health, view logs, (2) ApplicationSets - templated multi-cluster deployments with generators, (3) Projects - RBAC, source/destination restrictions, sync windows, roles, (4) Repositories - add/remove Git repos, Helm charts, OCI registries, credential templates, (5) Clusters - register, rotate credentials, manage multi-cluster, (6) Accounts - generate tokens, manage users, check permissions, (7) Admin operations - export/import, settings validation, RBAC testing, notifications, (8) Troubleshooting - sync issues, health problems, connection errors. Supports both REST API (curl/HTTP) and CLI approaches with bearer token authentication.
---

# ArgoCD Skill

Complete ArgoCD operations via REST API and CLI with bearer token authentication.

## Authentication Setup

Generate and use bearer tokens for all operations:

```bash
# Generate token (requires existing login)
argocd login $ARGOCD_SERVER --username admin --password $ARGOCD_PASSWORD
ARGOCD_TOKEN=$(argocd account generate-token)

# Or generate for service account
ARGOCD_TOKEN=$(argocd account generate-token --account cibot --expires-in 7d)

# Export for subsequent commands
export ARGOCD_SERVER="argocd.example.com"
export ARGOCD_AUTH_TOKEN="$ARGOCD_TOKEN"
```

**Service account setup** (in argocd-cm ConfigMap):

```yaml
data:
  accounts.cibot: apiKey,login
  accounts.cibot.enabled: "true"
```

## REST API Pattern

All API calls use this pattern:

```bash
curl -s -H "Authorization: Bearer $ARGOCD_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  "https://$ARGOCD_SERVER/api/v1/{endpoint}"
```

Use the helper script at `scripts/argocd-api.sh` for common operations.

## Quick Reference

### Applications

```bash
# List all applications
argocd app list -o json

# Create application
argocd app create myapp \
  --repo https://github.com/org/repo.git \
  --path manifests \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace default \
  --sync-policy automated \
  --auto-prune \
  --self-heal

# Sync with options
argocd app sync myapp --prune --force --timeout 300

# Sync specific resources only
argocd app sync myapp --resource apps:Deployment:nginx

# Dry run
argocd app sync myapp --dry-run

# Wait for health
argocd app wait myapp --health --sync --timeout 300

# Get status
argocd app get myapp -o json | jq '{health: .status.health.status, sync: .status.sync.status}'

# Rollback
argocd app history myapp
argocd app rollback myapp 2

# Delete (cascade deletes resources)
argocd app delete myapp --cascade -y

# Terminate running operation
argocd app terminate-op myapp
```

### ApplicationSets

```bash
# Create/update ApplicationSet
argocd appset create appset.yaml --upsert

# List
argocd appset list

# Get details
argocd appset get myappset -o yaml

# Delete
argocd appset delete myappset -y
```

### Projects

```bash
# Create project
argocd proj create myproject -d https://kubernetes.default.svc,default -s https://github.com/org/*

# Add destinations/sources
argocd proj add-destination myproject https://kubernetes.default.svc 'team-*'
argocd proj add-source myproject 'https://github.com/org/*'

# Manage roles
argocd proj role create myproject deployer
argocd proj role add-policy myproject deployer -a sync -p allow -o '*'
argocd proj role add-group myproject deployer my-sso-group

# Generate role token
argocd proj role create-token myproject deployer --expires-in 24h

# Sync windows
argocd proj windows add myproject \
  --kind allow --schedule "0 22 * * *" --duration 2h
argocd proj windows list myproject
```

### Repositories

```bash
# Add HTTPS repo with token
argocd repo add https://github.com/org/repo --username git --password $GH_TOKEN

# Add SSH repo
argocd repo add git@github.com:org/repo.git --ssh-private-key-path ~/.ssh/id_rsa

# Add Helm repo
argocd repo add https://charts.example.com --type helm --name myrepo

# Add OCI registry
argocd repo add registry.example.com \
  --type helm --enable-oci --username user --password pass

# Credential template (applies to matching repos)
argocd repocreds add https://github.com/myorg/ --username git --password $TOKEN

# List/remove
argocd repo list
argocd repo rm https://github.com/org/repo
```

### Clusters

```bash
# Add cluster from kubeconfig context
argocd cluster add my-context --name production

# List clusters
argocd cluster list

# Get cluster details
argocd cluster get https://production.example.com

# Rotate credentials
argocd cluster rotate-auth production

# Remove cluster
argocd cluster rm https://production.example.com
```

### Accounts

```bash
# List accounts
argocd account list

# Generate token
argocd account generate-token --account cibot --expires-in 7d --id deploy-token

# Check permissions
argocd account can-i sync applications '*'
argocd account can-i get applications 'myproject/*'

# Update password
argocd account update-password --account admin

# Get user info
argocd account get-user-info
```

## REST API Examples

See `references/api-reference.md` for complete endpoint documentation.

### Create Application via API

```bash
curl -X POST -H "Authorization: Bearer $ARGOCD_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  "https://$ARGOCD_SERVER/api/v1/applications" \
  -d '{
    "metadata": {"name": "myapp", "namespace": "argocd"},
    "spec": {
      "project": "default",
      "source": {
        "repoURL": "https://github.com/org/repo.git",
        "path": "manifests",
        "targetRevision": "HEAD"
      },
      "destination": {
        "server": "https://kubernetes.default.svc",
        "namespace": "default"
      },
      "syncPolicy": {
        "automated": {"prune": true, "selfHeal": true},
        "syncOptions": ["CreateNamespace=true"]
      }
    }
  }'
```

### Sync Application via API

```bash
curl -X POST -H "Authorization: Bearer $ARGOCD_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  "https://$ARGOCD_SERVER/api/v1/applications/myapp/sync" \
  -d '{
    "revision": "HEAD",
    "prune": true,
    "dryRun": false,
    "strategy": {"hook": {}},
    "syncOptions": {"items": ["CreateNamespace=true"]}
  }'
```

### Get Application Status

```bash
curl -s -H "Authorization: Bearer $ARGOCD_AUTH_TOKEN" \
  "https://$ARGOCD_SERVER/api/v1/applications/myapp" | \
  jq '{name: .metadata.name, health: .status.health.status, sync: .status.sync.status}'
```

## Application Spec Reference

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: myapp
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default

  source:
    repoURL: https://github.com/org/repo.git
    targetRevision: HEAD
    path: manifests

    # Helm options
    helm:
      releaseName: my-release
      valueFiles: [values.yaml, values-prod.yaml]
      parameters:
        - name: image.tag
          value: v1.0.0

    # Kustomize options
    kustomize:
      namePrefix: prod-
      images: [gcr.io/image:v1.0.0]

  destination:
    server: https://kubernetes.default.svc
    namespace: default

  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
      - PruneLast=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m

  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers: [/spec/replicas]
```

## ApplicationSet Generators

See `references/api-reference.md` for complete generator patterns.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: cluster-apps
  namespace: argocd
spec:
  generators:
    # List generator
    - list:
        elements:
          - cluster: dev
            url: https://dev.example.com
          - cluster: prod
            url: https://prod.example.com

    # Cluster generator
    - clusters:
        selector:
          matchLabels:
            environment: production

    # Git directory generator
    - git:
        repoURL: https://github.com/org/apps.git
        directories:
          - path: apps/*

    # Matrix generator (combine two generators)
    - matrix:
        generators:
          - clusters: {}
          - git:
              repoURL: https://github.com/org/apps.git
              directories: [{path: apps/*}]

  template:
    metadata:
      name: '{{.cluster}}-{{.path.basename}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/apps.git
        targetRevision: HEAD
        path: '{{.path.path}}'
      destination:
        server: '{{.url}}'
        namespace: '{{.path.basename}}'
```

## Sync Options Reference

| Option | Description |
|--------|-------------|
| `Prune=true` | Delete resources not in Git |
| `PruneLast=true` | Prune after sync completes |
| `Replace=true` | Use replace instead of apply |
| `ServerSideApply=true` | Use server-side apply |
| `CreateNamespace=true` | Create namespace if missing |
| `ApplyOutOfSyncOnly=true` | Only sync changed resources |
| `Validate=false` | Skip kubectl validation |
| `Force=true` | Force resource replacement |
| `RespectIgnoreDifferences=true` | Respect ignoreDifferences on sync |

## Resource Hooks and Waves

```yaml
metadata:
  annotations:
    # Sync wave (lower = earlier)
    argocd.argoproj.io/sync-wave: "-1"

    # Hook phase
    argocd.argoproj.io/hook: PreSync|Sync|PostSync|SyncFail|PostDelete

    # Hook deletion policy
    argocd.argoproj.io/hook-delete-policy: HookSucceeded|HookFailed|BeforeHookCreation
```

## Health Status Values

| Status | Description |
|--------|-------------|
| `Healthy` | Resource running correctly |
| `Progressing` | Deployment in progress |
| `Degraded` | Health check failed |
| `Suspended` | Resource paused |
| `Missing` | Resource doesn't exist |
| `Unknown` | Cannot determine health |

## CLI Global Flags

| Flag | Description |
|------|-------------|
| `--server` | ArgoCD server address |
| `--auth-token` | Bearer token |
| `--grpc-web` | Use gRPC-web (for proxies) |
| `--insecure` | Skip TLS verification |
| `--plaintext` | Disable TLS |
| `--config` | Config file path |
| `-o json/yaml/wide` | Output format |

## Error Handling

```bash
# Check if app exists before operations
if argocd app get myapp &>/dev/null; then
  argocd app sync myapp
else
  argocd app create myapp ...
fi

# Wait with timeout and handle failure
if ! argocd app wait myapp --health --timeout 300; then
  echo "App failed to become healthy"
  argocd app get myapp
  exit 1
fi

# Idempotent upsert pattern
argocd app create myapp --upsert ...
argocd repo add https://repo --upsert ...
```

## Common Workflows

### Deploy and Wait Pattern

```bash
argocd app sync myapp --prune --async
argocd app wait myapp --health --sync --timeout 300
```

### Canary/Blue-Green with Argo Rollouts

```bash
# Promote rollout
argocd app actions run myapp promote --kind Rollout --resource-name my-rollout
```

### Multi-Cluster Deployment

```bash
# Register clusters
argocd cluster add dev-context --name dev
argocd cluster add prod-context --name prod

# Use ApplicationSet with cluster generator
```

## Admin Operations

```bash
# Get initial admin password
argocd admin initial-password -n argocd

# Export all resources for backup
argocd admin export > backup.yaml

# Import from backup
argocd admin import < backup.yaml

# Start local dashboard (core mode)
argocd admin dashboard

# Validate RBAC policy
argocd admin settings rbac validate --policy-file policy.csv

# Test RBAC permission
argocd admin settings rbac can role:developer sync applications 'myproject/*'

# Notification management
argocd admin notifications template list
argocd admin notifications trigger list
```

## Troubleshooting Quick Reference

```bash
# Check diff for out-of-sync apps
argocd app diff myapp

# Force refresh from Git
argocd app get myapp --hard-refresh

# View detailed sync operation
argocd app get myapp --show-operation

# Check application conditions
argocd app get myapp -o json | jq '.status.conditions'

# Terminate stuck sync
argocd app terminate-op myapp

# Check controller logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=100

# Apps not healthy
argocd app list -o json | \
  jq -r '.items[] | select(.status.health.status != "Healthy") | .metadata.name'

# Apps out of sync
argocd app list -o json | \
  jq -r '.items[] | select(.status.sync.status != "Synced") | .metadata.name'
```

For complete API endpoint documentation, see `references/api-reference.md`.
For complete CLI command reference, see `references/cli-reference.md`.
For troubleshooting guide, see `references/troubleshooting.md`.

---

## Absorbed sub-skills (post-consolidation)

This skill now subsumes the former `argocd-command` and `argocd-review` skills. Their original SKILL.md content (still useful as deep reference) lives under `References/`:

| Subject | Path |
|---------|------|
| Local cluster context (kubeconfig, port-forward, aliases) | `References/command-workflows/` + `References/command-tools/` |
| Application review, diff, rollback, history, sync troubleshooting | `References/review.md` + `References/review-workflows/` + `References/review-tools/` |

For multi-cluster ApplicationSets, Image Updater, cluster bootstrapping, and workload onboarding, see the sibling **`argocd-advanced`** skill. For canary / blue-green / promotion, see **`progressive-delivery`**.

---

## Gotchas

- **`OutOfSync` with empty diff:** Usually a Helm chart `releaseName` change or kustomize hash mismatch after a CRD upgrade. `argocd app diff` shows nothing — run `argocd app manifests` to see the rendered output.
- **`ignoreDifferences` silently ignored under SSA:** With Server-Side Diff enabled, schema-validation errors on unknown fields (e.g. Job `podReplacementPolicy` on K8s 1.29+) fire before ignoreDifferences runs. Disable SSA per-app via `argocd.argoproj.io/compare-options: ServerSideDiff=false`.
- **`--cascade` deletes the namespace too** if you created it via `CreateNamespace=true`. Use `--cascade=false` to detach the Application while keeping workloads.
- **Tokens cannot be revoked individually** — only by deleting the account or rotating the JWT signing key. Always pass `--id` to `generate-token` so you can audit which token is which.
- **`argocd app sync` on an automated-sync app is a no-op** if the controller already attempted a sync this poll cycle. Add `--force` or temporarily disable auto-sync to push through.
- **`finalizers: [resources-finalizer.argocd.argoproj.io]` is required** for cascade delete to actually remove cluster resources. Without it, deleting the Application orphans everything in the destination namespace.
