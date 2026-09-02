# DiagnoseSyncFailure Workflow

Systematically diagnose ArgoCD application sync failures, especially those caused by missing CRDs or undeployed dependencies.

## Step 1: Gather Error Context

Read the ArgoCD application status to identify the exact error:

```bash
KUBECONFIG=~/.kube/<cluster-config> kubectl get application <app-name> -n argocd -o yaml
```

Common error patterns:
- `could not find <group>/<kind>` -> Missing CRD (dependency not deployed)
- `ComparisonError` -> Schema mismatch or invalid manifest
- `SyncError` -> Resource creation/update failed

## Step 2: Identify the Missing Dependency

If the error mentions a missing CRD (e.g., `spv.no/AzureKeyVaultSecret`):

1. **Check if the CRD exists on the cluster**:
   ```bash
   KUBECONFIG=~/.kube/<config> kubectl get crd | grep <group>
   ```

2. **Check if the dependency application exists**:
   ```bash
   KUBECONFIG=~/.kube/<config> kubectl get application -n argocd | grep <dependency>
   ```

3. **Check if the ApplicationSet exists**:
   ```bash
   KUBECONFIG=~/.kube/<config> kubectl get applicationset -n argocd | grep <dependency>
   ```

## Step 3: Trace the Dependency Chain

Map the full dependency chain:

| CRD Group | Provided By | ApplicationSet | Status |
|-----------|-------------|----------------|--------|
| `spv.no` | akv2k8s | `akv2k8s.yaml` | Check |
| `cert-manager.io` | cert-manager | `cert-manager.yaml` | Check |
| `monitoring.coreos.com` | kube-prometheus-stack | N/A | Check |

## Step 4: Check Git vs Cluster State

1. **Does the ApplicationSet YAML exist in Git?**
   ```bash
   ls infra-team/applicationset/<dependency>.yaml
   ```

2. **Is it listed in kustomization.yaml?**
   ```bash
   grep <dependency> infra-team/applicationset/kustomization.yaml
   ```

3. **Do values exist for this cluster?**
   ```bash
   ls argo-cd-helm-values/kube-addons/<dependency>/<cluster>/values.yaml
   ```

## Step 5: Determine Fix

| Scenario | Fix |
|----------|-----|
| ApplicationSet exists in Git but not on cluster | Add to `kustomization.yaml` and commit |
| ApplicationSet exists but cluster not in generator list | Add cluster element to generator list |
| ApplicationSet deployed but CRDs not yet installed | Check sync wave ordering (dependency should have lower wave) |
| ApplicationSet YAML doesn't exist | Create it following existing patterns |
| Root Application doesn't exist | Use `CreateRootApplication` workflow |

## Step 6: Validate Fix

After committing and pushing:

```bash
# Verify ApplicationSet was created
KUBECONFIG=~/.kube/<config> kubectl get applicationset <name> -n argocd

# Verify Application was generated
KUBECONFIG=~/.kube/<config> kubectl get application -n argocd | grep <name>

# Verify CRDs were installed
KUBECONFIG=~/.kube/<config> kubectl get crd | grep <group>

# Verify original failing app now syncs
KUBECONFIG=~/.kube/<config> kubectl get application <original-app> -n argocd
```

## Common Dependency Map

| Application | Requires CRD From | Sync Wave Recommendation |
|-------------|-------------------|--------------------------|
| adp-agent (with AzureKeyVaultSecret) | akv2k8s | akv2k8s: -5, adp-agent: +5 |
| Any app with Certificate resources | cert-manager | cert-manager: -5 |
| Any app with ServiceMonitor | kube-prometheus-stack | prometheus: -5 |
| Any app with IngressRoute | traefik | traefik: -5 |
