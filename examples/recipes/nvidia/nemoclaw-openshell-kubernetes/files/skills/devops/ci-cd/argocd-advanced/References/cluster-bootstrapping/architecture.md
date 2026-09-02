# ArgoCD Cluster Bootstrapping - Architecture Deep Dive

Comprehensive architecture documentation for the multi-repository GitOps environment.

---

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              CONTROL PLANE                                      │
│  ┌───────────────────────────────────────────────────────────────────────────┐ │
│  │                         HUB CLUSTER (aks-example-app-default)                │ │
│  │                                                                           │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │ │
│  │  │   ArgoCD    │  │   ArgoCD    │  │ ApplicationSet│  │    Cluster     │  │ │
│  │  │   Server    │  │  Repo Server│  │  Controller   │  │    Secrets     │  │ │
│  │  └──────┬──────┘  └──────┬──────┘  └───────┬───────┘  └────────┬────────┘  │ │
│  │         │                │                 │                   │          │ │
│  │         └────────────────┴────────┬────────┴───────────────────┘          │ │
│  │                                   │                                        │ │
│  │                          ┌────────▼────────┐                              │ │
│  │                          │  Application    │                              │ │
│  │                          │  Controller     │                              │ │
│  │                          └────────┬────────┘                              │ │
│  └───────────────────────────────────┼───────────────────────────────────────┘ │
└──────────────────────────────────────┼──────────────────────────────────────────┘
                                       │
           ┌───────────────────────────┼───────────────────────────┐
           │                           │                           │
           ▼                           ▼                           ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│   DEV CLUSTERS      │   │   HLG CLUSTERS      │   │   PRD CLUSTERS      │
│                     │   │                     │   │                     │
│ ┌─────────────────┐ │   │ ┌─────────────────┐ │   │ ┌─────────────────┐ │
│ │ example-app-dev    │ │   │ │ example-app-hlg    │ │   │ │ example-app-prd    │ │
│ │ loyalty-dev     │ │   │ │ loyalty-hlg     │ │   │ │ loyalty-prd     │ │
│ │ example-app3-dev      │ │   │ │ example-app3-hlg      │ │   │ │ example-app3-prd      │ │
│ └─────────────────┘ │   │ └─────────────────┘ │   │ └─────────────────┘ │
│                     │   │                     │   │                     │
│ Features:           │   │ Features:           │   │ Features:           │
│ - Spot instances    │   │ - Mixed nodes       │   │ - Standard nodes    │
│ - Auto sync         │   │ - Manual sync opt   │   │ - Manual sync       │
│ - 1 replica         │   │ - 2 replicas        │   │ - 3 replicas HA     │
│ - Prune enabled     │   │ - Prune enabled     │   │ - Prune disabled    │
└─────────────────────┘   └─────────────────────┘   └─────────────────────┘
```

---

## Repository Architecture

### Multi-Repository Pattern

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           GIT REPOSITORIES                                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────────────┐        ┌─────────────────────────┐                │
│  │     infra-team/         │        │  argo-cd-helm-values/   │                │
│  │   (Infrastructure)      │        │  (Environment Values)   │                │
│  │                         │        │                         │                │
│  │ ├── applicationset/     │        │ └── kube-addons/        │                │
│  │ │   ├── kube-addons/    │        │     ├── cert-manager/   │                │
│  │ │   └── applications/   │        │     │   ├── dev/        │                │
│  │ ├── argocd-clusters/    │        │     │   ├── hlg/        │                │
│  │ │   ├── example-app-dev    │        │     │   └── prd/        │                │
│  │ │   ├── example-app-hlg    │        │     ├── ingress-nginx/  │                │
│  │ │   └── example-app-prd    │        │     ├── prometheus/     │                │
│  │ ├── argocd-projects/    │        │     └── ...             │                │
│  │ └── helm-charts/        │        │                         │                │
│  │     └── (base charts)   │        │                         │                │
│  └─────────────────────────┘        └─────────────────────────┘                │
│              │                                  │                               │
│              │    Security Boundary             │                               │
│              │    (Different access controls)   │                               │
│              └─────────────┬────────────────────┘                               │
│                            │                                                    │
│                            ▼                                                    │
│                  ┌─────────────────────┐                                       │
│                  │   ArgoCD Server     │                                       │
│                  │   (Multi-Source)    │                                       │
│                  └─────────────────────┘                                       │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Directory Structure Detail

#### infra-team/ Repository
```
infra-team/
├── applicationset/                    # ApplicationSet definitions
│   ├── kube-addons/                  # Platform components
│   │   ├── cert-manager.yaml         # Certificate management
│   │   ├── external-secrets.yaml     # Secret management
│   │   ├── ingress-nginx.yaml        # Ingress controller
│   │   ├── prometheus-stack.yaml     # Monitoring
│   │   ├── loki.yaml                 # Logging
│   │   └── external-dns.yaml         # DNS management
│   ├── applications/                 # Business applications
│   │   ├── example-app/
│   │   ├── loyalty/
│   │   └── example-app2/
│   └── master-applicationset.yaml    # Orchestrator AppSet
│
├── argocd-clusters/                  # Cluster registration
│   ├── example-app-dev.yaml
│   ├── example-app-hlg.yaml
│   ├── example-app-prd.yaml
│   ├── loyalty-dev.yaml
│   └── ...
│
├── argocd-projects/                  # RBAC definitions
│   ├── platform.yaml                 # Platform team project
│   ├── example-app.yaml                 # ExampleApp business unit
│   ├── loyalty.yaml                  # Loyalty business unit
│   └── ...
│
├── argocd/                           # ArgoCD configuration
│   ├── argocd-cm.yaml               # ConfigMap
│   ├── argocd-rbac-cm.yaml          # RBAC ConfigMap
│   └── argocd-secret.yaml           # Secrets
│
├── applicationset-templates/         # Reusable templates
│   ├── multi-source-helm.yaml
│   ├── cluster-generator.yaml
│   └── matrix-generator.yaml
│
└── helm-charts/                      # Custom Helm charts
    ├── common/                       # Shared templates
    └── applications/                 # Business app charts
```

#### argo-cd-helm-values/ Repository
```
argo-cd-helm-values/
└── kube-addons/
    ├── cert-manager/
    │   ├── base/                     # Base values (all envs)
    │   │   └── values.yaml
    │   ├── example-app-dev/             # Cluster-specific
    │   │   └── values.yaml
    │   ├── example-app-hlg/
    │   │   └── values.yaml
    │   └── example-app-prd/
    │       └── values.yaml
    │
    ├── ingress-nginx/
    │   ├── base/
    │   │   └── values.yaml
    │   ├── example-app-dev/
    │   │   └── values.yaml           # Spot tolerations
    │   ├── example-app-hlg/
    │   │   └── values.yaml           # 2 replicas
    │   └── example-app-prd/
    │       └── values.yaml           # 3 replicas, HA
    │
    ├── prometheus-stack/
    │   ├── base/
    │   ├── example-app-dev/
    │   ├── example-app-hlg/
    │   └── example-app-prd/
    │
    └── ... (28+ components)
```

---

## Cluster Secret Architecture

### Secret Structure

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: example-app-dev                            # Must match cluster name
  namespace: argocd                             # Always in argocd namespace
  labels:
    # Required: Identifies as cluster secret
    argocd.argoproj.io/secret-type: cluster

    # Targeting Labels (used by ApplicationSets)
    environment: dev                            # Environment tier
    region: brazilsouth                         # Geographic region
    cluster-name: example-app-dev                  # Cluster identifier
    node-type: spot                             # Node type (spot/standard/mixed)
    connection-type: internal                   # Network type
    tier: application                           # Cluster tier

    # Optional: Additional metadata
    business-unit: example-app
    cost-center: CC-001

type: Opaque
stringData:
  name: example-app-dev                            # Display name in ArgoCD
  server: https://aks-example-app-dev-xxx.hcp.brazilsouth.azmk8s.io:443
  config: |
    {
      "execProviderConfig": {
        "command": "argocd-k8s-auth",
        "args": ["azure", "--cluster-name", "aks-example-app-dev"],
        "apiVersion": "client.authentication.k8s.io/v1beta1"
      },
      "tlsClientConfig": {
        "insecure": false,
        "caData": "LS0tLS1CRUdJTi..."
      }
    }
```

### Label Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│                      LABEL HIERARCHY                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Level 1: System Labels (Required)                             │
│  ├── argocd.argoproj.io/secret-type: cluster                   │
│                                                                 │
│  Level 2: Environment Labels (Required)                        │
│  ├── environment: dev|hlg|prd|hub                              │
│  ├── cluster-name: <unique-identifier>                         │
│                                                                 │
│  Level 3: Infrastructure Labels (Recommended)                  │
│  ├── region: brazilsouth|eastus2|...                           │
│  ├── node-type: spot|standard|mixed                            │
│  ├── connection-type: internal|external                        │
│  ├── tier: platform|application                                │
│                                                                 │
│  Level 4: Business Labels (Optional)                           │
│  ├── business-unit: example-app|loyalty|...                       │
│  ├── cost-center: <billing-code>                               │
│  └── owner: <team-name>                                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## ApplicationSet Architecture

### Generator Types

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        APPLICATIONSET GENERATORS                                │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────┐     Use When:                                             │
│  │ List Generator  │     - Small, fixed set of targets                         │
│  │                 │     - Different parameters per target                     │
│  │ elements:       │     - Non-cluster based generation                        │
│  │   - cluster: a  │                                                           │
│  │   - cluster: b  │                                                           │
│  └─────────────────┘                                                           │
│                                                                                 │
│  ┌─────────────────┐     Use When:                                             │
│  │Cluster Generator│     - Dynamic cluster discovery                           │
│  │                 │     - Label-based targeting                               │
│  │ selector:       │     - All clusters matching criteria                      │
│  │   matchLabels:  │                                                           │
│  │     env: dev    │                                                           │
│  └─────────────────┘                                                           │
│                                                                                 │
│  ┌─────────────────┐     Use When:                                             │
│  │ Git Generator   │     - Config-as-code from Git                             │
│  │                 │     - Directory-based generation                          │
│  │ repoURL: ...    │     - File-based generation                               │
│  │ directories:    │                                                           │
│  │   - path: apps/*│                                                           │
│  └─────────────────┘                                                           │
│                                                                                 │
│  ┌─────────────────┐     Use When:                                             │
│  │Matrix Generator │     - Cartesian product needed                            │
│  │                 │     - Multiple dimensions                                 │
│  │ generators:     │     - Apps × Clusters                                     │
│  │   - list: ...   │                                                           │
│  │   - clusters:...│                                                           │
│  └─────────────────┘                                                           │
│                                                                                 │
│  ┌─────────────────┐     Use When:                                             │
│  │ Merge Generator │     - Combining results                                   │
│  │                 │     - Override values                                     │
│  │ generators:     │     - Complex targeting                                   │
│  │   - ...         │                                                           │
│  │ mergeKeys:      │                                                           │
│  │   - name        │                                                           │
│  └─────────────────┘                                                           │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Multi-Source Application Flow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     MULTI-SOURCE APPLICATION FLOW                              │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  Source 1: Helm Chart              Source 2: Values Reference                   │
│  ┌──────────────────────┐         ┌──────────────────────┐                     │
│  │ repoURL: helm-repo   │         │ repoURL: values-repo │                     │
│  │ chart: ingress-nginx │         │ targetRevision: main │                     │
│  │ targetRevision: 4.9.0│         │ ref: values          │ ◄── Reference name  │
│  │ helm:                │         └──────────────────────┘                     │
│  │   valueFiles:        │                    │                                 │
│  │     - $values/base   │◄───────────────────┘ Using $values reference         │
│  │     - $values/cluster│                                                      │
│  └──────────────────────┘                                                      │
│             │                                                                   │
│             ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────┐          │
│  │                    VALUES MERGE ORDER                            │          │
│  │                                                                  │          │
│  │  1. Chart default values.yaml                                    │          │
│  │           ↓                                                      │          │
│  │  2. Base values (argo-cd-helm-values/kube-addons/app/base/)     │          │
│  │           ↓                                                      │          │
│  │  3. Cluster values (argo-cd-helm-values/kube-addons/app/cluster/)│          │
│  │           ↓                                                      │          │
│  │  Final merged values applied to cluster                          │          │
│  └──────────────────────────────────────────────────────────────────┘          │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Network Architecture

### Hub-and-Spoke Model

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            NETWORK TOPOLOGY                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│                        ┌───────────────────┐                                   │
│                        │   Azure VNet Hub  │                                   │
│                        │   (10.0.0.0/16)   │                                   │
│                        └─────────┬─────────┘                                   │
│                                  │                                              │
│           ┌──────────────────────┼──────────────────────┐                      │
│           │                      │                      │                      │
│           ▼                      ▼                      ▼                      │
│  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐              │
│  │  DEV VNet       │   │  HLG VNet       │   │  PRD VNet       │              │
│  │  (10.1.0.0/16)  │   │  (10.2.0.0/16)  │   │  (10.3.0.0/16)  │              │
│  │                 │   │                 │   │                 │              │
│  │ ┌─────────────┐ │   │ ┌─────────────┐ │   │ ┌─────────────┐ │              │
│  │ │ AKS Subnet  │ │   │ │ AKS Subnet  │ │   │ │ AKS Subnet  │ │              │
│  │ │10.1.0.0/22  │ │   │ │10.2.0.0/22  │ │   │ │10.3.0.0/22  │ │              │
│  │ └─────────────┘ │   │ └─────────────┘ │   │ └─────────────┘ │              │
│  └─────────────────┘   └─────────────────┘   └─────────────────┘              │
│                                                                                 │
│  Traffic Flow:                                                                  │
│  ─────────────                                                                  │
│  Hub ArgoCD ──(HTTPS/443)──► Spoke AKS API Server                              │
│  Hub ArgoCD ◄──(Metrics)──── Spoke Prometheus                                  │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Firewall Rules Required

```
┌───────────────┬──────────────────┬──────────┬───────────────────────────┐
│ Source        │ Destination      │ Port     │ Purpose                   │
├───────────────┼──────────────────┼──────────┼───────────────────────────┤
│ Hub ArgoCD    │ Spoke AKS API    │ 443/TCP  │ Cluster management        │
│ Hub ArgoCD    │ GitHub/GitLab    │ 443/TCP  │ Git operations            │
│ Hub ArgoCD    │ Helm Repos       │ 443/TCP  │ Chart fetching            │
│ Spoke Apps    │ Hub Monitoring   │ 443/TCP  │ Metrics/Logs forwarding   │
│ Developers    │ Hub ArgoCD UI    │ 443/TCP  │ UI access                 │
└───────────────┴──────────────────┴──────────┴───────────────────────────┘
```

---

## Sync Flow Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          SYNC FLOW DIAGRAM                                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   ┌─────────┐      ┌─────────────┐      ┌─────────────────┐                    │
│   │   Git   │      │  Repo       │      │  Application    │                    │
│   │  Commit │─────►│  Server     │─────►│  Controller     │                    │
│   └─────────┘      └─────────────┘      └────────┬────────┘                    │
│                           │                      │                              │
│                           │                      │                              │
│                    ┌──────▼──────┐               │                              │
│                    │   Manifest  │               │                              │
│                    │   Cache     │               │                              │
│                    └──────┬──────┘               │                              │
│                           │                      │                              │
│         ┌─────────────────┴──────────────────────┤                              │
│         │                                        │                              │
│         ▼                                        ▼                              │
│   ┌───────────┐                          ┌────────────┐                        │
│   │  Desired  │                          │   Live     │                        │
│   │   State   │◄────── COMPARE ─────────►│   State    │                        │
│   │(from Git) │                          │(from K8s)  │                        │
│   └─────┬─────┘                          └────────────┘                        │
│         │                                       ▲                               │
│         │                                       │                               │
│         │        ┌────────────────┐             │                               │
│         │        │   Sync Status  │             │                               │
│         │        │                │             │                               │
│         │        │ • Synced       │             │                               │
│         └───────►│ • OutOfSync    │◄────────────┘                               │
│                  │ • Unknown      │                                             │
│                  └────────┬───────┘                                             │
│                           │                                                     │
│                           ▼                                                     │
│                  ┌────────────────┐                                            │
│                  │  Sync Action   │                                            │
│                  │  (if automated)│                                            │
│                  └────────┬───────┘                                            │
│                           │                                                     │
│                           ▼                                                     │
│                  ┌────────────────┐                                            │
│                  │  Apply to      │                                            │
│                  │  Cluster       │                                            │
│                  └────────────────┘                                            │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## High Availability Architecture

### Production HA Setup

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    PRODUCTION HIGH AVAILABILITY                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  Availability Zone 1        Availability Zone 2        Availability Zone 3     │
│  ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐       │
│  │     Node 1      │       │     Node 2      │       │     Node 3      │       │
│  │                 │       │                 │       │                 │       │
│  │ ┌─────────────┐ │       │ ┌─────────────┐ │       │ ┌─────────────┐ │       │
│  │ │ App Pod     │ │       │ │ App Pod     │ │       │ │ App Pod     │ │       │
│  │ │ (Replica 1) │ │       │ │ (Replica 2) │ │       │ │ (Replica 3) │ │       │
│  │ └─────────────┘ │       │ └─────────────┘ │       │ └─────────────┘ │       │
│  └─────────────────┘       └─────────────────┘       └─────────────────┘       │
│                                                                                 │
│  Configuration:                                                                 │
│  ──────────────                                                                 │
│  • replicaCount: 3                                                             │
│  • podAntiAffinity: requiredDuringSchedulingIgnoredDuringExecution             │
│  • topologySpreadConstraints: zone distribution                                │
│  • podDisruptionBudget: minAvailable: 2                                        │
│                                                                                 │
│  Example Values:                                                                │
│  ───────────────                                                                │
│  affinity:                                                                      │
│    podAntiAffinity:                                                            │
│      requiredDuringSchedulingIgnoredDuringExecution:                           │
│        - labelSelector:                                                        │
│            matchLabels:                                                        │
│              app: myapp                                                        │
│          topologyKey: topology.kubernetes.io/zone                              │
│                                                                                 │
│  topologySpreadConstraints:                                                    │
│    - maxSkew: 1                                                                │
│      topologyKey: topology.kubernetes.io/zone                                  │
│      whenUnsatisfiable: DoNotSchedule                                          │
│      labelSelector:                                                            │
│        matchLabels:                                                            │
│          app: myapp                                                            │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```
