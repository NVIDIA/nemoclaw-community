# Login Workflow

Authenticate to ArgoCD server for the example-app-hub cluster.

## Cluster Configuration

| Setting | Value |
|---------|-------|
| **Kubeconfig** | `~/.kube/aks-rg-example-hub-config` |
| **ArgoCD Server** | `argocd.example.com` |
| **ArgoCD Namespace** | `argocd` |

## Connection Options

| Mode | Server | Command |
|------|--------|---------|
| **Production** | `argocd.example.com` | `argocd login argocd.example.com --sso` |
| **Port-Forward** | `localhost:8080` | `argocd login localhost:8080 --insecure` |

## Steps

### 1. Production Login (SSO)

```bash
# Set kubeconfig for example-app-hub
export KUBECONFIG=~/.kube/aks-rg-example-hub-config

# Login with Azure AD SSO
argocd login argocd.example.com --sso

# Verify login
argocd account get-user-info
```

### 2. Port-Forward Login (Development)

```bash
# Start port-forward in background (example-app-hub cluster)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config port-forward svc/argocd-server -n argocd 8080:443 &

# Login with insecure flag (self-signed cert)
argocd login localhost:8080 --insecure

# Get initial admin password (if needed)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

### 3. Token-Based Login

```bash
# Login with auth token
argocd login argocd.example.com --auth-token $ARGOCD_AUTH_TOKEN

# Generate new token
argocd account generate-token
```

## Context Management

```bash
# List available contexts
argocd context

# Switch context
argocd context <context-name>

# Delete context
argocd context --delete <context-name>
```

## Account Management

```bash
# Get current user info
argocd account get-user-info

# List accounts
argocd account list

# Update password
argocd account update-password

# Get account details
argocd account get --account <username>
```

## Logout

```bash
# Logout from current server
argocd logout argocd.example.com

# Relogin (refresh token)
argocd relogin
```

## Troubleshooting

### Certificate Issues
```bash
# Skip TLS verification
argocd login argocd.example.com --insecure

# Use specific CA certificate
argocd login argocd.example.com --certificate-authority /path/to/ca.crt
```

### Connection Issues
```bash
# Check server connectivity
curl -k https://argocd.example.com/api/version

# Check ArgoCD server pod (example-app-hub cluster)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config get pods -n argocd -l app.kubernetes.io/name=argocd-server
```
