# ClusterManage Workflow

Manage ArgoCD cluster registrations - add, list, remove, and rotate credentials.

## Kubeconfig Reference

All kubectl commands in this workflow use the example-app-hub cluster kubeconfig:
```bash
export KUBECONFIG=~/.kube/aks-rg-example-hub-config
# Or use: kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config ...
```

## Quick Commands

| Action | Command |
|--------|---------|
| List clusters | `argocd cluster list` |
| Get cluster | `argocd cluster get <server>` |
| Add cluster | `argocd cluster add <context>` |
| Remove cluster | `argocd cluster rm <server>` |
| Rotate auth | `argocd cluster rotate-auth <server>` |

## List Clusters

```bash
# List all registered clusters
argocd cluster list

# List with specific output
argocd cluster list -o wide
argocd cluster list -o json
argocd cluster list -o yaml

# List cluster names only
argocd cluster list -o name
```

## Get Cluster Details

```bash
# Get cluster details
argocd cluster get <server-url>

# Get as JSON
argocd cluster get <server-url> -o json

# Get by cluster name
argocd cluster get <cluster-name>

# Example
argocd cluster get https://kubernetes.default.svc
argocd cluster get example-app-hub
```

## Add Cluster

### From kubeconfig Context

```bash
# Add cluster from current kubeconfig context
argocd cluster add <context-name>

# Add with custom name
argocd cluster add <context-name> --name <friendly-name>

# Add in-cluster (for ArgoCD running in the cluster)
argocd cluster add <context-name> --in-cluster

# Add with specific kubeconfig
argocd cluster add <context-name> --kubeconfig /path/to/kubeconfig

# Add with namespace restrictions
argocd cluster add <context-name> --namespace <namespace>

# Add with labels
argocd cluster add <context-name> --label environment=production --label team=platform
```

### Add Azure AKS Cluster

```bash
# Get AKS credentials first
az aks get-credentials --resource-group <rg-name> --name <cluster-name>

# Add to ArgoCD
argocd cluster add <aks-context-name> --name <friendly-name>

# Example for example-app clusters
az aks get-credentials --resource-group rg-example-web --name aks-example-app-dev --admin
argocd cluster add aks-example-app-dev --name example-app-dev --label environment=dev
```

### Add with Service Account

```bash
# Add cluster with existing service account
argocd cluster add <context-name> --service-account argocd-manager

# Create service account in target cluster first
kubectl create serviceaccount argocd-manager -n kube-system
kubectl create clusterrolebinding argocd-manager --clusterrole=cluster-admin --serviceaccount=kube-system:argocd-manager
```

## Set Cluster Properties

```bash
# Set cluster name
argocd cluster set <server> --name <new-name>

# Set namespace restrictions
argocd cluster set <server> --namespace <namespace1>,<namespace2>

# Add labels
argocd cluster set <server> --label environment=production

# Set project restrictions
argocd cluster set <server> --project <project-name>
```

## Remove Cluster

```bash
# Remove cluster by server URL
argocd cluster rm <server-url>

# Remove cluster by name
argocd cluster rm <cluster-name>

# Example
argocd cluster rm https://10.0.0.1:6443
argocd cluster rm example-app-dev
```

## Rotate Cluster Credentials

```bash
# Rotate authentication credentials
argocd cluster rotate-auth <server-url>

# Rotate by cluster name
argocd cluster rotate-auth <cluster-name>
```

## Cluster Secrets (Kubernetes)

### View Cluster Secrets

```bash
# List cluster secrets (example-app-hub)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config get secrets -n argocd -l argocd.argoproj.io/secret-type=cluster

# Get specific cluster secret
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config get secret -n argocd <cluster-secret-name> -o yaml
```

### Create Cluster Secret Manually

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: cluster-example-app-dev
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
type: Opaque
stringData:
  name: example-app-dev
  server: https://10.0.0.1:6443
  config: |
    {
      "bearerToken": "<token>",
      "tlsClientConfig": {
        "insecure": false,
        "caData": "<base64-ca-cert>"
      }
    }
```

### Cluster with Azure Workload Identity

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: cluster-aks-example-app-dev
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
type: Opaque
stringData:
  name: example-app-dev
  server: https://aks-example-app-dev-xxxxx.hcp.brazilsouth.azmk8s.io:443
  config: |
    {
      "execProviderConfig": {
        "command": "argocd-k8s-auth",
        "args": ["azure"],
        "apiVersion": "client.authentication.k8s.io/v1beta1"
      },
      "tlsClientConfig": {
        "insecure": false,
        "caData": "<base64-ca-cert>"
      }
    }
```

## Troubleshooting

### Check Cluster Connectivity

```bash
# Test cluster connection
argocd cluster get <server> -o json | jq '.connectionState'

# Check cluster status in ArgoCD
kubectl get applications -A -o json | jq '.items[] | select(.spec.destination.server == "<server>") | .status.health'
```

### Common Issues

```bash
# Certificate issues - use insecure (not recommended for production)
argocd cluster add <context> --insecure

# Token expired - rotate credentials
argocd cluster rotate-auth <server>

# Permission issues - check service account
kubectl auth can-i --list --as=system:serviceaccount:kube-system:argocd-manager
```

### Check ArgoCD Application Controller Logs

```bash
# Check for cluster connection errors (example-app-hub)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f | grep -i "cluster"
```
