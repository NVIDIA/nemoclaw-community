# ArgoCD Cluster Bootstrapping Templates

Ready-to-use YAML templates for bootstrapping Kubernetes clusters into ArgoCD.

## Template Index

| Template | Purpose | Location |
|----------|---------|----------|
| `cluster-secret.yaml` | Register cluster with ArgoCD | `infra-team/argocd-clusters/` |
| `argocd-project.yaml` | Define RBAC boundaries | `infra-team/argocd-projects/` |
| `applicationset-cluster-generator.yaml` | Deploy to clusters by labels | `infra-team/applicationset/` |
| `applicationset-matrix-generator.yaml` | Deploy multiple apps × clusters | `infra-team/applicationset/` |
| `values-base.yaml` | Base Helm values (all envs) | `argo-cd-helm-values/.../base/` |
| `values-dev.yaml` | Development environment values | `argo-cd-helm-values/.../<cluster>/` |
| `values-prd.yaml` | Production environment values | `argo-cd-helm-values/.../<cluster>/` |
| `bootstrap-script.sh` | Automated bootstrap script | `scripts/` |

## Quick Start

### 1. Create Cluster Secret

```bash
# Copy template
cp cluster-secret.yaml infra-team/argocd-clusters/my-cluster.yaml

# Edit placeholders
sed -i 's/<CLUSTER_NAME>/my-cluster/g' infra-team/argocd-clusters/my-cluster.yaml
sed -i 's/<ENVIRONMENT>/dev/g' infra-team/argocd-clusters/my-cluster.yaml
# ... continue with other placeholders
```

### 2. Create ArgoCD Project

```bash
# Copy template
cp argocd-project.yaml infra-team/argocd-projects/my-cluster.yaml

# Edit placeholders
sed -i 's/<PROJECT_NAME>/my-cluster/g' infra-team/argocd-projects/my-cluster.yaml
```

### 3. Create Component Values

```bash
# Create directory structure
mkdir -p argo-cd-helm-values/kube-addons/ingress-nginx/my-cluster

# Copy appropriate template
cp values-dev.yaml argo-cd-helm-values/kube-addons/ingress-nginx/my-cluster/values.yaml

# Edit for specific component
```

## Placeholder Reference

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `<CLUSTER_NAME>` | Developer-friendly name | `example-app-dev` |
| `<ENVIRONMENT>` | Environment tier | `dev`, `hlg`, `prd` |
| `<REGION>` | Azure region code | `brazilsouth` |
| `<NODE_TYPE>` | Node instance type | `spot`, `standard` |
| `<SERVER_URL>` | Kubernetes API URL | `https://aks-xxx.hcp.brazilsouth.azmk8s.io:443` |
| `<PROJECT_NAME>` | ArgoCD project name | `example-app-dev` |
| `<COMPONENT_NAME>` | Helm component name | `ingress-nginx` |
| `<HELM_REPO_URL>` | Helm repository URL | `https://kubernetes.github.io/ingress-nginx` |
| `<CHART_NAME>` | Helm chart name | `ingress-nginx` |
| `<CHART_VERSION>` | Helm chart version | `4.9.0` |

## Validation

Before committing, validate your YAML:

```bash
# Validate syntax
yq eval '.' your-file.yaml > /dev/null

# Validate against ArgoCD schema (if available)
kubectl apply --dry-run=client -f your-file.yaml

# Run pre-commit hooks
pre-commit run --all-files
```

## Common Customizations

### Add New Component

1. Create ApplicationSet in `infra-team/applicationset/kube-addons/`
2. Create base values in `argo-cd-helm-values/kube-addons/<component>/base/`
3. Create per-cluster values for each target cluster

### Add New Cluster to Existing ApplicationSets

1. Create cluster secret with appropriate labels
2. Create ArgoCD project
3. Create values files for each component
4. Existing ApplicationSets will automatically target the new cluster

### Change Sync Policy

Modify the `syncPolicy` section in ApplicationSets:

```yaml
# Automated (dev)
syncPolicy:
  automated:
    prune: true
    selfHeal: true

# Manual (prd)
syncPolicy:
  syncOptions:
    - CreateNamespace=true
```
