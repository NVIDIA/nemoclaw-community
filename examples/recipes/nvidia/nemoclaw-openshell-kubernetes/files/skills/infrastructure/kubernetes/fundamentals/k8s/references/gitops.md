# GitOps Reference — ArgoCD & Flux

GitOps uses Git as the single source of truth for declarative infrastructure. Changes are made via pull requests, and a controller syncs cluster state to match Git.

---

## Table of Contents

1. [Core Principles](#core-principles)
2. [ArgoCD](#argocd)
3. [Flux](#flux)
4. [Shared Patterns](#shared-patterns)

---

## Core Principles

| Principle | What it means |
|-----------|--------------|
| **Declarative** | Desired state is described in Git, not applied imperatively |
| **Versioned** | Every change is a Git commit with history, authorship, and rollback |
| **Automated** | Controllers continuously reconcile cluster state to match Git |
| **Observable** | Drift detection shows when cluster diverges from desired state |

**Workflow:**
1. Developer pushes code → CI builds image → CI updates manifest in Git
2. GitOps controller detects Git change
3. Controller applies changes to cluster
4. Drift is detected and corrected automatically

---

## ArgoCD

### Installation

```bash
# Install ArgoCD
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Install CLI
brew install argocd

# Get initial admin password
argocd admin initial-password -n argocd

# Port-forward UI
kubectl port-forward svc/argocd-server -n argocd 8080:443

# Login via CLI
argocd login localhost:8080
```

### Application CRD

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: myapp
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/k8s-manifests.git
    targetRevision: main
    path: apps/myapp/overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: production
  syncPolicy:
    automated:
      prune: true              # Delete resources removed from Git
      selfHeal: true           # Revert manual changes in cluster
      allowEmpty: false        # Don't sync if source is empty
    syncOptions:
      - CreateNamespace=true
      - ApplyOutOfSyncOnly=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

### Application with Helm Source

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: myapp-helm
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/helm-charts.git
    targetRevision: main
    path: charts/myapp
    helm:
      valueFiles:
        - values.yaml
        - values-production.yaml
      parameters:
        - name: image.tag
          value: v1.2.3
  destination:
    server: https://kubernetes.default.svc
    namespace: production
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### Application with Helm Repository

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: prometheus
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://prometheus-community.github.io/helm-charts
    chart: kube-prometheus-stack
    targetRevision: 55.5.0
    helm:
      valueFiles:
        - $values/monitoring/values-production.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: monitoring
```

### App-of-Apps Pattern

A parent Application manages child Applications — scales to hundreds of services.

```yaml
# apps/root-app.yaml — the parent
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: root-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/k8s-manifests.git
    targetRevision: main
    path: apps                 # Directory containing child Application YAMLs
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

```yaml
# apps/myapp.yaml — a child Application
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: myapp
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/k8s-manifests.git
    targetRevision: main
    path: services/myapp/overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: production
```

### ApplicationSet (Multi-Cluster / Multi-Env)

Generate Applications dynamically from templates.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: myapp-environments
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - env: dev
            cluster: https://dev-cluster.example.com
            namespace: dev
          - env: staging
            cluster: https://staging-cluster.example.com
            namespace: staging
          - env: production
            cluster: https://prod-cluster.example.com
            namespace: production
  template:
    metadata:
      name: "myapp-{{env}}"
    spec:
      project: default
      source:
        repoURL: https://github.com/org/k8s-manifests.git
        targetRevision: main
        path: "apps/myapp/overlays/{{env}}"
      destination:
        server: "{{cluster}}"
        namespace: "{{namespace}}"
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

### ArgoCD CLI Commands

```bash
# Application management
argocd app list
argocd app get myapp
argocd app sync myapp                          # Trigger sync
argocd app sync myapp --force                  # Force sync (recreate resources)
argocd app sync myapp --prune                  # Sync and prune deleted resources
argocd app wait myapp                          # Wait for sync to complete

# Rollback
argocd app history myapp                       # View sync history
argocd app rollback myapp <revision>           # Rollback to revision

# Diff
argocd app diff myapp                          # Show diff between Git and cluster

# Health and status
argocd app get myapp -o tree                   # Show resource tree
argocd app resources myapp                     # List all managed resources

# Project management
argocd proj list
argocd proj get default

# Repository management
argocd repo add https://github.com/org/repo.git --username git --password <token>
argocd repo list

# Cluster management (multi-cluster)
argocd cluster add <context-name>
argocd cluster list
```

### ArgoCD Sync Waves and Hooks

Control the order of resource deployment:

```yaml
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "-1"     # Negative = deploy first
    # Wave order: -1 (namespaces, CRDs) → 0 (default) → 1 (apps) → 2 (tests)
```

Pre/post sync hooks:

```yaml
metadata:
  annotations:
    argocd.argoproj.io/hook: PreSync       # Run before sync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
# Hook types: PreSync, Sync, PostSync, SyncFail, Skip
```

### ArgoCD Health Checks

```bash
# Check application health
argocd app get myapp | grep -E "Health|Sync"

# Custom health check (in argocd-cm ConfigMap)
# Useful for CRDs that ArgoCD doesn't know how to assess
```

| Health Status | Meaning |
|---------------|---------|
| Healthy | All resources are running as expected |
| Progressing | Resources are being created/updated |
| Degraded | One or more resources are unhealthy |
| Suspended | Application is paused |
| Missing | Resources exist in Git but not in cluster |

| Sync Status | Meaning |
|-------------|---------|
| Synced | Cluster matches Git |
| OutOfSync | Cluster differs from Git |

---

## Flux

### Installation

```bash
# Install Flux CLI
brew install fluxcd/tap/flux

# Bootstrap Flux into cluster (creates Git repo structure)
flux bootstrap github \
  --owner=org \
  --repository=fleet-infra \
  --branch=main \
  --path=clusters/production \
  --personal=false

# Check status
flux check
```

### GitRepository Source

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: k8s-manifests
  namespace: flux-system
spec:
  interval: 5m
  url: https://github.com/org/k8s-manifests.git
  ref:
    branch: main
  secretRef:
    name: git-credentials        # For private repos
```

### Kustomization (Deploy from Git)

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: myapp
  namespace: flux-system
spec:
  interval: 10m
  targetNamespace: production
  sourceRef:
    kind: GitRepository
    name: k8s-manifests
  path: ./apps/myapp/overlays/production
  prune: true                    # Delete resources removed from Git
  healthChecks:
    - apiVersion: apps/v1
      kind: Deployment
      name: myapp
      namespace: production
  timeout: 5m
  retryInterval: 2m
```

### HelmRepository + HelmRelease

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: bitnami
  namespace: flux-system
spec:
  interval: 1h
  url: https://charts.bitnami.com/bitnami
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: postgresql
  namespace: production
spec:
  interval: 10m
  chart:
    spec:
      chart: postgresql
      version: "12.x"
      sourceRef:
        kind: HelmRepository
        name: bitnami
        namespace: flux-system
  values:
    auth:
      postgresPassword: "${POSTGRES_PASSWORD}"
      database: myapp
    primary:
      resources:
        requests:
          cpu: 250m
          memory: 256Mi
  valuesFrom:
    - kind: Secret
      name: postgresql-values
      valuesKey: values.yaml
  upgrade:
    remediation:
      retries: 3
  rollback:
    cleanupOnFail: true
```

### Image Automation (Auto-Update on New Image)

```yaml
# Watch a container registry for new tags
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImageRepository
metadata:
  name: myapp
  namespace: flux-system
spec:
  image: registry.example.com/myapp
  interval: 5m
---
# Policy: use latest semver tag
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImagePolicy
metadata:
  name: myapp
  namespace: flux-system
spec:
  imageRepositoryRef:
    name: myapp
  policy:
    semver:
      range: ">=1.0.0"
---
# Auto-update manifests in Git when new image matches policy
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImageUpdateAutomation
metadata:
  name: myapp
  namespace: flux-system
spec:
  interval: 5m
  sourceRef:
    kind: GitRepository
    name: k8s-manifests
  git:
    checkout:
      ref:
        branch: main
    commit:
      author:
        name: flux
        email: flux@example.com
      messageTemplate: "chore: update myapp to {{.NewTag}}"
    push:
      branch: main
  update:
    path: ./apps/myapp
    strategy: Setters
```

In the Deployment manifest, mark which image to auto-update:

```yaml
containers:
  - name: myapp
    image: registry.example.com/myapp:1.2.3  # {"$imagepolicy": "flux-system:myapp"}
```

### Flux CLI Commands

```bash
# Status
flux get all                                   # All Flux resources
flux get kustomizations                        # Kustomization status
flux get helmreleases -A                       # HelmRelease status across namespaces
flux get sources git                           # Git source status

# Reconcile (force sync)
flux reconcile kustomization myapp             # Trigger immediate sync
flux reconcile helmrelease postgresql -n prod  # Force Helm reconcile
flux reconcile source git k8s-manifests        # Force Git fetch

# Suspend / Resume
flux suspend kustomization myapp               # Pause syncing
flux resume kustomization myapp                # Resume syncing

# Logs and debugging
flux logs                                      # All controller logs
flux logs --kind=Kustomization --name=myapp    # Specific resource logs
flux events                                    # Recent events

# Export (backup)
flux export kustomization myapp > myapp.yaml
flux export helmrelease postgresql -n prod > postgresql.yaml

# Uninstall
flux uninstall
```

### Flux Multi-Cluster Structure

```
fleet-infra/
├── clusters/
│   ├── dev/
│   │   ├── flux-system/          # Flux bootstrap (auto-generated)
│   │   └── apps.yaml             # Kustomization pointing to apps/dev
│   ├── staging/
│   │   ├── flux-system/
│   │   └── apps.yaml
│   └── production/
│       ├── flux-system/
│       └── apps.yaml
├── apps/
│   ├── base/                     # Shared manifests
│   │   └── myapp/
│   │       ├── deployment.yaml
│   │       ├── service.yaml
│   │       └── kustomization.yaml
│   ├── dev/
│   │   └── kustomization.yaml    # Patches for dev
│   ├── staging/
│   │   └── kustomization.yaml
│   └── production/
│       └── kustomization.yaml
└── infrastructure/
    ├── base/                     # Shared infra (cert-manager, ingress-nginx)
    └── production/               # Prod-specific infra config
```

---

## Shared Patterns

### Git Repository Structure

```
k8s-manifests/
├── apps/                         # Application workloads
│   ├── myapp/
│   │   ├── base/                 # Shared manifests
│   │   │   ├── deployment.yaml
│   │   │   ├── service.yaml
│   │   │   ├── hpa.yaml
│   │   │   └── kustomization.yaml
│   │   └── overlays/
│   │       ├── dev/
│   │       │   ├── kustomization.yaml
│   │       │   └── patch-replicas.yaml
│   │       ├── staging/
│   │       └── production/
│   └── another-app/
├── infrastructure/               # Cluster infrastructure
│   ├── cert-manager/
│   ├── ingress-nginx/
│   ├── monitoring/
│   └── sealed-secrets/
└── clusters/                     # Cluster-specific entry points
    ├── dev/
    ├── staging/
    └── production/
```

### Environment Promotion

**PR-based promotion (recommended):**

```
feature branch → dev (auto-sync)
                  ↓
          PR to staging branch → staging (auto-sync)
                                   ↓
                           PR to main → production (auto/manual sync)
```

Each promotion is a pull request with review and approval.

**Image tag promotion:**

```bash
# CI updates dev overlay with new image tag
# After testing, promote to staging:
cd apps/myapp/overlays/staging
kustomize edit set image myapp=registry.example.com/myapp:v1.2.3
git commit -m "promote myapp v1.2.3 to staging"

# After staging validation, promote to production:
cd apps/myapp/overlays/production
kustomize edit set image myapp=registry.example.com/myapp:v1.2.3
git commit -m "promote myapp v1.2.3 to production"
```

### Secrets in GitOps

Never commit plaintext secrets to Git. Use one of these approaches:

**Sealed Secrets (Bitnami):**

```bash
# Encrypt secret for Git storage
kubectl create secret generic myapp-secrets \
  --from-literal=API_KEY=sk-xxx \
  --dry-run=client -o yaml | \
  kubeseal --format yaml > sealed-secret.yaml

# Safe to commit sealed-secret.yaml to Git
# Only the controller in-cluster can decrypt
```

**SOPS + age (Mozilla):**

```bash
# Encrypt a file
sops --encrypt --age <public-key> secrets.yaml > secrets.enc.yaml

# Decrypt in-cluster via Flux/ArgoCD integration
# Flux: use decryption provider in Kustomization
# ArgoCD: use argocd-vault-plugin or SOPS plugin
```

**Flux Kustomization with SOPS:**

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: myapp
  namespace: flux-system
spec:
  decryption:
    provider: sops
    secretRef:
      name: sops-age-key       # Secret containing the age private key
  sourceRef:
    kind: GitRepository
    name: k8s-manifests
  path: ./apps/myapp
```

**External Secrets Operator:**

```yaml
# ExternalSecret syncs from AWS SM / Vault / GCP SM into K8s Secret
# Managed by GitOps — only the ExternalSecret CRD is in Git, not the secret values
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: myapp-secrets
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: myapp-secrets
  data:
    - secretKey: API_KEY
      remoteRef:
        key: production/myapp
        property: api_key
```

### ArgoCD vs Flux — When to Use Which

| Aspect | ArgoCD | Flux |
|--------|--------|------|
| **UI** | Built-in web dashboard | No UI (use Grafana dashboards or Weave GitOps) |
| **Multi-cluster** | Built-in, manage from central server | Bootstrap per cluster, manage via Git |
| **Helm support** | As source in Application CRD | Native HelmRelease CRD with remediation |
| **Image automation** | Via ArgoCD Image Updater (separate) | Native ImagePolicy + ImageUpdateAutomation |
| **RBAC** | Built-in project-level RBAC | Delegates to K8s RBAC |
| **Complexity** | More components, more features | Lightweight, K8s-native CRDs |
| **Best for** | Teams wanting visibility + multi-cluster from one place | Teams wanting GitOps purity + lightweight footprint |
| **Backing** | Intuit + Akuity (strong commercial) | CNCF graduated (Weaveworks shut down 2024) |

### Rollback Patterns

**ArgoCD:**
```bash
argocd app history myapp
argocd app rollback myapp <revision>
# Or: revert the Git commit and let auto-sync fix it
```

**Flux:**
```bash
# Revert the Git commit — Flux auto-reconciles
git revert HEAD
git push

# Or suspend and manually rollback:
flux suspend kustomization myapp
kubectl rollout undo deployment/myapp -n production
# Fix the issue, then:
flux resume kustomization myapp
```

**Best practice:** Always rollback via Git revert, not manual kubectl commands. This keeps Git as the source of truth.
