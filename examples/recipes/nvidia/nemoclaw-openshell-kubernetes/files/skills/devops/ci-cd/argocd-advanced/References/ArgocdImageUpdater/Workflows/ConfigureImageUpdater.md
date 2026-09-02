# ConfigureImageUpdater Workflow

Configure ArgoCD Image Updater via Helm chart in a multi-source ApplicationSet pattern.

## Prerequisites

- ArgoCD Image Updater Helm chart v1.1.1+ from `argo-helm`
- Multi-source ApplicationSet with `$values` reference
- Registry credentials secret in `argocd` namespace

## Step 1: ApplicationSet Structure

The ApplicationSet combines public Helm chart + environment-specific values:

```yaml
spec:
  sources:
    - chart: argocd-image-updater
      repoURL: https://argoproj.github.io/argo-helm
      targetRevision: 1.1.1
      helm:
        releaseName: argocd-image-updater
        valueFiles:
          - $values/argo-cd-helm-values/kube-addons/argocd-image-updater/{{cluster}}/values.yaml
    - repoURL: <your-values-repo>
      targetRevision: "{{branch}}"
      ref: values
```

## Step 2: Helm Values Configuration

### Core Configuration

```yaml
replicaCount: 1

updateStrategy:
  type: Recreate

config:
  log.level: debug  # Use flat dotted keys, NOT nested maps

  registries:
    - name: Azure Container Registry
      api_url: https://<registry>.azurecr.io
      ping: yes
      prefix: <registry>.azurecr.io
      credentials: pullsecret:argocd/<secret-name>
```

### Metrics (HTTP, not HTTPS)

```yaml
extraArgs:
  - --metrics-secure=false

containerPorts:
  metrics: 8080

metrics:
  enabled: true
  service:
    servicePort: 8080
  serviceMonitor:
    enabled: true
    namespace: monitoring
    additionalLabels:
      release: robusta
```

### Sync Policy

```yaml
syncPolicy:
  automated:
    prune: true
    selfHeal: true
  syncOptions:
    - ServerSideApply=true
    - RespectIgnoreDifferences=true
```

## Step 3: Validate

```bash
yamllint <values-file>
pre-commit run --all-files
```

## Common Pitfalls

1. **Nested config keys**: Chart v1.1.1 expects `config.log.level`, NOT `config: { logLevel: }`. Nested maps render as Go map literals in the ConfigMap, breaking lookups.
2. **HTTPS metrics**: Default chart serves metrics on port 8443 with TLS. ServiceMonitor scraping HTTP will get TLS handshake errors. Use `--metrics-secure=false`.
3. **Broad ignoreDifferences**: Never ignore `/data` on the entire ConfigMap — it masks real drift.
