# ArgoCD Cluster Bootstrapping - Best Practices & Guidance

Comprehensive guide covering best practices, security considerations, troubleshooting, and common patterns for cluster bootstrapping.

---

## Best Practices

### Naming Conventions

#### Cluster Names
```
Pattern: <business-unit>-<environment>[-<variant>]

Examples:
  example-app-dev         # Primary dev cluster
  example-app-dev-02      # Secondary dev cluster
  loyalty-prd          # Loyalty production
  example-app2-hlg   # Panel clients homologation
```

#### ApplicationSet Names
```
Pattern: <component>-<scope>[-<variant>]

Examples:
  ingress-nginx-all-clusters    # Deployed to all clusters
  prometheus-stack-platform     # Platform monitoring
  app-example-app-dev              # ExampleApp dev applications
```

#### Secret Names
```
Pattern: Match cluster name exactly

Example:
  Cluster: example-app-dev-02
  Secret:  example-app-dev-02 (in argocd namespace)
```

### Label Strategy

#### Required Labels (All Clusters)
```yaml
labels:
  argocd.argoproj.io/secret-type: cluster  # Required by ArgoCD
  environment: <env>                        # dev|hlg|prd|hub
  region: <region>                          # Azure region code
  cluster-name: <name>                      # Developer-friendly name
```

#### Recommended Labels
```yaml
labels:
  node-type: <type>          # spot|standard|mixed
  connection-type: <type>    # internal|external
  tier: <tier>               # platform|application
  business-unit: <unit>      # example-app|loyalty|etc
  cost-center: <code>        # For billing tracking
```

#### ApplicationSet Targeting Examples
```yaml
# Target all dev clusters
selector:
  matchLabels:
    environment: dev

# Target all platform tier clusters
selector:
  matchLabels:
    tier: platform

# Target specific business unit in production
selector:
  matchLabels:
    business-unit: example-app
    environment: prd

# Target clusters with spot instances
selector:
  matchLabels:
    node-type: spot
```

### Environment-Specific Configurations

#### Development (dev)
```yaml
# Sync Policy
syncPolicy:
  automated:
    prune: true
    selfHeal: true
  syncOptions:
    - CreateNamespace=true

# Resources
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi

# Replicas
replicaCount: 1

# Spot Tolerations (required for dev)
tolerations:
  - key: "kubernetes.azure.com/scalesetpriority"
    operator: "Equal"
    value: "spot"
    effect: "NoSchedule"
```

#### Homologation (hlg)
```yaml
# Sync Policy
syncPolicy:
  automated:
    prune: true
    selfHeal: false  # Manual intervention for staging
  syncOptions:
    - CreateNamespace=true

# Resources
resources:
  requests:
    cpu: 250m
    memory: 256Mi
  limits:
    cpu: 1000m
    memory: 1Gi

# Replicas
replicaCount: 2
```

#### Production (prd)
```yaml
# Sync Policy (manual sync recommended)
syncPolicy:
  syncOptions:
    - CreateNamespace=true
    - PruneLast=true
    - ApplyOutOfSyncOnly=true

# Resources
resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    cpu: 2000m
    memory: 2Gi

# Replicas
replicaCount: 3

# Pod Disruption Budget
podDisruptionBudget:
  enabled: true
  minAvailable: 2

# Anti-affinity for HA
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchLabels:
            app: myapp
        topologyKey: kubernetes.io/hostname
```

---

## Security Considerations

### Cluster Registration Security

#### Use Azure AD Workload Identity
```yaml
# Preferred: Azure AD authentication
config: |
  {
    "execProviderConfig": {
      "command": "argocd-k8s-auth",
      "args": ["azure"],
      "apiVersion": "client.authentication.k8s.io/v1beta1"
    }
  }
```

#### Avoid Service Account Tokens
```yaml
# Avoid: Long-lived tokens
config: |
  {
    "bearerToken": "eyJhbGciOiJSUzI1NiIsI..."  # BAD PRACTICE
  }
```

### RBAC Best Practices

#### Minimal Project Permissions
```yaml
# Good: Specific namespace destinations
destinations:
  - namespace: 'app-*'
    server: https://cluster-server
  - namespace: 'monitoring'
    server: https://cluster-server

# Bad: Wildcard everything
destinations:
  - namespace: '*'
    server: '*'
```

#### Cluster Resource Restrictions
```yaml
# Good: Limited cluster resources
clusterResourceWhitelist:
  - group: ''
    kind: Namespace
  - group: rbac.authorization.k8s.io
    kind: ClusterRole
  - group: rbac.authorization.k8s.io
    kind: ClusterRoleBinding

# Avoid: All cluster resources
clusterResourceWhitelist:
  - group: '*'
    kind: '*'
```

### Secret Management

#### External Secrets Pattern
```yaml
# Use ExternalSecret for sensitive data
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: database-credentials
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: azure-keyvault
    kind: ClusterSecretStore
  target:
    name: database-credentials
  data:
    - secretKey: password
      remoteRef:
        key: database-password
```

#### Never Commit Secrets
```yaml
# .gitignore
*.secret.yaml
*-secret.yaml
secrets/
.env
```

---

## Troubleshooting Guide

### Common Issues

#### Issue: Cluster Shows "Unknown" Status

**Symptoms:**
- Cluster appears in ArgoCD but shows "Unknown" connection state
- Applications cannot sync

**Diagnosis:**
```bash
# Check ArgoCD logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=100

# Check cluster connectivity
argocd cluster get <cluster-name>

# Test network connectivity
kubectl exec -n argocd deploy/argocd-server -- curl -k <cluster-api-url>/healthz
```

**Solutions:**
1. Verify network connectivity between hub and target cluster
2. Check if cluster API server is accessible
3. Verify cluster credentials are valid
4. Ensure firewall rules allow traffic on port 443

---

#### Issue: ApplicationSet Not Generating Applications

**Symptoms:**
- ApplicationSet exists but no Applications are created
- Expected clusters not targeted

**Diagnosis:**
```bash
# Check ApplicationSet controller logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller --tail=100

# Verify generator parameters
argocd appset get <appset-name> --show-params

# Check cluster labels
kubectl get secret -n argocd -l argocd.argoproj.io/secret-type=cluster --show-labels
```

**Solutions:**
1. Verify cluster secret has correct labels
2. Check selector matches cluster labels exactly
3. Ensure cluster secret is in `argocd` namespace
4. Verify `argocd.argoproj.io/secret-type: cluster` label exists

---

#### Issue: Sync Failed - "Permission Denied"

**Symptoms:**
- Application sync fails with RBAC error
- "User 'system:serviceaccount:argocd:argocd-application-controller' cannot..."

**Diagnosis:**
```bash
# Check project permissions
argocd proj get <project-name>

# Verify destination is allowed
argocd proj get <project-name> -o json | jq '.spec.destinations'

# Check cluster resource whitelist
argocd proj get <project-name> -o json | jq '.spec.clusterResourceWhitelist'
```

**Solutions:**
1. Add destination to project
2. Whitelist required cluster resources
3. Whitelist required namespace resources

---

#### Issue: Multi-Source Application Not Syncing

**Symptoms:**
- Application shows "OutOfSync" but sync appears to do nothing
- Values from secondary source not applied

**Diagnosis:**
```bash
# Get application sources
argocd app get <app-name> -o json | jq '.spec.sources'

# Check repo server can access sources
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server --tail=100 | grep -i error

# Verify value file paths
ls -la <repo>/kube-addons/<component>/<cluster>/
```

**Solutions:**
1. Verify all source repositories are accessible
2. Check value file paths match exactly
3. Ensure Helm chart version is correct
4. Verify `$values` reference in helm.valueFiles

---

#### Issue: Spot Instance Pods Not Scheduling

**Symptoms:**
- Pods stuck in Pending state on dev clusters
- Events show "FailedScheduling"

**Diagnosis:**
```bash
# Check pod events
kubectl describe pod <pod-name> -n <namespace>

# Check node labels
kubectl get nodes --show-labels | grep spot

# Verify tolerations in deployment
kubectl get deploy <deployment> -n <namespace> -o yaml | grep -A10 tolerations
```

**Solutions:**
1. Add spot tolerations to deployment:
```yaml
tolerations:
  - key: "kubernetes.azure.com/scalesetpriority"
    operator: "Equal"
    value: "spot"
    effect: "NoSchedule"
```

2. Add nodeSelector:
```yaml
nodeSelector:
  kubernetes.azure.com/scalesetpriority: spot
```

---

### Diagnostic Commands

```bash
# Full cluster diagnostic
argocd-cluster-diagnostic() {
  local cluster=$1
  echo "=== Cluster: $cluster ==="

  echo -e "\n--- Connection Status ---"
  argocd cluster get "$cluster"

  echo -e "\n--- Cluster Secret ---"
  kubectl get secret "$cluster" -n argocd -o yaml | head -30

  echo -e "\n--- Applications on Cluster ---"
  argocd app list --dest-name "$cluster"

  echo -e "\n--- Recent Events ---"
  kubectl get events -n argocd --sort-by='.lastTimestamp' | tail -20

  echo -e "\n--- Controller Logs ---"
  kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=50 | grep -i "$cluster"
}

# Application diagnostic
argocd-app-diagnostic() {
  local app=$1
  echo "=== Application: $app ==="

  echo -e "\n--- Status ---"
  argocd app get "$app"

  echo -e "\n--- Sync Status ---"
  argocd app get "$app" -o json | jq '.status.sync'

  echo -e "\n--- Health Status ---"
  argocd app get "$app" -o json | jq '.status.health'

  echo -e "\n--- Resources ---"
  argocd app resources "$app"

  echo -e "\n--- Diff ---"
  argocd app diff "$app" || true

  echo -e "\n--- Events ---"
  kubectl get events -n argocd --field-selector involvedObject.name="$app" --sort-by='.lastTimestamp'
}
```

---

## Common Patterns

### Multi-Source Application Pattern

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ingress-nginx
spec:
  sources:
    # Source 1: Helm chart from public repo
    - repoURL: https://kubernetes.github.io/ingress-nginx
      chart: ingress-nginx
      targetRevision: 4.9.0
      helm:
        valueFiles:
          - $values/kube-addons/ingress-nginx/base/values.yaml
          - $values/kube-addons/ingress-nginx/{{name}}/values.yaml

    # Source 2: Values from private repo (referenced as $values)
    - repoURL: https://github.com/org/argo-cd-helm-values.git
      targetRevision: main
      ref: values
```

### Cluster Generator with Matrix Pattern

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: platform-apps
spec:
  generators:
    - matrix:
        generators:
          # Generator 1: List of applications
          - list:
              elements:
                - app: cert-manager
                  chart: cert-manager
                  repo: https://charts.jetstack.io
                - app: external-secrets
                  chart: external-secrets
                  repo: https://charts.external-secrets.io

          # Generator 2: Target clusters
          - clusters:
              selector:
                matchLabels:
                  tier: platform

  template:
    metadata:
      name: '{{app}}-{{name}}'
    spec:
      project: platform
      sources:
        - repoURL: '{{repo}}'
          chart: '{{chart}}'
          targetRevision: '*'
          helm:
            valueFiles:
              - $values/kube-addons/{{app}}/{{name}}/values.yaml
        - repoURL: https://github.com/org/argo-cd-helm-values.git
          targetRevision: main
          ref: values
      destination:
        server: '{{server}}'
        namespace: '{{app}}'
```

### Progressive Rollout Pattern

```yaml
# Deploy to dev first, then hlg, then prd
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: progressive-app
spec:
  generators:
    - clusters:
        selector:
          matchLabels:
            environment: dev
        values:
          wave: "1"
    - clusters:
        selector:
          matchLabels:
            environment: hlg
        values:
          wave: "2"
    - clusters:
        selector:
          matchLabels:
            environment: prd
        values:
          wave: "3"

  template:
    metadata:
      name: 'myapp-{{name}}'
      annotations:
        argocd.argoproj.io/sync-wave: '{{wave}}'
```

---

## Pre-Commit Validation

### Required Checks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: validate-cluster-secrets
        name: Validate Cluster Secrets
        entry: scripts/validate-cluster-secrets.sh
        language: script
        files: 'argocd-clusters/.*\.yaml$'

      - id: validate-applicationsets
        name: Validate ApplicationSets
        entry: scripts/validate-applicationsets.sh
        language: script
        files: 'applicationset/.*\.yaml$'

      - id: check-spot-tolerations
        name: Check Spot Tolerations (Dev)
        entry: scripts/check-spot-tolerations.sh
        language: script
        files: 'kube-addons/.*dev.*/values\.yaml$'

      - id: helm-lint
        name: Helm Lint
        entry: helm lint
        language: system
        files: 'helm-charts/.*'
```

### Validation Script Example

```bash
#!/bin/bash
# validate-cluster-secrets.sh

set -e

for file in "$@"; do
  echo "Validating: $file"

  # Check required labels
  if ! grep -q "argocd.argoproj.io/secret-type: cluster" "$file"; then
    echo "ERROR: Missing required label 'argocd.argoproj.io/secret-type: cluster'"
    exit 1
  fi

  if ! grep -q "environment:" "$file"; then
    echo "ERROR: Missing required label 'environment'"
    exit 1
  fi

  if ! grep -q "cluster-name:" "$file"; then
    echo "ERROR: Missing required label 'cluster-name'"
    exit 1
  fi

  # Validate YAML syntax
  if ! yq eval '.' "$file" > /dev/null 2>&1; then
    echo "ERROR: Invalid YAML syntax"
    exit 1
  fi

  echo "OK: $file"
done
```
