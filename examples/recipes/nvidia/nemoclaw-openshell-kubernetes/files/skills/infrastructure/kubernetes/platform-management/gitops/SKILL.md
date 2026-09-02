---
name: kubernetes-platform-gitops
description: Master GitOps practices, CI/CD integration, Helm charts, Kustomize, and ArgoCD. Learn modern deployment patterns and infrastructure as code.
sasmp_version: "1.3.0"
eqhm_enabled: true
bonded_agent: 07-development-gitops
bond_type: PRIMARY_BOND
capabilities: ["ArgoCD management", "Helm charts", "Kustomize overlays", "CI/CD pipelines", "Multi-environment", "Progressive delivery", "Drift detection", "Secret management"]
input_schema:
  type: object
  properties:
    action:
      type: string
      enum: ["deploy", "sync", "rollback", "diff", "promote"]
    environment:
      type: string
      enum: ["dev", "staging", "production"]
    tool:
      type: string
      enum: ["argocd", "helm", "kustomize", "flux"]
output_schema:
  type: object
  properties:
    sync_status:
      type: string
    health_status:
      type: string
    diff:
      type: array
---

# GitOps & CI/CD

## Executive Summary
Production-grade GitOps practices covering ArgoCD, Helm, Kustomize, and CI/CD pipeline integration. This skill provides deep expertise in implementing declarative infrastructure, progressive delivery, and automated reconciliation for enterprise-scale Kubernetes deployments.

## Core Competencies

### 1. ArgoCD Application Management

**ApplicationSet for Multi-Environment**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: api-server
  namespace: argocd
spec:
  generators:
  - list:
      elements:
      - env: dev
        cluster: dev-cluster
        namespace: dev
      - env: staging
        cluster: staging-cluster
        namespace: staging
      - env: production
        cluster: prod-cluster
        namespace: production
  template:
    metadata:
      name: 'api-server-{{env}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/api-server
        targetRevision: HEAD
        path: k8s/overlays/{{env}}
      destination:
        server: '{{cluster}}'
        namespace: '{{namespace}}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
        - CreateNamespace=true
        retry:
          limit: 5
          backoff:
            duration: 5s
            maxDuration: 3m
```

**Sync Waves for Ordered Deployment**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: myapp
  annotations:
    argocd.argoproj.io/sync-wave: "0"  # Deploy first
---
# Database
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "1"
---
# API Server
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "2"
---
# Frontend
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "3"
```

### 2. Kustomize Structure

**Multi-Environment Layout**
```
├── base/
│   ├── kustomization.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   └── configmap.yaml
└── overlays/
    ├── dev/
    │   ├── kustomization.yaml
    │   └── replicas-patch.yaml
    ├── staging/
    │   ├── kustomization.yaml
    │   └── resources-patch.yaml
    └── production/
        ├── kustomization.yaml
        ├── replicas-patch.yaml
        └── hpa.yaml
```

**Production Kustomization**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: production
resources:
- ../../base
- hpa.yaml
- pdb.yaml

patches:
- path: replicas-patch.yaml
- path: resources-patch.yaml

images:
- name: api-server
  newName: myregistry.io/api-server
  newTag: v2.1.0

configMapGenerator:
- name: api-config
  behavior: merge
  literals:
  - LOG_LEVEL=info
  - ENV=production
```

### 3. Helm Chart Best Practices

**Production values.yaml**
```yaml
replicaCount: 3

image:
  repository: myregistry.io/api-server
  tag: "v2.1.0"
  pullPolicy: IfNotPresent

resources:
  requests:
    cpu: 250m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 1Gi

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70

podDisruptionBudget:
  enabled: true
  minAvailable: 2

serviceMonitor:
  enabled: true
  interval: 15s

ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
  - host: api.example.com
    paths:
    - path: /
      pathType: Prefix
  tls:
  - secretName: api-tls
    hosts:
    - api.example.com
```

### 4. CI/CD Pipeline

**GitHub Actions**
```yaml
name: kubernetes-platform-gitops

on:
  push:
    branches: [main]
    tags: ['v*']

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Build and Push
      uses: docker/build-push-action@v5
      with:
        push: true
        tags: myregistry.io/api-server:${{ github.sha }}

    - name: Update Kustomize
      run: |
        cd k8s/overlays/staging
        kustomize edit set image api-server=myregistry.io/api-server:${{ github.sha }}

    - name: Commit and Push
      run: |
        git config user.name "github-actions"
        git config user.email "actions@github.com"
        git add .
        git commit -m "Update image to ${{ github.sha }}"
        git push

  promote:
    if: startsWith(github.ref, 'refs/tags/')
    needs: build
    runs-on: ubuntu-latest
    steps:
    - name: Promote to Production
      run: |
        cd k8s/overlays/production
        kustomize edit set image api-server=myregistry.io/api-server:${{ github.ref_name }}
```

### 5. Secret Management with SOPS

```yaml
# .sops.yaml
creation_rules:
- path_regex: .*secrets.*\.yaml$
  kms: arn:aws:kms:us-east-1:123456789:key/xxx
  encrypted_regex: ^(data|stringData)$
```

```bash
# Encrypt secrets
sops -e secrets.yaml > secrets.enc.yaml

# ArgoCD SOPS plugin
apiVersion: argoproj.io/v1alpha1
kind: Application
spec:
  source:
    plugin:
      name: argocd-vault-plugin-kustomize
```

## Integration Patterns

### Uses skill: **docker-containers**
- Image building
- Registry management

### Coordinates with skill: **deployments**
- Rollout strategies
- Canary deployments

### Works with skill: **monitoring**
- Deployment metrics
- Rollout alerts

## Troubleshooting Guide

### Decision Tree: Sync Issues

```
ArgoCD Sync Failed?
│
├── OutOfSync
│   ├── Check: argocd app diff
│   ├── Manual changes in cluster
│   └── Enable selfHeal
│
├── SyncError
│   ├── Check: kubectl events
│   ├── Resource validation
│   └── Check RBAC permissions
│
└── Degraded health
    ├── Check pod status
    ├── Verify probes
    └── Check resource limits
```

### Debug Commands

```bash
# ArgoCD CLI
argocd app list
argocd app sync myapp
argocd app diff myapp
argocd app logs myapp

# Helm debugging
helm template . --debug
helm get values myapp -n production
helm history myapp -n production

# Kustomize
kustomize build overlays/production
kubectl diff -k overlays/production
```

## Common Challenges & Solutions

| Challenge | Solution |
|-----------|----------|
| Drift detection | Enable selfHeal |
| Secret management | SOPS, Sealed Secrets |
| Multi-cluster | ApplicationSets |
| Slow syncs | Reduce refresh interval |

## Success Criteria

| Metric | Target |
|--------|--------|
| Deployment frequency | Multiple per day |
| Lead time | <1 hour |
| Change failure | <5% |
| MTTR | <15 minutes |

## Resources
- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [Helm Documentation](https://helm.sh/docs/)
- [Kustomize Documentation](https://kustomize.io/)
