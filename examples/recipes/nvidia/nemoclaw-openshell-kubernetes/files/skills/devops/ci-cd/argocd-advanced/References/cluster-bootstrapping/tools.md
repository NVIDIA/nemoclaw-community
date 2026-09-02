# ArgoCD Cluster Bootstrapping - Tools & Commands

Complete reference for CLI commands, scripts, and automation tools used in cluster bootstrapping.

---

## ArgoCD CLI Reference

### Authentication

```bash
# Login with SSO
argocd login argocd.example.com --sso

# Login with username/password
argocd login argocd.example.com --username admin --password <password>

# Login with auth token
argocd login argocd.example.com --auth-token <token>

# Check current context
argocd context

# Logout
argocd logout argocd.example.com
```

### Cluster Management

```bash
# List all clusters
argocd cluster list

# Add cluster (uses current kubectl context)
argocd cluster add <context-name> --name <friendly-name>

# Add cluster with specific kubeconfig
argocd cluster add <context-name> \
  --name <friendly-name> \
  --kubeconfig /path/to/kubeconfig \
  --in-cluster-context <context-in-kubeconfig>

# Get cluster details
argocd cluster get <cluster-name>

# Remove cluster
argocd cluster rm <cluster-name>

# Rotate cluster credentials
argocd cluster rotate-auth <cluster-name>
```

### Application Management

```bash
# List applications
argocd app list

# Filter by cluster
argocd app list --dest-server <server-url>

# Filter by project
argocd app list --project <project-name>

# Get application details
argocd app get <app-name>

# Get application manifests
argocd app manifests <app-name>

# Sync application
argocd app sync <app-name>

# Sync with prune
argocd app sync <app-name> --prune

# Force sync (replace resources)
argocd app sync <app-name> --force

# Sync specific resources
argocd app sync <app-name> --resource <group>:<kind>:<name>

# Diff against live state
argocd app diff <app-name>

# Rollback application
argocd app rollback <app-name> <history-id>

# View application history
argocd app history <app-name>

# Delete application
argocd app delete <app-name> --cascade
```

### ApplicationSet Management

```bash
# List ApplicationSets
argocd appset list

# Get ApplicationSet details
argocd appset get <appset-name>

# Get ApplicationSet with generator parameters
argocd appset get <appset-name> --show-params

# Create ApplicationSet from file
argocd appset create -f applicationset.yaml

# Delete ApplicationSet
argocd appset delete <appset-name>
```

### Project Management

```bash
# List projects
argocd proj list

# Get project details
argocd proj get <project-name>

# Create project
argocd proj create <project-name> \
  --description "Project description" \
  --src <repo-url> \
  --dest <server>,<namespace>

# Add source repository to project
argocd proj add-source <project-name> <repo-url>

# Add destination to project
argocd proj add-destination <project-name> <server> <namespace>

# Remove destination from project
argocd proj remove-destination <project-name> <server> <namespace>

# Allow cluster resource
argocd proj allow-cluster-resource <project-name> <group> <kind>

# Deny cluster resource
argocd proj deny-cluster-resource <project-name> <group> <kind>
```

---

## kubectl Commands for ArgoCD

### Cluster Secrets

```bash
# List cluster secrets
kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=cluster

# Get cluster secret details
kubectl get secret <cluster-name> -n argocd -o yaml

# Get cluster secret labels
kubectl get secret <cluster-name> -n argocd --show-labels

# Describe cluster secret
kubectl describe secret <cluster-name> -n argocd

# Edit cluster secret (use with caution)
kubectl edit secret <cluster-name> -n argocd

# Delete cluster secret
kubectl delete secret <cluster-name> -n argocd
```

### ArgoCD Resources

```bash
# List all Applications
kubectl get applications -n argocd

# List all ApplicationSets
kubectl get applicationsets -n argocd

# List all AppProjects
kubectl get appprojects -n argocd

# Get Application status
kubectl get application <app-name> -n argocd -o jsonpath='{.status.sync.status}'

# Get Application health
kubectl get application <app-name> -n argocd -o jsonpath='{.status.health.status}'

# Watch Application sync
kubectl get application <app-name> -n argocd -w
```

### Debugging

```bash
# ArgoCD Server logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server -f

# ArgoCD Repo Server logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -f

# ArgoCD Application Controller logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f

# ApplicationSet Controller logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller -f

# Redis logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-redis -f
```

---

## Bootstrap Scripts

### Full Bootstrap Script

```bash
#!/bin/bash
# bootstrap-cluster.sh - Complete cluster bootstrap automation

set -euo pipefail

# Configuration
CLUSTER_NAME=""
ENVIRONMENT=""
REGION=""
NODE_TYPE=""
INFRA_REPO_PATH=""
VALUES_REPO_PATH=""

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --name) CLUSTER_NAME="$2"; shift 2 ;;
    --environment) ENVIRONMENT="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --node-type) NODE_TYPE="$2"; shift 2 ;;
    --infra-repo) INFRA_REPO_PATH="$2"; shift 2 ;;
    --values-repo) VALUES_REPO_PATH="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# Validate required arguments
[[ -z "$CLUSTER_NAME" ]] && { echo "ERROR: --name required"; exit 1; }
[[ -z "$ENVIRONMENT" ]] && { echo "ERROR: --environment required"; exit 1; }
[[ -z "$REGION" ]] && { echo "ERROR: --region required"; exit 1; }

# Default values
NODE_TYPE="${NODE_TYPE:-standard}"
INFRA_REPO_PATH="${INFRA_REPO_PATH:-./infra-team}"
VALUES_REPO_PATH="${VALUES_REPO_PATH:-./argo-cd-helm-values}"

echo "=== ArgoCD Cluster Bootstrap ==="
echo "Cluster: $CLUSTER_NAME"
echo "Environment: $ENVIRONMENT"
echo "Region: $REGION"
echo "Node Type: $NODE_TYPE"
echo ""

# Step 1: Verify prerequisites
echo "Step 1: Verifying prerequisites..."
command -v argocd >/dev/null || { echo "ERROR: argocd CLI not found"; exit 1; }
command -v kubectl >/dev/null || { echo "ERROR: kubectl not found"; exit 1; }

# Step 2: Verify cluster connectivity
echo "Step 2: Verifying cluster connectivity..."
kubectl config use-context "aks-${CLUSTER_NAME}" || { echo "ERROR: Cannot switch to cluster context"; exit 1; }
kubectl get nodes || { echo "ERROR: Cannot access cluster"; exit 1; }

# Step 3: Add cluster to ArgoCD
echo "Step 3: Adding cluster to ArgoCD..."
kubectl config use-context aks-example-app-default  # Switch to hub
argocd cluster add "aks-${CLUSTER_NAME}" --name "$CLUSTER_NAME" --yes || true

# Step 4: Generate cluster secret
echo "Step 4: Generating cluster secret..."
SERVER_URL=$(argocd cluster get "$CLUSTER_NAME" -o json | jq -r '.server')

cat > "${INFRA_REPO_PATH}/argocd-clusters/${CLUSTER_NAME}.yaml" << EOF
apiVersion: v1
kind: Secret
metadata:
  name: ${CLUSTER_NAME}
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
    environment: ${ENVIRONMENT}
    region: ${REGION}
    cluster-name: ${CLUSTER_NAME}
    node-type: ${NODE_TYPE}
    connection-type: internal
    tier: application
type: Opaque
stringData:
  name: ${CLUSTER_NAME}
  server: ${SERVER_URL}
EOF

echo "Generated: ${INFRA_REPO_PATH}/argocd-clusters/${CLUSTER_NAME}.yaml"

# Step 5: Generate ArgoCD Project
echo "Step 5: Generating ArgoCD Project..."
cat > "${INFRA_REPO_PATH}/argocd-projects/${CLUSTER_NAME}.yaml" << EOF
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: ${CLUSTER_NAME}
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  description: "${CLUSTER_NAME} Cluster Project"
  sourceRepos:
    - '*'
  destinations:
    - namespace: '*'
      server: ${SERVER_URL}
      name: ${CLUSTER_NAME}
  clusterResourceWhitelist:
    - group: '*'
      kind: '*'
  namespaceResourceWhitelist:
    - group: '*'
      kind: '*'
  orphanedResources:
    warn: true
EOF

echo "Generated: ${INFRA_REPO_PATH}/argocd-projects/${CLUSTER_NAME}.yaml"

# Step 6: Create values directories
echo "Step 6: Creating values directories..."
COMPONENTS=(
  "cert-manager"
  "external-secrets"
  "ingress-nginx"
  "prometheus-stack"
  "loki"
  "external-dns"
)

for component in "${COMPONENTS[@]}"; do
  mkdir -p "${VALUES_REPO_PATH}/kube-addons/${component}/${CLUSTER_NAME}"

  # Create base values file
  cat > "${VALUES_REPO_PATH}/kube-addons/${component}/${CLUSTER_NAME}/values.yaml" << EOF
# ${component} values for ${CLUSTER_NAME}
# Environment: ${ENVIRONMENT}
# Region: ${REGION}

# Add component-specific overrides here
EOF

  echo "Created: ${VALUES_REPO_PATH}/kube-addons/${component}/${CLUSTER_NAME}/values.yaml"
done

# Step 7: Add spot tolerations for dev
if [[ "$ENVIRONMENT" == "dev" && "$NODE_TYPE" == "spot" ]]; then
  echo "Step 7: Adding spot tolerations..."
  for component in "${COMPONENTS[@]}"; do
    cat >> "${VALUES_REPO_PATH}/kube-addons/${component}/${CLUSTER_NAME}/values.yaml" << EOF

# Spot instance configuration
tolerations:
  - key: "kubernetes.azure.com/scalesetpriority"
    operator: "Equal"
    value: "spot"
    effect: "NoSchedule"

nodeSelector:
  kubernetes.azure.com/scalesetpriority: spot
EOF
  done
fi

echo ""
echo "=== Bootstrap Complete ==="
echo ""
echo "Next steps:"
echo "1. Review generated files"
echo "2. Commit and push to Git repositories"
echo "3. Verify cluster appears in ArgoCD UI"
echo "4. Monitor ApplicationSet sync"
```

### Validation Script

```bash
#!/bin/bash
# validate-cluster.sh - Validate cluster bootstrap

set -euo pipefail

CLUSTER_NAME="${1:-}"

[[ -z "$CLUSTER_NAME" ]] && { echo "Usage: $0 <cluster-name>"; exit 1; }

echo "=== Validating Cluster: $CLUSTER_NAME ==="

# Check 1: Cluster in ArgoCD
echo -n "Checking ArgoCD cluster registration... "
if argocd cluster get "$CLUSTER_NAME" &>/dev/null; then
  echo "PASS"
else
  echo "FAIL"
  exit 1
fi

# Check 2: Cluster connectivity
echo -n "Checking cluster connectivity... "
STATUS=$(argocd cluster get "$CLUSTER_NAME" -o json | jq -r '.connectionState.status')
if [[ "$STATUS" == "Successful" ]]; then
  echo "PASS"
else
  echo "FAIL (Status: $STATUS)"
  exit 1
fi

# Check 3: Cluster secret exists
echo -n "Checking cluster secret... "
if kubectl get secret "$CLUSTER_NAME" -n argocd &>/dev/null; then
  echo "PASS"
else
  echo "FAIL"
  exit 1
fi

# Check 4: Cluster secret labels
echo -n "Checking cluster secret labels... "
LABELS=$(kubectl get secret "$CLUSTER_NAME" -n argocd -o jsonpath='{.metadata.labels}')
if echo "$LABELS" | grep -q "environment"; then
  echo "PASS"
else
  echo "FAIL (Missing required labels)"
  exit 1
fi

# Check 5: ArgoCD Project exists
echo -n "Checking ArgoCD project... "
if argocd proj get "$CLUSTER_NAME" &>/dev/null; then
  echo "PASS"
else
  echo "FAIL"
  exit 1
fi

# Check 6: Applications synced
echo -n "Checking applications... "
APP_COUNT=$(argocd app list --dest-name "$CLUSTER_NAME" -o json | jq length)
if [[ "$APP_COUNT" -gt 0 ]]; then
  echo "PASS ($APP_COUNT apps)"
else
  echo "WARNING (No apps found)"
fi

# Check 7: Application health
echo "Checking application health..."
argocd app list --dest-name "$CLUSTER_NAME" -o json | \
  jq -r '.[] | "\(.metadata.name): \(.status.sync.status) / \(.status.health.status)"'

echo ""
echo "=== Validation Complete ==="
```

### Cleanup Script

```bash
#!/bin/bash
# cleanup-cluster.sh - Remove cluster from ArgoCD

set -euo pipefail

CLUSTER_NAME="${1:-}"
DRY_RUN="${2:-true}"

[[ -z "$CLUSTER_NAME" ]] && { echo "Usage: $0 <cluster-name> [dry-run=true|false]"; exit 1; }

echo "=== Cleanup Cluster: $CLUSTER_NAME ==="
echo "Dry Run: $DRY_RUN"
echo ""

# List affected applications
echo "Applications to be deleted:"
argocd app list --dest-name "$CLUSTER_NAME" -o name

if [[ "$DRY_RUN" == "false" ]]; then
  echo ""
  echo "Proceeding with cleanup..."

  # Delete applications
  for app in $(argocd app list --dest-name "$CLUSTER_NAME" -o name); do
    echo "Deleting application: $app"
    argocd app delete "$app" --cascade --yes
  done

  # Remove cluster from ArgoCD
  echo "Removing cluster from ArgoCD..."
  argocd cluster rm "$CLUSTER_NAME"

  # Delete cluster secret
  echo "Deleting cluster secret..."
  kubectl delete secret "$CLUSTER_NAME" -n argocd --ignore-not-found

  # Delete project
  echo "Deleting ArgoCD project..."
  kubectl delete appproject "$CLUSTER_NAME" -n argocd --ignore-not-found

  echo ""
  echo "=== Cleanup Complete ==="
  echo ""
  echo "Manual steps required:"
  echo "1. Remove cluster files from infra-team repo"
  echo "2. Remove values files from argo-cd-helm-values repo"
  echo "3. (Optional) Delete AKS cluster from Azure"
else
  echo ""
  echo "Dry run complete. Run with 'false' to execute cleanup."
fi
```

---

## Helm Commands

### Repository Management

```bash
# Add common repositories
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add jetstack https://charts.jetstack.io
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo add grafana https://grafana.github.io/helm-charts

# Update repositories
helm repo update

# Search for charts
helm search repo <keyword>

# Show chart values
helm show values <chart>
```

### Template Testing

```bash
# Template chart locally
helm template <release-name> <chart> -f values.yaml

# Template with multiple value files
helm template <release-name> <chart> \
  -f base-values.yaml \
  -f env-values.yaml \
  -f cluster-values.yaml

# Validate chart
helm lint <chart-path>

# Diff against deployed release
helm diff upgrade <release-name> <chart> -f values.yaml
```

---

## Azure CLI Commands

### AKS Management

```bash
# Get credentials
az aks get-credentials \
  --resource-group <rg-name> \
  --name <cluster-name> \
  --admin

# List clusters
az aks list --output table

# Show cluster details
az aks show \
  --resource-group <rg-name> \
  --name <cluster-name>

# Get cluster version
az aks show \
  --resource-group <rg-name> \
  --name <cluster-name> \
  --query kubernetesVersion

# Scale node pool
az aks nodepool scale \
  --resource-group <rg-name> \
  --cluster-name <cluster-name> \
  --name <nodepool-name> \
  --node-count <count>

# Upgrade cluster
az aks upgrade \
  --resource-group <rg-name> \
  --name <cluster-name> \
  --kubernetes-version <version>
```

### Identity Management

```bash
# Get managed identity
az aks show \
  --resource-group <rg-name> \
  --name <cluster-name> \
  --query identity

# Assign role to managed identity
az role assignment create \
  --assignee <identity-client-id> \
  --role <role-name> \
  --scope <scope>
```

---

## Git Workflow Commands

```bash
# Create feature branch
git checkout -b feat/add-cluster-<cluster-name>

# Stage changes
git add infra-team/argocd-clusters/<cluster-name>.yaml
git add infra-team/argocd-projects/<cluster-name>.yaml

# Commit with conventional message
git commit -m "feat(cluster): add <cluster-name> cluster registration

- Add cluster secret with labels
- Add ArgoCD project
- Configure for <environment> environment"

# Push and create PR
git push origin feat/add-cluster-<cluster-name>

# Run pre-commit hooks
pre-commit run --all-files
```
