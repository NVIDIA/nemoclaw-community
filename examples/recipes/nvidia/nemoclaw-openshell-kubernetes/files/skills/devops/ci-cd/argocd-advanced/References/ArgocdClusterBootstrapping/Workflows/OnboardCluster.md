# OnboardCluster Workflow

Add a new Kubernetes cluster to existing ArgoCD ApplicationSet generators.

## Step 1: Gather Cluster Information

Collect the required details for the new cluster:

| Field | Description | Example |
|-------|-------------|---------|
| `cluster` | Short name (used in app names and paths) | `example-app-prd` |
| `url` | Kubernetes API server URL | `https://aks-xxx.privatelink.eastus.azmk8s.io:443` |
| `project` | ArgoCD project name | `kube-addons` |
| `branch` | Git branch for values | `main` |
| `environment` | Environment label (`development`, `production`) | `production` |

## Step 2: Register Cluster in ArgoCD

Ensure the cluster is registered in ArgoCD (check `argocd-repos.yaml` or cluster secrets):

```bash
KUBECONFIG=~/.kube/<hub-config> kubectl get secret -n argocd -l argocd.argoproj.io/secret-type=cluster
```

## Step 3: Add Cluster to ApplicationSet Generators

For each ApplicationSet that should target the new cluster, add an element to the `list` generator:

```yaml
generators:
  - list:
      elements:
        # ... existing clusters ...
        - cluster: <new-cluster-name>
          url: <api-server-url>
          project: <argocd-project>
          branch: main
          environment: <environment>
```

## Step 4: Create Values Files

For each ApplicationSet targeting the new cluster, create the values file:

```bash
mkdir -p argo-cd-helm-values/kube-addons/<addon>/<cluster-name>/
```

Create `values.yaml` based on an existing cluster's values, adjusting for:
- **Environment-specific settings** (resource limits, replica counts)
- **Spot tolerations** (for development clusters only)
- **Cluster-specific endpoints** (Key Vault names, DNS zones)

### Spot Tolerations (Development Clusters Only)

```yaml
tolerations:
  - key: kubernetes.azure.com/scalesetpriority
    operator: Equal
    value: spot
    effect: NoSchedule

affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: kubernetes.azure.com/scalesetpriority
              operator: In
              values:
                - spot
```

## Step 5: Create ArgoCD Project (if needed)

If the new cluster uses a new ArgoCD project, add it to `argocd-projects.yaml`:

```yaml
- cluster: <new-cluster>
  project: <new-project-name>
  sourceRepos:
    - '*'
  destinations:
    - namespace: '*'
      server: <api-server-url>
```

## Step 6: Validate

```bash
# Validate kustomize build
kustomize build infra-team/applicationset/

# Run pre-commit hooks
pre-commit run --all-files

# Check values files exist for all addons
for addon in akv2k8s cert-manager ingress-nginx otel; do
  ls argo-cd-helm-values/kube-addons/$addon/<cluster-name>/values.yaml
done
```

## Step 7: Commit and Push

```bash
git add infra-team/applicationset/ argo-cd-helm-values/
git commit -m "feat(argocd): onboard <cluster-name> to ApplicationSets"
git push
```

## Step 8: Monitor Deployment

After push, monitor in ArgoCD UI:
1. New Applications should appear (e.g., `<cluster>-akv2k8s`, `<cluster>-otel`)
2. Applications should sync and become Healthy
3. Check sync wave ordering — dependencies first (akv2k8s, cert-manager), then consumers

```bash
KUBECONFIG=~/.kube/<config> kubectl get application -n argocd | grep <cluster-name>
```

## Recommended Onboarding Order

Deploy addons in this order (respecting dependencies):

1. **Wave -5**: akv2k8s, cert-manager (CRD providers)
2. **Wave 0**: ingress-nginx, external-dns, storage-class (infrastructure)
3. **Wave 0**: otel, loki, tempo, mimir, pyroscope (observability)
4. **Wave +5**: adp-agent, application workloads (CRD consumers)
