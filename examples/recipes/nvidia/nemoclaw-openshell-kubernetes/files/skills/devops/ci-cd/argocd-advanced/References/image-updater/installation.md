# ArgoCD Image Updater Installation Guide

## Prerequisites

- Kubernetes cluster with Argo CD installed
- kubectl configured to access your cluster
- Argo CD v1.0.0+ (v2.0+ for Git write-back)

## Installation Methods

### Method 1: Kubernetes Manifests (Recommended for Quick Start)

```bash
# Install in argocd namespace (same as Argo CD)
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj-labs/argocd-image-updater/stable/config/install.yaml
```

### Method 2: Kustomize

Create a `kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: argocd

resources:
  - https://raw.githubusercontent.com/argoproj-labs/argocd-image-updater/stable/config/install.yaml
```

Apply with:

```bash
kubectl apply -k .
```

### Method 3: Helm

```bash
# Add Argo Helm repository
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

# Install argocd-image-updater
helm install argocd-image-updater argo/argocd-image-updater \
  --namespace argocd \
  --create-namespace
```

#### Helm Values Example

```yaml
# values.yaml
replicaCount: 1

image:
  repository: quay.io/argoprojlabs/argocd-image-updater
  pullPolicy: Always
  tag: ""  # Uses chart appVersion

config:
  # ArgoCD API server address
  argocd:
    serverAddress: argocd-server.argocd.svc.cluster.local
    insecure: true
    plaintext: false

  # Log level (trace, debug, info, warn, error)
  logLevel: info

  # Registries configuration
  registries: []
    # - name: Docker Hub
    #   prefix: docker.io
    #   api_url: https://registry-1.docker.io
    #   default: true

serviceAccount:
  create: true
  name: argocd-image-updater

rbac:
  enabled: true
```

### Method 4: Separate Namespace Installation

For isolation, install in a dedicated namespace. This example follows the principle of least privilege by using namespaced Roles for secrets access while using ClusterRoles only where cluster-wide access is genuinely required.

> **Security Note:** Avoid granting cluster-wide access to secrets. The configuration below uses namespaced Roles to limit secrets access to specific namespaces where credentials are stored.

```bash
# Create namespace
kubectl create namespace argocd-image-updater

# Create RBAC with least privilege
kubectl apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: argocd-image-updater
  namespace: argocd-image-updater
---
# Namespaced Role for secrets access in the argocd namespace only
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: argocd-image-updater-secrets
  namespace: argocd
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: argocd-image-updater-secrets
  namespace: argocd
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: argocd-image-updater-secrets
subjects:
  - kind: ServiceAccount
    name: argocd-image-updater
    namespace: argocd-image-updater
---
# ClusterRole for resources that require cluster-wide access
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: argocd-image-updater
rules:
  # ConfigMaps needed for argocd-image-updater-config
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list", "watch"]
  # Applications may exist in multiple namespaces
  - apiGroups: ["argoproj.io"]
    resources: ["applications"]
    verbs: ["get", "list", "update", "patch"]
  # ImageUpdater CRDs are cluster-scoped
  - apiGroups: ["argocd-image-updater.argoproj.io"]
    resources: ["imageupdaters"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: argocd-image-updater
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: argocd-image-updater
subjects:
  - kind: ServiceAccount
    name: argocd-image-updater
    namespace: argocd-image-updater
EOF
```

If you store registry credentials in multiple namespaces, create additional RoleBindings:

```bash
# Example: Grant secrets access in 'production' namespace
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: argocd-image-updater-secrets
  namespace: production
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: argocd-image-updater-secrets
  namespace: production
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: argocd-image-updater-secrets
subjects:
  - kind: ServiceAccount
    name: argocd-image-updater
    namespace: argocd-image-updater
EOF
```

## Post-Installation Verification

### Check Pod Status

```bash
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-image-updater
```

Expected output:

```
NAME                                      READY   STATUS    RESTARTS   AGE
argocd-image-updater-xxxxxxxxxx-xxxxx     1/1     Running   0          1m
```

### Check Logs

```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-image-updater -f
```

### Verify CRD Installation

```bash
kubectl get crd imageupdaters.argocd-image-updater.argoproj.io
```

## Configuration

### ConfigMap Configuration

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-image-updater-config
  namespace: argocd
data:
  # Interval for checking image updates (default: 2m0s)
  registries.conf: |
    registries:
      - name: Docker Hub
        prefix: docker.io
        api_url: https://registry-1.docker.io
        default: true
      - name: GitHub Container Registry
        prefix: ghcr.io
        api_url: https://ghcr.io
      - name: Quay
        prefix: quay.io
        api_url: https://quay.io

  # Log level configuration
  log.level: info
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ARGOCD_SERVER` | Argo CD server address | `argocd-server:443` |
| `ARGOCD_INSECURE` | Skip TLS verification | `false` |
| `ARGOCD_PLAINTEXT` | Use HTTP instead of HTTPS | `false` |
| `ARGOCD_TOKEN` | Argo CD API token | - |
| `IMAGE_UPDATER_LOGLEVEL` | Log level | `info` |

## Upgrading

### From Manifests

```bash
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj-labs/argocd-image-updater/stable/config/install.yaml
```

### From Helm

```bash
helm repo update
helm upgrade argocd-image-updater argo/argocd-image-updater -n argocd
```

## Uninstallation

### Manifests

```bash
kubectl delete -n argocd -f https://raw.githubusercontent.com/argoproj-labs/argocd-image-updater/stable/config/install.yaml
```

### Helm

```bash
helm uninstall argocd-image-updater -n argocd
```

## Troubleshooting Installation

### Pod Not Starting

Check events:

```bash
kubectl describe pod -n argocd -l app.kubernetes.io/name=argocd-image-updater
```

Common issues:

- Missing RBAC permissions
- Unable to reach Argo CD API server
- Missing ConfigMap or Secret

### Connection to Argo CD Failing

Verify Argo CD server is accessible:

```bash
kubectl exec -n argocd deployment/argocd-image-updater -- \
  wget -qO- https://argocd-server.argocd.svc.cluster.local/api/version
```

### CRD Not Found

Install CRDs manually:

```bash
kubectl apply -f https://raw.githubusercontent.com/argoproj-labs/argocd-image-updater/stable/config/crds/argocd-image-updater.argoproj.io_imageupdaters.yaml
```
