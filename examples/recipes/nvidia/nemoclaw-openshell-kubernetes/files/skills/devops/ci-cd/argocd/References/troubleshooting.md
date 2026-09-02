# ArgoCD Troubleshooting Guide

Common issues and solutions for ArgoCD operations.

## Application Sync Issues

### OutOfSync Status

**Symptoms:** Application shows OutOfSync but sync does nothing

```bash
# Check diff to understand what's out of sync
argocd app diff myapp

# Force refresh from Git
argocd app get myapp --hard-refresh

# Check if ignoreDifferences is needed
argocd app get myapp -o yaml | grep -A20 ignoreDifferences
```

**Common causes:**

- Resource modified by controllers (replicas, status fields)
- Annotations/labels added by admission controllers
- Server-side defaults not in Git

**Solution:** Add `ignoreDifferences` to app spec:

```yaml
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas
    - group: "*"
      kind: "*"
      managedFieldsManagers:
        - kube-controller-manager
```

### Sync Failed

```bash
# Get detailed sync status
argocd app get myapp --show-operation

# Check sync result
argocd app get myapp -o json | jq '.status.operationState'

# View sync logs
argocd app logs myapp --filter-by-sync-id

# Check resource events
kubectl get events -n <namespace> --field-selector involvedObject.name=<resource>
```

### Sync Stuck/Hanging

```bash
# Terminate stuck operation
argocd app terminate-op myapp

# Check ArgoCD controller logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=100

# Force sync with replace
argocd app sync myapp --force --replace
```

## Health Status Issues

### Application Degraded

```bash
# Get resource health details
argocd app get myapp -o wide

# Check specific resource health
argocd app resources myapp --output tree

# View pod logs for unhealthy deployments
argocd app logs myapp --kind Deployment --name <deployment-name>
```

### Custom Health Checks

```bash
# Check if custom health check exists
kubectl get cm argocd-cm -n argocd -o yaml | grep -A50 "resource.customizations"

# Test health check
argocd admin settings resource-overrides health <kind> --argocd-cm-path argocd-cm.yaml
```

## Repository Issues

### Repository Connection Failed

```bash
# Test repository connection
argocd repo get https://github.com/org/repo --refresh

# List repositories with connection status
argocd repo list

# Re-add repository with credentials
argocd repo add https://github.com/org/repo --username git --password $TOKEN --upsert
```

### SSH Key Issues

```bash
# Add SSH known hosts
ssh-keyscan github.com | argocd cert add-ssh --batch

# List certificates
argocd cert list --cert-type ssh

# Test SSH connection manually
ssh -T git@github.com
```

### Helm Repository Issues

```bash
# Refresh Helm repository
argocd repo get https://charts.example.com --refresh

# Check Helm chart availability
helm search repo <repo-name>/<chart-name>

# Add Helm repo with credentials
argocd repo add https://charts.example.com \
  --type helm --name myrepo --username user --password pass
```

## Cluster Connection Issues

### Cluster Unreachable

```bash
# Check cluster status
argocd cluster list

# Get cluster details
argocd cluster get https://kubernetes.example.com

# Rotate cluster credentials
argocd cluster rotate-auth https://kubernetes.example.com

# Re-add cluster
argocd cluster add <context> --name <cluster-name> --upsert
```

### Permission Denied

```bash
# Check service account permissions
kubectl auth can-i --list \
  --as system:serviceaccount:argocd:argocd-application-controller \
  -n <target-namespace>

# Check cluster role bindings
kubectl get clusterrolebinding | grep argocd

# Check if namespace is in project destinations
argocd proj get <project> | grep destinations
```

## Authentication Issues

### Token Expired

```bash
# Generate new token
argocd account generate-token --account <account> --expires-in 7d

# Check token expiration
argocd account get-user-info

# Re-login
argocd login $ARGOCD_SERVER --username admin --password $PASSWORD
```

### SSO Issues

```bash
# Test OIDC configuration
argocd admin settings validate -n argocd

# Check Dex logs (if using Dex)
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-dex-server

# Force SSO re-login
argocd relogin --sso
```

### RBAC Permission Denied

```bash
# Check current permissions
argocd account can-i sync applications '*'
argocd account can-i get applications 'myproject/*'

# Test RBAC policy
argocd admin settings rbac can role:developer get applications '*/*'

# Validate RBAC policy file
argocd admin settings rbac validate --policy-file policy.csv
```

## Performance Issues

### Slow Sync

```bash
# Check controller queue depth
kubectl get --raw /metrics -n argocd | grep workqueue

# Check application count per controller
kubectl get applications.argoproj.io -A --no-headers | wc -l

# Enable selective sync
argocd app sync myapp --apply-out-of-sync-only
```

### High Memory Usage

```bash
# Check controller resource usage
kubectl top pods -n argocd

# Check repo-server cache
kubectl exec -n argocd deploy/argocd-repo-server -- ls -la /tmp

# Clear application cache
kubectl delete pods -n argocd -l app.kubernetes.io/name=argocd-repo-server
```

## Common Error Messages

### "permission denied"

```bash
# Check RBAC policy
argocd admin settings rbac can <role> <action> <resource> <subresource>

# Add policy to project role
argocd proj role add-policy <project> <role> -a <action> -p allow -o '<pattern>'
```

### "Unable to create application: application spec is invalid"

```bash
# Validate application manifest
argocd app create --file app.yaml --validate

# Check project restrictions
argocd proj get <project>

# Ensure destination is allowed
argocd proj add-destination <project> <server> <namespace>
```

### "repository not accessible"

```bash
# Check repository credentials
argocd repo get <repo-url>

# Test with git directly
GIT_SSH_COMMAND="ssh -v" git ls-remote <repo-url>

# Re-add with correct credentials
argocd repo add <repo-url> --username git --password $TOKEN --upsert
```

### "ComparisonError"

```bash
# Get detailed error
argocd app get myapp -o json | jq '.status.conditions'

# Check repo-server logs
kubectl logs -n argocd deploy/argocd-repo-server --tail=100

# Clear repo cache
kubectl delete pods -n argocd -l app.kubernetes.io/name=argocd-repo-server
```

## Debugging Commands

### ArgoCD Component Logs

```bash
# Application controller
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f

# API server
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server -f

# Repo server
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -f

# Redis
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-redis -f

# Dex (if using SSO)
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-dex-server -f
```

### Enable Debug Logging

```bash
# Patch controller for debug logging
kubectl patch configmap argocd-cmd-params-cm -n argocd --type merge -p '{"data":{"controller.log.level":"debug"}}'

# Restart controller
kubectl rollout restart deploy/argocd-application-controller -n argocd
```

### API Debugging

```bash
# Check API health
curl -sk https://$ARGOCD_SERVER/healthz

# Get API version
curl -sk https://$ARGOCD_SERVER/api/version

# Test authenticated endpoint
curl -sk -H "Authorization: Bearer $ARGOCD_AUTH_TOKEN" https://$ARGOCD_SERVER/api/v1/applications
```

## Recovery Procedures

### Restore from Backup

```bash
# Export current state
argocd admin export > backup.yaml

# Import from backup
argocd admin import < backup.yaml
```

### Reset Admin Password

```bash
# Get initial password
argocd admin initial-password -n argocd

# Or reset using bcrypt
NEW_PASSWORD_HASH=$(argocd account bcrypt --password newpassword)
kubectl patch secret argocd-secret -n argocd -p '{"stringData":{"admin.password":"'"$NEW_PASSWORD_HASH"'"}}'
```

### Force Delete Stuck Application

```bash
# Remove finalizer
kubectl patch app myapp -n argocd -p '{"metadata":{"finalizers":null}}' --type merge

# Delete application
kubectl delete app myapp -n argocd
```

### Clear Resource Cache

```bash
# Invalidate cluster cache
argocd cluster get <cluster-url> --refresh

# Via API
curl -X POST -H "Authorization: Bearer $TOKEN" \
  "https://$ARGOCD_SERVER/api/v1/clusters/<cluster-url>/invalidate-cache"
```

## Useful Diagnostic One-Liners

```bash
# All apps with sync status
argocd app list -o json | \
  jq -r '.items[] | "\(.metadata.name): \(.status.sync.status)"'

# Apps that are OutOfSync
argocd app list -o json | \
  jq -r '.items[] | select(.status.sync.status != "Synced") | .metadata.name'

# Apps that are not Healthy
argocd app list -o json | \
  jq -r '.items[] | select(.status.health.status != "Healthy") | .metadata.name'

# Recent sync operations
argocd app list -o json | \
  jq -r '.items[] | "\(.metadata.name): \(.status.operationState.phase)"'

# Check all repository statuses
argocd repo list -o json | jq -r '.[] | "\(.repo): \(.connectionState.status)"'

# Check all cluster statuses
argocd cluster list -o json | jq -r '.items[] | "\(.name): \(.connectionState.status)"'
```
