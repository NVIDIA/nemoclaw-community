# ArgoCD Image Updater - Git Write-Back Configuration

Git write-back commits image updates directly to your Git repository, providing permanent, auditable changes that follow GitOps principles.

## Prerequisites

- Argo CD v2.0+ (for git write-back support)
- Git credentials with write access to the target repository
- SSH key or HTTPS token configured

## Basic Configuration

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: my-image-updater
  namespace: argocd
spec:
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@github.com:myorg/myrepo.git"
      branch: "main"
  applicationRefs:
    - namePattern: "my-app"
      images:
        - alias: "app"
          imageName: "myregistry/app"
```

## Write-Back Targets

### Default: .argocd-source File

Creates/updates `.argocd-source-<appName>.yaml`:

```yaml
writeBackConfig:
  method: "git"
  gitConfig:
    repository: "git@github.com:myorg/myrepo.git"
    branch: "main"
    # writeBackTarget defaults to creating .argocd-source-<appName>.yaml
```

Generated file example:

```yaml
# .argocd-source-my-app.yaml
helm:
  parameters:
    - name: image.tag
      value: "1.2.3"
```

### Kustomization Target

Updates `kustomization.yaml`:

```yaml
writeBackConfig:
  method: "git"
  gitConfig:
    repository: "git@github.com:myorg/myrepo.git"
    branch: "main"
    writeBackTarget: "kustomization"
```

Updates images section:

```yaml
# kustomization.yaml
images:
  - name: myregistry/app
    newTag: "1.2.3"
```

### Helm Values Target

Updates a specific Helm values file:

```yaml
writeBackConfig:
  method: "git"
  gitConfig:
    repository: "git@github.com:myorg/myrepo.git"
    branch: "main"
    writeBackTarget: "helmvalues:./values.yaml"
```

Requires manifest targets in image config:

```yaml
images:
  - alias: "app"
    imageName: "myregistry/app"
    manifestTargets:
      helm:
        name: "image.repository"
        tag: "image.tag"
```

## Git Authentication

### SSH Key Authentication

Create a secret with SSH private key:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: git-ssh-key
  namespace: argocd
type: Opaque
stringData:
  sshPrivateKey: |
    <SSH_PRIVATE_KEY_CONTENT>
    # Generate with: ssh-keygen -t ed25519 -C "argocd-image-updater"
```

Reference in ImageUpdater:

```yaml
writeBackConfig:
  method: "git"
  gitConfig:
    repository: "git@github.com:myorg/myrepo.git"
    branch: "main"
    credentials:
      sshPrivateKeySecret:
        name: git-ssh-key
        key: sshPrivateKey
```

### HTTPS Token Authentication

Create a secret with username and token:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: git-creds
  namespace: argocd
type: Opaque
stringData:
  username: git
  password: ghp_xxxxxxxxxxxxxxxxxxxx
```

Reference in ImageUpdater:

```yaml
writeBackConfig:
  method: "git"
  gitConfig:
    repository: "https://github.com/myorg/myrepo.git"
    branch: "main"
    credentials:
      usernamePasswordSecret:
        name: git-creds
        usernameKey: username
        passwordKey: password
```

### Using Argo CD Repository Credentials

If repository is already configured in Argo CD:

```yaml
writeBackConfig:
  method: "git"
  gitConfig:
    repository: "git@github.com:myorg/myrepo.git"
    branch: "main"
    credentials:
      argocdRepoServer: true  # Use Argo CD's stored credentials
```

## Commit Configuration

### Custom Commit Message

```yaml
writeBackConfig:
  method: "git"
  gitConfig:
    repository: "git@github.com:myorg/myrepo.git"
    branch: "main"
    commitMessage: |
      chore: update image {{ .ImageName }} to {{ .NewTag }}

      Application: {{ .AppName }}
      Previous: {{ .OldTag }}
      Strategy: {{ .UpdateStrategy }}
```

### Available Template Variables

| Variable | Description |
|----------|-------------|
| `{{ .AppName }}` | Argo CD application name |
| `{{ .ImageName }}` | Full image name |
| `{{ .ImageAlias }}` | Image alias |
| `{{ .NewTag }}` | New image tag |
| `{{ .OldTag }}` | Previous image tag |
| `{{ .UpdateStrategy }}` | Strategy used |

### Commit Author Configuration

```yaml
writeBackConfig:
  method: "git"
  gitConfig:
    repository: "git@github.com:myorg/myrepo.git"
    branch: "main"
    commitAuthor:
      name: "ArgoCD Image Updater"
      email: "image-updater@example.com"
```

## Branch Strategies

### Direct to Main Branch

```yaml
writeBackConfig:
  method: "git"
  gitConfig:
    repository: "git@github.com:myorg/myrepo.git"
    branch: "main"
```

### Feature Branch per Update

Not directly supported, but you can:

1. Use webhooks to create PRs
2. Use a bot that monitors commits and creates PRs

### Different Branch per Environment

```yaml
# Dev environment
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: dev-updater
spec:
  writeBackConfig:
    method: "git"
    gitConfig:
      branch: "develop"
---
# Production environment
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: prod-updater
spec:
  writeBackConfig:
    method: "git"
    gitConfig:
      branch: "main"
```

## Complete Example: Helm Application

```yaml
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: production-updater
  namespace: argocd
spec:
  namespace: argocd
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@github.com:myorg/helm-values.git"
      branch: "main"
      writeBackTarget: "helmvalues:./production/values.yaml"
      credentials:
        sshPrivateKeySecret:
          name: git-ssh-key
          key: sshPrivateKey
      commitMessage: |
        chore(production): update {{ .ImageAlias }} to {{ .NewTag }}

        Application: {{ .AppName }}
      commitAuthor:
        name: "Image Updater Bot"
        email: "bot@example.com"
  applicationRefs:
    - namePattern: "production-*"
      images:
        - alias: "backend"
          imageName: "myregistry/backend"
          commonUpdateSettings:
            updateStrategy: "semver"
          manifestTargets:
            helm:
              name: "backend.image.repository"
              tag: "backend.image.tag"
        - alias: "frontend"
          imageName: "myregistry/frontend"
          commonUpdateSettings:
            updateStrategy: "semver"
          manifestTargets:
            helm:
              name: "frontend.image.repository"
              tag: "frontend.image.tag"
```

## Troubleshooting Git Write-Back

### Permission Denied

```bash
# Check if secret exists
kubectl get secret git-ssh-key -n argocd

# Verify key format
kubectl get secret git-ssh-key -n argocd -o jsonpath='{.data.sshPrivateKey}' | base64 -d | head -1
```

### Branch Not Found

Ensure the branch exists in the remote repository:

```bash
git ls-remote --heads origin main
```

### Commit Not Appearing

Check Image Updater logs:

```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-image-updater | grep -i git
```

### Merge Conflicts

If manual changes conflict:

1. Resolve conflict in Git
2. Image Updater will retry on next cycle
