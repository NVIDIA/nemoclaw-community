# CreateRootApplication Workflow

Create a root ArgoCD Application (app-of-apps pattern) that manages ApplicationSets via Kustomize for GitOps lifecycle management.

## Step 1: Audit the ApplicationSet Directory

List all YAML files in the ApplicationSet directory:

```bash
ls infra-team/applicationset/*.yaml
```

Categorize each file:
- **Active**: Currently deployed on the cluster (verify with `kubectl get applicationset -n argocd`)
- **Template**: Contains placeholders like `<SERVICE_NAME>` (e.g., `TEMPLATE.yaml`)
- **WIP**: Work-in-progress files (e.g., `*-wip.yaml`)
- **Duplicate**: Files defining the same ApplicationSet name as another file

**CRITICAL**: Only active files go in the kustomization. Including templates or WIP files would deploy broken resources.

## Step 2: Check for Name Conflicts

Scan all ApplicationSet files for duplicate `metadata.name` values:

```bash
grep -h "^  name:" infra-team/applicationset/*.yaml | sort | uniq -d
```

If duplicates exist, determine which file is the canonical one (usually the one matching the cluster state) and exclude the other.

## Step 3: Create kustomization.yaml

Create `infra-team/applicationset/kustomization.yaml` with only the curated active files:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# Active ApplicationSets managed by the root-applicationsets Application.
# Only files listed here are deployed to ArgoCD.
# To add a new ApplicationSet: create the YAML, add it here, commit and push.
resources:
  - addon-one.yaml
  - addon-two.yaml
  # NOTE: template.yaml and wip files are excluded
```

**Why Kustomize over raw directory?**
- Explicit control over what gets deployed
- Safe exclusion of templates, WIP, and experimental files
- Adding/removing is a single-line change in Git
- `prune: true` means removing from the list also removes from the cluster

## Step 4: Create the Root Application

Create `infra-team/bootstrap/root-applicationsets.yaml`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: root-applicationsets
  namespace: argocd
  labels:
    app.kubernetes.io/name: root-applicationsets
    app.kubernetes.io/part-of: argocd-bootstrap
    app.kubernetes.io/component: applicationset-management
    app.kubernetes.io/managed-by: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "-10"
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: <GIT_REPO_URL>
    targetRevision: main
    path: infra-team/applicationset
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
      allowEmpty: false
    syncOptions:
      - ServerSideApply=true
      - CreateNamespace=false
      - Validate=true
      - ApplyOutOfSyncOnly=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

Key design decisions:
- **sync-wave: "-10"**: Deploys before any ApplicationSet (which default to wave 0)
- **prune: true**: Removing a file from kustomization.yaml deletes the ApplicationSet
- **ServerSideApply**: Prevents conflicts when adopting existing ApplicationSets
- **ApplyOutOfSyncOnly**: Avoids unnecessary re-syncing of unchanged resources
- **project: default**: Root app uses default project for maximum permissions

## Step 5: Validate with Kustomize Build

```bash
kustomize build infra-team/applicationset/ | head -50
```

Verify:
- All listed resources are valid YAML
- No template placeholders remain
- No duplicate resource names

## Step 6: Run Pre-Commit Checks

```bash
pre-commit run --all-files
```

Fix any yamllint or validation errors before committing.

## Step 7: Commit and Push

```bash
git add infra-team/applicationset/kustomization.yaml infra-team/bootstrap/root-applicationsets.yaml
git commit -m "feat(argocd): add root Application for GitOps ApplicationSet management"
git push
```

## Step 8: Bootstrap (One-Time Manual Step)

The root Application must be applied ONCE to ArgoCD. After this, all future changes are via Git.

**Option A: ArgoCD UI**
1. ArgoCD UI > **+ NEW APP**
2. Paste the YAML from `infra-team/bootstrap/root-applicationsets.yaml`
3. Click **CREATE**

**Option B: ArgoCD CLI** (if available)
```bash
argocd app create -f infra-team/bootstrap/root-applicationsets.yaml
```

## Step 9: Verify

```bash
# Root app synced
KUBECONFIG=~/.kube/<config> kubectl get application root-applicationsets -n argocd

# All ApplicationSets present
KUBECONFIG=~/.kube/<config> kubectl get applicationset -n argocd

# No orphaned ApplicationSets (all managed by root app)
KUBECONFIG=~/.kube/<config> kubectl get applicationset -n argocd -o json | jq '.items[].metadata.ownerReferences'
```

## Future Workflow

To add a new ApplicationSet after root app is deployed:
1. Create the YAML in `infra-team/applicationset/`
2. Add the filename to `infra-team/applicationset/kustomization.yaml`
3. Commit and push — ArgoCD auto-deploys it

To remove an ApplicationSet:
1. Remove the filename from `kustomization.yaml`
2. Commit and push — ArgoCD auto-prunes it (if `prune: true`)
