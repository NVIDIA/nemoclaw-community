---
name: argocd-advanced-argocd-image-updater
description: Manage ArgoCD Image Updater configuration, drift resolution, and ImageUpdater CRDs. USE WHEN argocd image updater, image update drift, ImageUpdater CRD, extraObjects helm, environment-scoped image updates, argocd-image-updater troubleshooting.
---

# ArgoCD Image Updater

Operational skill for configuring and troubleshooting ArgoCD Image Updater in multi-cluster GitOps environments. Covers Helm chart configuration, ImageUpdater CRD management, drift resolution, and environment-scoped update patterns.

## Workflow Routing

| Workflow | Trigger | File |
|----------|---------|------|
| **ResolveDrift** | "fix drift", "resolve drift", "orphaned resources" | `Workflows/ResolveDrift.md` |
| **ConfigureImageUpdater** | "configure image updater", "setup image updates" | `Workflows/ConfigureImageUpdater.md` |
| **CreateImageUpdaterCrds** | "create ImageUpdater CRD", "scope image updates" | `Workflows/CreateImageUpdaterCrds.md` |

## Quick Reference

- **Chart**: `argocd-image-updater` v1.1.1 (app v1.1.0) from `argo-helm`
- **CRD API**: `argocd-image-updater.argoproj.io/v1alpha1` kind `ImageUpdater`
- **Custom resources via Helm**: Use `extraObjects` values key
- **Config format**: Flat dotted keys (e.g., `config.log.level`), NOT nested maps
- **Metrics**: Use `--metrics-secure=false` + port 8080 for HTTP Prometheus scraping

## Key Patterns

- **Environment scoping**: Create per-environment `ImageUpdater` CRs with `namePattern` (e.g., `dev-*`, `hlg-*`, `prd-*`)
- **Drift resolution**: Bring manually-applied resources under GitOps via `extraObjects` in Helm values
- **ServerSideApply**: Enables ArgoCD to adopt existing resources without conflicts
- **Registry auth**: `pullsecret:namespace/secret-name` format for ACR credentials

**Full documentation:** See context files in this skill directory.
