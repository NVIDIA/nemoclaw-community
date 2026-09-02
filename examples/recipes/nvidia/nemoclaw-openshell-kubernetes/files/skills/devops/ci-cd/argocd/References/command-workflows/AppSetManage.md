# AppSetManage Workflow

Manage ArgoCD ApplicationSets - create, list, generate, and delete.

## Quick Commands

| Action | Command |
|--------|---------|
| List appsets | `argocd appset list` |
| Get appset | `argocd appset get <name>` |
| Create appset | `argocd appset create -f <file>` |
| Delete appset | `argocd appset delete <name>` |
| Generate apps | `argocd appset generate <file>` |

## List ApplicationSets

```bash
# List all ApplicationSets
argocd appset list

# List with specific output
argocd appset list -o wide
argocd appset list -o json
argocd appset list -o yaml

# Filter by project
argocd appset list -p default

# Filter by label
argocd appset list -l team=platform
```

## Get ApplicationSet Details

```bash
# Get appset details
argocd appset get <appset-name>

# Get as JSON
argocd appset get <appset-name> -o json

# Get as YAML
argocd appset get <appset-name> -o yaml
```

## Create ApplicationSet

### From File

```bash
# Create from YAML file
argocd appset create -f applicationset.yaml

# Create with upsert (update if exists)
argocd appset create -f applicationset.yaml --upsert

# Dry run (preview)
argocd appset create -f applicationset.yaml --dry-run
```

### Multi-Source ApplicationSet (example-app-hub Pattern)

```yaml
# applicationset-example.yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: monitoring-stack
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  generators:
    - matrix:
        generators:
          - clusters:
              selector:
                matchLabels:
                  environment: production
          - list:
              elements:
                - app: grafana
                  chart: grafana
                  repoURL: https://grafana.github.io/helm-charts
                  targetRevision: 8.0.0
                  namespace: monitoring
  template:
    metadata:
      name: '{{.app}}-{{.name}}'
      namespace: argocd
    spec:
      project: default
      sources:
        # Helm chart from public repo
        - repoURL: '{{.repoURL}}'
          chart: '{{.chart}}'
          targetRevision: '{{.targetRevision}}'
          helm:
            valueFiles:
              - $values/infra-team/argocd-helm-values/{{.app}}/base-values.yaml
              - $values/argo-cd-helm-values/{{.name}}/{{.app}}/values.yaml
        # Values from private repo
        - repoURL: git@ssh.dev.azure.com:v3/your-org/rg-example-web/Repos
          targetRevision: main
          ref: values
      destination:
        server: '{{.server}}'
        namespace: '{{.namespace}}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

### Git Generator ApplicationSet

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: git-apps
  namespace: argocd
spec:
  generators:
    - git:
        repoURL: https://github.com/org/repo.git
        revision: HEAD
        directories:
          - path: apps/*
  template:
    metadata:
      name: '{{path.basename}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/repo.git
        targetRevision: HEAD
        path: '{{path}}'
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{path.basename}}'
```

### List Generator ApplicationSet

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: env-apps
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - cluster: dev
            url: https://dev.example.com
          - cluster: staging
            url: https://staging.example.com
          - cluster: prod
            url: https://prod.example.com
  template:
    metadata:
      name: 'myapp-{{cluster}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/repo.git
        targetRevision: HEAD
        path: 'envs/{{cluster}}'
      destination:
        server: '{{url}}'
        namespace: myapp
```

### Cluster Generator ApplicationSet

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: cluster-addons
  namespace: argocd
spec:
  generators:
    - clusters:
        selector:
          matchLabels:
            argocd.argoproj.io/secret-type: cluster
  template:
    metadata:
      name: 'addons-{{name}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/cluster-addons.git
        targetRevision: HEAD
        path: addons
      destination:
        server: '{{server}}'
        namespace: cluster-addons
```

## Generate Applications (Preview)

```bash
# Generate and preview applications
argocd appset generate applicationset.yaml

# Generate as JSON
argocd appset generate applicationset.yaml -o json

# Generate and save to file
argocd appset generate applicationset.yaml > generated-apps.yaml
```

## Delete ApplicationSet

```bash
# Delete ApplicationSet
argocd appset delete <appset-name>

# Force delete (skip confirmation)
argocd appset delete <appset-name> --yes
```

## Common Patterns

### Matrix Generator (Cluster x Apps)

```yaml
generators:
  - matrix:
      generators:
        - clusters:
            selector:
              matchLabels:
                environment: production
        - list:
            elements:
              - app: prometheus
              - app: grafana
              - app: loki
```

### Merge Generator

```yaml
generators:
  - merge:
      mergeKeys:
        - cluster
      generators:
        - clusters:
            values:
              replicas: "3"
        - list:
            elements:
              - cluster: dev
                replicas: "1"
```

### Pull Request Generator

```yaml
generators:
  - pullRequest:
      github:
        owner: org
        repo: repo
        tokenRef:
          secretName: github-token
          key: token
      filters:
        - branchMatch: "feature-.*"
```

## Troubleshooting

```bash
# Check ApplicationSet controller logs (example-app-hub cluster)
kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller -f

# Check generated applications
argocd appset generate <file> | kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config apply --dry-run=client -f -

# Validate YAML syntax
argocd appset create -f <file> --dry-run
```
