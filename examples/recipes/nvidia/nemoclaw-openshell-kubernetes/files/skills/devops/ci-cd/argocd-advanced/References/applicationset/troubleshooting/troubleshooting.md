# ArgoCD ApplicationSet Troubleshooting Guide

## Quick Diagnostic Commands

```bash
# Check ApplicationSet status
kubectl get applicationset -n argocd

# Describe ApplicationSet for events and status
kubectl describe applicationset <name> -n argocd

# View ApplicationSet controller logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller -f

# Check generated Applications
kubectl get applications -n argocd -l app.kubernetes.io/instance=<applicationset-name>

# Check ArgoCD Application status
argocd app list
argocd app get <app-name>
```

---

## Common Issues and Solutions

### 1. ApplicationSet Not Generating Applications

**Symptoms:**
- ApplicationSet exists but no Applications are created
- `kubectl get applications` returns empty for expected apps

**Diagnostic Steps:**

```bash
# Check ApplicationSet status
kubectl describe applicationset <name> -n argocd

# Look for generator errors in controller logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller | grep -i error

# Verify generator is producing parameters
kubectl get applicationset <name> -n argocd -o yaml | grep -A 50 status
```

**Common Causes & Solutions:**

| Cause | Solution |
|-------|----------|
| Git repository not accessible | Verify repo URL and credentials in ArgoCD |
| No matching directories/files | Check path patterns match repository structure |
| Cluster selector doesn't match | Verify cluster labels: `kubectl get secret -n argocd -l argocd.argoproj.io/secret-type=cluster -o yaml` |
| SCM token invalid/expired | Regenerate token and update secret |
| Pull Request labels don't match | Add required labels to PRs |

**Example Fix - Git Repository Access:**

```bash
# Verify repository is configured in ArgoCD
argocd repo list

# Add repository if missing
argocd repo add https://github.com/org/repo.git \
  --username <user> \
  --password <token>
```

---

### 2. Template Rendering Errors

**Symptoms:**
- ApplicationSet shows error status
- Controller logs show template parsing errors
- Applications created with incorrect names or values

**Diagnostic Steps:**

```bash
# Check controller logs for template errors
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller | grep -i "template"

# Verify template syntax by examining the ApplicationSet
kubectl get applicationset <name> -n argocd -o yaml
```

**Common Template Issues:**

| Issue | Wrong | Correct |
|-------|-------|---------|
| Missing dot in Go template | `{{ name }}` | `{{ .name }}` |
| Incorrect function syntax | `{{ .name \| lower() }}` | `{{ .name \| lower }}` |
| Missing quotes for strings | `name: {{ .name }}` | `name: '{{ .name }}'` |
| Incorrect index syntax | `{{ .path.segments.0 }}` | `{{ index .path.segments 0 }}` |

**Fix for missingkey Error:**

```yaml
# Add goTemplateOptions to catch missing keys early
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]  # Fail fast on missing keys
```

**Debug Template Output:**

```yaml
# Temporarily add debug annotation to see rendered values
template:
  metadata:
    annotations:
      debug.path: '{{ .path.path }}'
      debug.segments: '{{ .path.segments }}'
      debug.basename: '{{ .path.basename }}'
```

---

### 3. Sync Failures

**Symptoms:**
- Applications show "OutOfSync" or "SyncFailed" status
- Resources not deploying to cluster

**Diagnostic Steps:**

```bash
# Check application sync status
argocd app get <app-name> --show-operation

# View sync details
kubectl describe application <app-name> -n argocd

# Check for resource conflicts
argocd app diff <app-name>
```

**Common Causes & Solutions:**

| Cause | Solution |
|-------|----------|
| Namespace doesn't exist | Add `CreateNamespace=true` to syncOptions |
| Resource already exists (not managed by ArgoCD) | Use `ServerSideApply=true` or manually delete resource |
| CRD not installed | Deploy CRDs first with sync wave `-1` |
| Resource validation failed | Check resource YAML for errors |
| RBAC permissions | Verify ArgoCD service account permissions |

**Fix - Sync Options:**

```yaml
syncPolicy:
  automated:
    prune: true
    selfHeal: true
  syncOptions:
    - CreateNamespace=true
    - ServerSideApply=true
    - PruneLast=true
    - RespectIgnoreDifferences=true
```

---

### 4. Application Deletion Issues

**Symptoms:**
- Applications not deleted when removed from generator output
- Orphaned Applications remain after ApplicationSet deletion
- Resources remain in cluster after Application deletion

**Diagnostic Steps:**

```bash
# Check if pruning is enabled
kubectl get applicationset <name> -n argocd -o yaml | grep -A 5 syncPolicy

# Check Application finalizers
kubectl get application <app-name> -n argocd -o yaml | grep finalizers
```

**Solutions:**

```yaml
# Enable automated pruning
syncPolicy:
  automated:
    prune: true  # Delete Applications when removed from generator
    selfHeal: true

# Add finalizer for resource cleanup
template:
  metadata:
    finalizers:
      - resources-finalizer.argocd.argoproj.io
```

**Manual Cleanup (Emergency):**

```bash
# Remove finalizer if Application is stuck deleting
kubectl patch application <app-name> -n argocd \
  --type json \
  -p '[{"op": "remove", "path": "/metadata/finalizers"}]'
```

---

### 5. Matrix/Merge Generator Issues

**Symptoms:**
- Fewer Applications than expected
- Wrong combinations generated
- Merge not working as expected

**Diagnostic Steps:**

```bash
# Check ApplicationSet status for generated parameters
kubectl get applicationset <name> -n argocd -o yaml | grep -A 100 status
```

**Common Matrix Issues:**

| Issue | Cause | Solution |
|-------|-------|----------|
| No Applications generated | One generator returns empty | Ensure all generators return results |
| Missing combinations | Nested generator syntax error | Use proper YAML indentation |
| Duplicate Applications | Same name generated | Include unique identifiers in name template |

**Correct Matrix Syntax:**

```yaml
generators:
  - matrix:
      generators:
        - clusters:       # First generator
            selector:
              matchLabels:
                env: production
        - list:           # Second generator
            elements:
              - app: frontend
              - app: backend
```

**Merge with Correct mergeKeys:**

```yaml
generators:
  - merge:
      mergeKeys:
        - name           # Key to match and merge on
      generators:
        - clusters: {}   # Base (has .name from cluster)
        - list:          # Override (must have matching .name)
            elements:
              - name: cluster-1
                replicas: "5"
```

---

### 6. Pull Request Generator Issues

**Symptoms:**
- Preview environments not created for PRs
- PRs not detected by generator
- Preview environments not cleaned up

**Diagnostic Steps:**

```bash
# Check controller logs for PR discovery
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller | grep -i "pull"

# Verify token secret exists
kubectl get secret github-token -n argocd

# Check requeue interval
kubectl get applicationset <name> -n argocd -o yaml | grep requeueAfterSeconds
```

**Common Causes & Solutions:**

| Cause | Solution |
|-------|----------|
| Token doesn't have required permissions | Ensure `repo` scope for private repos |
| PRs missing required labels | Add labels specified in ApplicationSet |
| Token secret in wrong namespace | Create secret in `argocd` namespace |
| API rate limiting | Increase `requeueAfterSeconds` |

**Verify Token Permissions:**

```bash
# GitHub - test token
curl -H "Authorization: token <your-token>" \
  https://api.github.com/repos/<owner>/<repo>/pulls

# GitLab - test token
curl -H "PRIVATE-TOKEN: <your-token>" \
  https://gitlab.com/api/v4/projects/<project-id>/merge_requests
```

**Token Secret Format:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: github-token
  namespace: argocd  # Must be in argocd namespace
type: Opaque
stringData:
  token: ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

### 7. Cluster Generator Issues

**Symptoms:**
- Applications not deployed to specific clusters
- Cluster not discovered by generator

**Diagnostic Steps:**

```bash
# List all registered clusters
argocd cluster list

# Check cluster secrets with labels
kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=cluster -o yaml

# Verify cluster labels
kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=cluster \
  -o jsonpath='{range .items[*]}{.metadata.name}: {.metadata.labels}{"\n"}{end}'
```

**Common Issues:**

| Issue | Solution |
|-------|----------|
| Cluster not in ArgoCD | Register cluster with `argocd cluster add` |
| Missing labels | Add labels to cluster secret |
| Wrong selector | Verify matchLabels/matchExpressions syntax |

**Add Labels to Cluster:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: cluster-prod-east
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
    environment: production      # Custom label
    region: us-east              # Custom label
type: Opaque
stringData:
  name: prod-east
  server: https://prod-east.example.com:6443
  config: |
    {
      "bearerToken": "...",
      "tlsClientConfig": {
        "insecure": false,
        "caData": "..."
      }
    }
```

---

### 8. Git Generator Path Issues

**Symptoms:**
- No Applications generated despite directories existing
- Wrong directories matched

**Diagnostic Steps:**

```bash
# Clone repo and verify paths exist
git clone <repo-url>
find . -type d -name "*" | head -50

# Test glob pattern locally
ls -la apps/*/
```

**Common Path Issues:**

| Pattern | Matches | Does NOT Match |
|---------|---------|----------------|
| `apps/*` | `apps/frontend/` | `apps/frontend/overlays/dev/` |
| `apps/*/overlays/*` | `apps/frontend/overlays/dev/` | `apps/frontend/` |
| `apps/**` | All nested directories | - |
| `apps/*/config.yaml` (files) | `apps/frontend/config.yaml` | `apps/config.yaml` |

**Debug with Path Segments:**

```yaml
# Understanding path.segments for apps/frontend/overlays/dev
# segments[0] = apps
# segments[1] = frontend
# segments[2] = overlays
# segments[3] = dev

template:
  metadata:
    name: '{{ index .path.segments 3 }}-{{ index .path.segments 1 }}'
    # Results in: dev-frontend
```

**Exclude Specific Directories:**

```yaml
generators:
  - git:
      repoURL: https://github.com/org/repo.git
      revision: HEAD
      directories:
        - path: apps/*
        - path: apps/deprecated-*
          exclude: true
        - path: apps/test-*
          exclude: true
```

---

### 9. Performance Issues

**Symptoms:**
- ApplicationSet controller high CPU/memory
- Slow Application generation
- Controller restarts

**Diagnostic Steps:**

```bash
# Check controller resource usage
kubectl top pod -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller

# Check number of generated Applications
kubectl get applications -n argocd | wc -l

# Check controller logs for performance issues
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller | tail -100
```

**Optimization Strategies:**

| Issue | Solution |
|-------|----------|
| Too many Applications | Use more specific selectors/paths |
| Frequent reconciliation | Increase `requeueAfterSeconds` |
| Large Git repositories | Use shallow clones or specific paths |
| Many clusters | Use cluster selectors to limit scope |

**Controller Resource Tuning:**

```yaml
# In argocd-cmd-params-cm ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
data:
  # Increase concurrent reconciliations
  applicationsetcontroller.concurrent.reconciliations.max: "10"
  # Adjust requeue interval
  applicationsetcontroller.requeue.interval: "180"
```

---

### 10. RBAC and Permission Issues

**Symptoms:**
- "permission denied" errors
- Applications sync but resources not created
- Unable to create Applications in certain projects

**Diagnostic Steps:**

```bash
# Check ArgoCD RBAC
kubectl get configmap argocd-rbac-cm -n argocd -o yaml

# Check AppProject restrictions
kubectl get appproject <project-name> -n argocd -o yaml

# Verify service account permissions
kubectl auth can-i create deployments --as=system:serviceaccount:argocd:argocd-application-controller -n <namespace>
```

**Common RBAC Issues:**

| Issue | Solution |
|-------|----------|
| AppProject destination restrictions | Add destination to project whitelist |
| Source repository not allowed | Add repository to project sourceRepos |
| Cluster resources not permitted | Update clusterResourceWhitelist |

**Fix AppProject Permissions:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: my-project
  namespace: argocd
spec:
  description: My Application Project
  sourceRepos:
    - https://github.com/org/*       # Allow all repos in org
  destinations:
    - namespace: '*'                  # Allow all namespaces
      server: https://kubernetes.default.svc
    - namespace: 'preview-*'          # Allow preview namespaces
      server: '*'
  clusterResourceWhitelist:
    - group: ''
      kind: Namespace
    - group: 'rbac.authorization.k8s.io'
      kind: ClusterRole
    - group: 'rbac.authorization.k8s.io'
      kind: ClusterRoleBinding
```

---

## Debug Mode

Enable debug logging for deeper troubleshooting:

```bash
# Enable debug logs for ApplicationSet controller
kubectl set env deployment/argocd-applicationset-controller \
  -n argocd \
  ARGOCD_APPLICATIONSET_CONTROLLER_LOGLEVEL=debug

# Watch logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller -f
```

---

## Health Check Script

```bash
#!/bin/bash
# applicationset-health-check.sh

echo "=== ArgoCD ApplicationSet Health Check ==="
echo ""

echo "1. ApplicationSet Controller Status:"
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller
echo ""

echo "2. ApplicationSets:"
kubectl get applicationsets -n argocd
echo ""

echo "3. Generated Applications Summary:"
kubectl get applications -n argocd --no-headers | awk '{print $3}' | sort | uniq -c
echo ""

echo "4. Recent Controller Errors:"
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller --tail=50 | grep -i error | tail -10
echo ""

echo "5. Applications Not Synced:"
kubectl get applications -n argocd | grep -v "Synced" | grep -v "NAME"
echo ""

echo "=== End Health Check ==="
```

---

## Additional Resources

- [ArgoCD ApplicationSet Documentation](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/)
- [ArgoCD Troubleshooting Guide](https://argo-cd.readthedocs.io/en/stable/operator-manual/troubleshooting/)
- [GitHub Issues - ApplicationSet](https://github.com/argoproj/argo-cd/issues?q=is%3Aissue+applicationset)
