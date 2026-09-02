# ArgoCD Cluster Bootstrapping - Summary

## Purpose

This skill provides a complete framework for bootstrapping new Kubernetes clusters into a multi-repository GitOps environment managed by ArgoCD. It covers the entire lifecycle from cluster provisioning through production deployment.

## Scope

### In Scope
- AKS cluster registration with ArgoCD
- Cluster secret creation with proper labels
- ArgoCD Project setup for RBAC
- ApplicationSet configuration for new clusters
- Multi-source Helm value management
- Environment-specific configurations (dev/hlg/prd)
- Troubleshooting connectivity and sync issues

### Out of Scope
- Underlying Azure infrastructure provisioning (see Terraform modules)
- ArgoCD server installation (assumes existing hub)
- Application code deployment (handled by separate ApplicationSets)

## Architecture Pattern

This implementation uses a **multi-repository GitOps pattern**:

```
┌──────────────────────┐     ┌──────────────────────┐
│   infra-team/        │     │ argo-cd-helm-values/ │
│   (Infrastructure)   │     │ (Environment Values) │
│                      │     │                      │
│ - ApplicationSets    │     │ - Per-cluster values │
│ - Cluster secrets    │     │ - Sensitive configs  │
│ - Project definitions│     │ - Feature flags      │
│ - Base Helm values   │     │                      │
└──────────┬───────────┘     └──────────┬───────────┘
           │                            │
           └──────────┬─────────────────┘
                      ▼
              ┌───────────────┐
              │   ArgoCD      │
              │ Multi-Source  │
              │  Application  │
              └───────────────┘
```

## Key Statistics

| Metric | Value |
|--------|-------|
| Clusters Managed | 9 (dev, hlg, prd, hub variants) |
| ApplicationSets | 40+ definitions |
| Components | 28+ Helm charts |
| Projects | 10+ business units |
| Scripts | 100+ operational tools |

## Bootstrap Timeline

| Phase | Duration | Description |
|-------|----------|-------------|
| Pre-flight | 5 min | Verify access and prerequisites |
| Registration | 10 min | Add cluster to ArgoCD |
| Configuration | 15 min | Create secrets and projects |
| Validation | 10 min | Verify sync and connectivity |
| **Total** | **~40 min** | End-to-end bootstrap |

## Success Criteria

A cluster is fully bootstrapped when:
- [ ] Cluster appears in ArgoCD UI as "Connected"
- [ ] Cluster secret exists with correct labels
- [ ] ArgoCD Project grants appropriate permissions
- [ ] At least one ApplicationSet targets the cluster
- [ ] Test application syncs successfully
- [ ] Monitoring and logging are operational

## Related Skills

- `managing-infra-skill` - Kubernetes infrastructure patterns
- `kargo-skill` - Progressive delivery pipelines
- `external-dns-skill` - DNS management for new clusters
- `grafana-skill` - Monitoring setup for new clusters
