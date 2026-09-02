# CreateImageUpdaterCrds Workflow

Create ImageUpdater CRD custom resources to scope argocd-image-updater per environment.

## When to Use

- Scoping image updates to specific application name patterns (e.g., `dev-*`, `hlg-*`, `prd-*`)
- Moving from annotation-only config to CRD-based management
- Bringing manually-created ImageUpdater CRs under GitOps

## Step 1: Design the CRD Structure

Each `ImageUpdater` CR scopes the image updater to a set of ArgoCD Applications by name pattern.

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: updater-<env>
  namespace: argocd
spec:
  namespace: argocd
  applicationRefs:
    - namePattern: <env>-*
      useAnnotations: true
```

### Configuration Options

| Field | Description |
|-------|-------------|
| `namePattern` | Glob pattern matching ArgoCD Application names |
| `useAnnotations` | Use annotations on each Application for image config |
| `images` | Inline image update config (alternative to annotations) |
| `commonUpdateSettings.updateStrategy` | Default strategy: semver, newest-build, digest, alphabetical |

## Step 2: Add to Helm Values via extraObjects

Add CRs to the `extraObjects` key in the Helm values file:

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
  - apiVersion: argocd-image-updater.argoproj.io/v1alpha1
    kind: ImageUpdater
    metadata:
      name: updater-hlg
      namespace: argocd
    spec:
      namespace: argocd
      applicationRefs:
        - namePattern: hlg-*
          useAnnotations: true
  - apiVersion: argocd-image-updater.argoproj.io/v1alpha1
    kind: ImageUpdater
    metadata:
      name: updater-prd
      namespace: argocd
    spec:
      namespace: argocd
      applicationRefs:
        - namePattern: prd-*
          useAnnotations: true
```

## Step 3: Validate

```bash
# Lint the values file
yamllint <values-file>

# Verify CRD exists in cluster
KUBECONFIG=~/.kube/<config> kubectl get crd imageupdaters.argocd-image-updater.argoproj.io

# After sync, check CRs are managed
KUBECONFIG=~/.kube/<config> kubectl get imageupdaters -n argocd
```

## Notes

- **yamllint**: Don't quote glob patterns like `dev-*` — yamllint flags redundant quotes
- **ServerSideApply**: If CRs already exist from manual `kubectl apply`, ArgoCD's `ServerSideApply=true` will adopt them without conflict
- **Finalizers**: The image updater controller adds `resources-finalizer.argocd-image-updater.argoproj.io` automatically
- **CRD installation**: Chart v1.1.1 installs the CRD by default (`crds.install: true`)
