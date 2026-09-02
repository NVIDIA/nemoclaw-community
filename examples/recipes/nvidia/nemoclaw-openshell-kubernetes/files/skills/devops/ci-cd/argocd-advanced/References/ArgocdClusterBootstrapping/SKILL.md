---
name: argocd-advanced-argocd-cluster-bootstrapping
description: Complete ArgoCD cluster bootstrapping skill for diagnosing sync failures, creating root Applications (app-of-apps), curating ApplicationSets via Kustomize, and resolving missing CRD dependencies. USE WHEN argocd bootstrap OR app-of-apps pattern OR root application OR applicationset gitops management OR argocd sync failed missing CRD OR kustomize applicationset curation OR argocd cluster onboarding.
---

# ArgoCD Cluster Bootstrapping

Operational skill for bootstrapping ArgoCD clusters using the app-of-apps pattern with Kustomize-curated ApplicationSets. Covers diagnosing sync failures from missing CRDs, creating root Applications for GitOps lifecycle management, and onboarding new clusters to existing ApplicationSet generators.

## Workflow Routing

| Workflow | Trigger | File |
|----------|---------|------|
| **DiagnoseSyncFailure** | "sync failed", "missing CRD", "argocd error", "OutOfSync" | `Workflows/DiagnoseSyncFailure.md` |
| **CreateRootApplication** | "root application", "app-of-apps", "bootstrap argocd", "manage applicationsets" | `Workflows/CreateRootApplication.md` |
| **OnboardCluster** | "add cluster", "onboard cluster", "new environment" | `Workflows/OnboardCluster.md` |

## Examples

**Example 1: Diagnose a sync failure caused by missing CRD**
```
User: "example-app-hub-adp-agent is SyncFailed with missing AzureKeyVaultSecret CRD"
-> Invokes DiagnoseSyncFailure workflow
-> Traces dependency chain: adp-agent needs akv2k8s CRDs
-> Checks if akv2k8s ApplicationSet exists on cluster
-> Identifies root cause: ApplicationSet never deployed
-> Recommends fix via root Application or manual apply
```

**Example 2: Create a root Application for GitOps ApplicationSet management**
```
User: "Create a root Application to manage all ApplicationSets via GitOps"
-> Invokes CreateRootApplication workflow
-> Audits applicationset directory for active vs inactive files
-> Creates kustomization.yaml with curated list
-> Creates root-applicationsets.yaml Application
-> Provides bootstrap instructions for ArgoCD UI
```

**Example 3: Add a new cluster to existing ApplicationSets**
```
User: "Onboard example-app-prd cluster to the otel ApplicationSet"
-> Invokes OnboardCluster workflow
-> Reads existing ApplicationSet generator list
-> Adds new cluster element with correct URL, project, branch
-> Creates values file in argo-cd-helm-values repo
-> Validates with kustomize build
```

## Key Patterns

- **App-of-Apps via Kustomize**: Root Application watches `infra-team/applicationset/` with `kustomization.yaml` for explicit curation
- **Multi-source Helm**: ApplicationSets combine chart repo + Git values repo using `$values` ref
- **Sync waves**: Dependencies deploy first (e.g., akv2k8s at wave `-5`, consumers at wave `+5`)
- **ServerSideApply**: Prevents adoption conflicts when bringing existing resources under GitOps
- **Bootstrap chicken-and-egg**: Root Application must be applied once via ArgoCD UI, then self-manages
- **Pure GitOps**: No `kubectl apply/patch/edit/delete` — all changes via Git commits

## Architecture Reference

```
root-applicationsets (Application)
  └── watches: infra-team/applicationset/ (Kustomize)
       ├── akv2k8s.yaml (ApplicationSet)
       ├── adp-agent.yaml (ApplicationSet)
       ├── otel.yaml (ApplicationSet)
       └── ... (curated list in kustomization.yaml)
```

## Quick Reference

- **Root Application path**: `infra-team/bootstrap/root-applicationsets.yaml`
- **ApplicationSet directory**: `infra-team/applicationset/`
- **Kustomization file**: `infra-team/applicationset/kustomization.yaml`
- **Values repo**: `argo-cd-helm-values/kube-addons/{addon}/{cluster}/values.yaml`
- **Git repo URL**: `https://your-org@dev.azure.com/your-org/devops-team/_git/argocd`

**Full documentation:** See workflow files in `Workflows/` directory.
