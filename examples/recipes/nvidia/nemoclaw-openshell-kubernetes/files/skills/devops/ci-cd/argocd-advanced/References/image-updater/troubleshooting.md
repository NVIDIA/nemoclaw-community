# ArgoCD Image Updater - Troubleshooting Guide

## Diagnostic Commands

### Check Pod Status

```bash
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-image-updater
kubectl describe pod -n argocd -l app.kubernetes.io/name=argocd-image-updater
```

### View Logs

```bash
# All logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-image-updater -f

# With increased verbosity
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-image-updater -f | grep -E "(error|warn|ERR|WARN)"

# Last 100 lines
kubectl logs -n argocd deployment/argocd-image-updater --tail=100
```

### Check ImageUpdater CRs

```bash
kubectl get imageupdaters -n argocd
kubectl describe imageupdater <name> -n argocd
kubectl get imageupdater <name> -n argocd -o yaml
```

### Check Application Annotations

```bash
kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.annotations}{"\n"}{end}'
```

## Common Issues

### Issue: Images Not Updating

**Symptoms:**

- No updates appearing in logs
- Application image stays the same

**Diagnosis:**

```bash
# Check if application is being processed
kubectl logs -n argocd deployment/argocd-image-updater | grep "Processing application"

# Verify application has correct annotations/is referenced by ImageUpdater
kubectl get application <app-name> -n argocd -o yaml | grep -A20 "annotations"
```

**Common Causes & Solutions:**

1. **Application not matched by ImageUpdater**

   ```yaml
   # Verify namePattern matches
   applicationRefs:
     - namePattern: "my-app"  # Must match application name
   ```

2. **Image name mismatch**

   ```yaml
   # Image in application must match imageName in ImageUpdater
   images:
     - alias: "app"
       imageName: "myregistry/myapp"  # Must match exactly
   ```

3. **No new versions available**

   ```bash
   # Check available tags
   kubectl exec -n argocd deployment/argocd-image-updater -- \
     argocd-image-updater test myregistry/myapp --registries-conf-path /app/config/registries.conf
   ```

### Issue: Registry Authentication Errors

**Symptoms:**

- `unauthorized` or `authentication required` in logs
- `401` or `403` errors

**Diagnosis:**

```bash
# Check if secret exists
kubectl get secret <secret-name> -n argocd

# Verify secret content
kubectl get secret <secret-name> -n argocd -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d
```

**Solutions:**

1. **Incorrect credentials**

   ```bash
   # Test credentials manually
   docker login myregistry.example.com -u username -p password
   ```

2. **Wrong secret type**

   ```yaml
   # Must be kubernetes.io/dockerconfigjson
   type: kubernetes.io/dockerconfigjson
   ```

3. **Secret not referenced correctly**

   ```yaml
   credentials: pullsecret:argocd/<secret-name>
   ```

### Issue: Git Write-Back Failing

**Symptoms:**

- Updates detected but not committed
- Git-related errors in logs

**Diagnosis:**

```bash
kubectl logs -n argocd deployment/argocd-image-updater | grep -i git
```

**Common Causes & Solutions:**

1. **SSH key issues**

   ```bash
   # Test SSH connection
   kubectl exec -n argocd deployment/argocd-image-updater -- \
     ssh -T git@github.com
   ```

2. **Branch doesn't exist**

   ```bash
   # Verify branch exists
   git ls-remote --heads origin <branch-name>
   ```

3. **Permission denied**
   - Verify deploy key has write access
   - Check if branch is protected
   - Ensure token has `repo` scope

4. **Merge conflicts**
   - Resolve conflicts manually in Git
   - Image Updater will retry on next cycle

### Issue: Wrong Version Selected

**Symptoms:**

- Unexpected version being deployed
- Older version selected instead of newer

**Diagnosis:**

```bash
# List all tags being considered
kubectl exec -n argocd deployment/argocd-image-updater -- \
  argocd-image-updater test myregistry/myapp --semver-constraint "1.x"
```

**Solutions:**

1. **Wrong update strategy**

   ```yaml
   # Verify correct strategy for your tagging scheme
   commonUpdateSettings:
     updateStrategy: "semver"  # vs newest-build, digest, alphabetical
   ```

2. **Tag filtering too restrictive/permissive**

   ```yaml
   tagMatch:
     pattern: "^v[0-9]+\\.[0-9]+\\.[0-9]+$"
   ```

3. **Semver constraint mismatch**

   ```yaml
   imageName: "myregistry/app:1.x"  # Constraint in tag
   ```

### Issue: Argo CD Connection Errors

**Symptoms:**

- `connection refused` or `timeout` errors
- Unable to update applications

**Diagnosis:**

```bash
# Check Argo CD server is accessible
kubectl exec -n argocd deployment/argocd-image-updater -- \
  wget -qO- https://argocd-server.argocd.svc.cluster.local/api/version
```

**Solutions:**

1. **Wrong server address**

   ```yaml
   # In ConfigMap or environment
   ARGOCD_SERVER: argocd-server.argocd.svc.cluster.local:443
   ```

2. **TLS issues**

   ```yaml
   ARGOCD_INSECURE: "true"  # Skip TLS verification (not for production)
   ```

3. **API token expired/invalid**
   - Generate new token in Argo CD
   - Update secret with new token

### Issue: Pod CrashLoopBackOff

**Diagnosis:**

```bash
kubectl describe pod -n argocd -l app.kubernetes.io/name=argocd-image-updater
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-image-updater --previous
```

**Common Causes:**

1. **Missing ConfigMap**

   ```bash
   kubectl get configmap argocd-image-updater-config -n argocd
   ```

2. **Invalid configuration**
   - Check YAML syntax in ConfigMap
   - Validate registries.conf format

3. **RBAC issues**

   ```bash
   kubectl auth can-i get applications -n argocd --as=system:serviceaccount:argocd:argocd-image-updater
   ```

## Debug Mode

Enable debug logging:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-image-updater-config
  namespace: argocd
data:
  log.level: debug
```

Or via environment variable:

```yaml
env:
  - name: IMAGE_UPDATER_LOGLEVEL
    value: debug
```

## Test Commands

### Test Image Discovery

```bash
kubectl exec -n argocd deployment/argocd-image-updater -- \
  argocd-image-updater test myregistry/myapp \
    --update-strategy semver \
    --semver-constraint "1.x" \
    --registries-conf-path /app/config/registries.conf
```

### Force Update Check

```bash
kubectl rollout restart deployment argocd-image-updater -n argocd
```

### Manual Application Update

```bash
# Get current image
kubectl get application <app-name> -n argocd -o jsonpath='{.spec.source.helm.parameters}' | jq .

# Check Image Updater status
kubectl logs -n argocd deployment/argocd-image-updater | grep "<app-name>"
```

## Performance Issues

### High Memory Usage

```yaml
# Limit concurrent checks
spec:
  concurrency: 2  # Default is 10
```

### Slow Registry Responses

```yaml
# Increase timeout
spec:
  registryTimeout: 60s  # Default is 30s
```

### Too Frequent Updates

```yaml
# Adjust check interval
spec:
  interval: 5m  # Default is 2m
```

## Getting Help

1. Check [official documentation](https://argocd-image-updater.readthedocs.io/)
2. Search [GitHub issues](https://github.com/argoproj-labs/argocd-image-updater/issues)
3. Ask in [Argo CD Slack](https://argoproj.github.io/community/join-slack) #argo-cd-image-updater channel
