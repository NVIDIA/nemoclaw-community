# ResolveDrift Workflow

Resolve ArgoCD Image Updater drift caused by manually-applied resources or configuration mismatches.

## Step 1: Diagnose the Drift

Check the ArgoCD application sync and health status:

```bash
KUBECONFIG=~/.kube/<cluster-config> kubectl get application <app-name> -n argocd -o jsonpath='{.status.sync.status}'
KUBECONFIG=~/.kube/<cluster-config> kubectl get application <app-name> -n argocd -o jsonpath='{.status.health.status}'
```

Check for out-of-sync resources:

```bash
KUBECONFIG=~/.kube/<cluster-config> kubectl get application <app-name> -n argocd -o jsonpath='{.status.resources[?(@.status!="Synced")]}'
```

Check for orphaned ImageUpdater CRs (manually applied, not managed by ArgoCD):

```bash
KUBECONFIG=~/.kube/<cluster-config> kubectl get imageupdaters -n argocd
KUBECONFIG=~/.kube/<cluster-config> kubectl get imageupdaters -n argocd -o yaml
```

Look for `kubectl.kubernetes.io/last-applied-configuration` annotations — these indicate manual `kubectl apply`.

## Step 2: Identify the Root Cause

Common drift causes:

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| ConfigMap shows Go map literal | Nested YAML keys instead of flat dotted keys | Use `config.log.level: debug` not `config: { logLevel: debug }` |
| Stale keys in ConfigMap | Legacy chart version keys still in values | Remove keys not used by current chart version |
| `ignoreDifferences` masking drift | Overly broad `/data` pointer on ConfigMap | Remove broad rules, let ArgoCD self-heal |
| Orphaned CRs in cluster | Manually applied resources not in Git | Add to `extraObjects` in Helm values |
| Metrics TLS handshake errors | Chart defaults to HTTPS metrics on 8443 | Set `--metrics-secure=false` and port 8080 |

## Step 3: Fix via GitOps

**CRITICAL: Never `kubectl apply` directly. All changes go through Git.**

### For orphaned resources (most common):

Add them to `extraObjects` in the Helm values file:

```yaml
extraObjects:
  - apiVersion: argocd-image-updater.argoproj.io/v1alpha1
    kind: ImageUpdater
    metadata:
      name: updater-dev
      namespace: argocd
    spec:
      namespace: argocd
      applicationRefs:
        - namePattern: dev-*
          useAnnotations: true
```

### For ConfigMap drift:

1. Check what keys the current chart version actually reads
2. Remove any stale keys from values.yaml
3. Remove overly broad `ignoreDifferences` rules
4. Let ArgoCD self-heal with correct values

### For metrics drift:

```yaml
extraArgs:
  - --metrics-secure=false

containerPorts:
  metrics: 8080

metrics:
  enabled: true
  service:
    servicePort: 8080
  serviceMonitor:
    enabled: true
    namespace: monitoring
```

## Step 4: Validate

```bash
# Run yamllint on modified file
yamllint <path-to-values.yaml>

# Run pre-commit hooks
pre-commit run --all-files

# After merge, verify ArgoCD sync
KUBECONFIG=~/.kube/<cluster-config> kubectl get application <app-name> -n argocd -o jsonpath='{.status.sync.status}'

# Verify resources are managed
KUBECONFIG=~/.kube/<cluster-config> kubectl get imageupdaters -n argocd
```

## Step 5: Worktree Considerations

When working in a git worktree and `main` is checked out in the parent:

```bash
# Cannot checkout main — it's locked by parent worktree
# Instead, fast-forward push directly:
git merge-base --is-ancestor origin/main <branch> && echo "Fast-forward possible"
git push origin <branch>:main
```
