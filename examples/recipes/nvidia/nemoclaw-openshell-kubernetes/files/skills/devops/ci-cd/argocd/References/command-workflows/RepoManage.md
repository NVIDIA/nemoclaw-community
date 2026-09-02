# RepoManage Workflow

Manage ArgoCD repository connections - add, list, remove Git/Helm/OCI repos.

## Kubeconfig Reference

All kubectl commands in this workflow use the example-app-hub cluster kubeconfig:
```bash
export KUBECONFIG=~/.kube/aks-rg-example-hub-config
# Or use: kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config ...
```

## Quick Commands

| Action | Command |
|--------|---------|
| List repos | `argocd repo list` |
| Get repo | `argocd repo get <url>` |
| Add repo | `argocd repo add <url>` |
| Remove repo | `argocd repo rm <url>` |

## List Repositories

```bash
# List all configured repositories
argocd repo list

# List with specific output
argocd repo list -o wide
argocd repo list -o json
argocd repo list -o yaml
```

## Get Repository Details

```bash
# Get repository details
argocd repo get <repo-url>

# Get as JSON
argocd repo get <repo-url> -o json

# Example
argocd repo get https://github.com/org/repo.git
```

## Add Repository

### Git Repository (HTTPS)

```bash
# Public repository
argocd repo add https://github.com/org/repo.git

# Private repository with username/password
argocd repo add https://github.com/org/repo.git \
  --username <username> \
  --password <password-or-token>

# With GitHub token
argocd repo add https://github.com/org/repo.git \
  --username git \
  --password <github-token>
```

### Git Repository (SSH)

```bash
# Add SSH repository
argocd repo add git@github.com:org/repo.git \
  --ssh-private-key-path ~/.ssh/id_rsa

# With specific SSH key
argocd repo add git@ssh.dev.azure.com:v3/your-org/project/repo \
  --ssh-private-key-path ~/.ssh/azure_devops_key

# Example: Azure DevOps SSH
argocd repo add git@ssh.dev.azure.com:v3/your-org/rg-example-web/Repos \
  --ssh-private-key-path ~/.ssh/id_rsa \
  --name example-app-repos
```

### Helm Repository

```bash
# Public Helm repository
argocd repo add https://charts.bitnami.com/bitnami --type helm --name bitnami

# Private Helm repository with auth
argocd repo add https://charts.example.com \
  --type helm \
  --name private-charts \
  --username <username> \
  --password <password>

# Common public Helm repos
argocd repo add https://prometheus-community.github.io/helm-charts --type helm --name prometheus
argocd repo add https://grafana.github.io/helm-charts --type helm --name grafana
argocd repo add https://charts.jetstack.io --type helm --name jetstack
argocd repo add https://kubernetes-sigs.github.io/external-dns --type helm --name external-dns
```

### OCI Repository

```bash
# Add OCI registry
argocd repo add oci://registry.example.com/charts \
  --type helm \
  --name oci-charts \
  --username <username> \
  --password <password>

# Azure Container Registry
argocd repo add oci://myacr.azurecr.io/helm \
  --type helm \
  --enable-oci \
  --username <sp-client-id> \
  --password <sp-client-secret>
```

### With Custom Name

```bash
# Add repository with friendly name
argocd repo add https://github.com/org/repo.git --name my-app-repo
```

### With Project Restriction

```bash
# Add repository restricted to specific project
argocd repo add https://github.com/org/repo.git --project my-project
```

## Remove Repository

```bash
# Remove repository
argocd repo rm <repo-url>

# Examples
argocd repo rm https://github.com/org/repo.git
argocd repo rm git@github.com:org/repo.git
argocd repo rm https://charts.bitnami.com/bitnami
```

## Repository Credentials Templates

Credential templates allow reusing credentials across multiple repositories.

### List Credential Templates

```bash
# List repository credential templates
argocd repocreds list
```

### Add Credential Template

```bash
# HTTPS credential template (matches all repos under URL)
argocd repocreds add https://github.com/org \
  --username git \
  --password <github-token>

# SSH credential template
argocd repocreds add git@github.com:org \
  --ssh-private-key-path ~/.ssh/id_rsa

# Azure DevOps credential template
argocd repocreds add git@ssh.dev.azure.com:v3/your-org \
  --ssh-private-key-path ~/.ssh/azure_key
```

### Remove Credential Template

```bash
argocd repocreds rm <url-pattern>
```

## Repository Secrets (Kubernetes)

### View Repository Secrets

```bash
# List repository secrets (example-app-hub)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config get secrets -n argocd -l argocd.argoproj.io/secret-type=repository

# Get specific repository secret
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config get secret -n argocd <repo-secret-name> -o yaml
```

### Create Repository Secret Manually

```yaml
# Git repository with SSH key
apiVersion: v1
kind: Secret
metadata:
  name: repo-example-app
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
type: Opaque
stringData:
  type: git
  url: git@ssh.dev.azure.com:v3/your-org/rg-example-web/Repos
  sshPrivateKey: |
    -----BEGIN OPENSSH PRIVATE KEY-----
    ...
    -----END OPENSSH PRIVATE KEY-----
---
# Helm repository with credentials
apiVersion: v1
kind: Secret
metadata:
  name: repo-private-helm
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
type: Opaque
stringData:
  type: helm
  name: private-charts
  url: https://charts.example.com
  username: admin
  password: secret123
```

### Credential Template Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: creds-github
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repo-creds
type: Opaque
stringData:
  type: git
  url: https://github.com/myorg
  username: git
  password: <github-token>
```

## Troubleshooting

### Test Repository Connection

```bash
# Check repository status
argocd repo get <url> -o json | jq '.connectionState'

# Test git clone
git ls-remote <repo-url>

# Test Helm repo
helm repo add test <helm-repo-url> && helm search repo test/
```

### Common Issues

```bash
# SSH known hosts issue
argocd cert add-ssh --batch --from-file /etc/ssh/ssh_known_hosts

# TLS certificate issue
argocd cert add-tls <hostname> --from /path/to/cert.pem

# Check repo server logs (example-app-hub)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -f
```

### Refresh Repository

```bash
# Force repository refresh
argocd app get <app-name> --hard-refresh
```
