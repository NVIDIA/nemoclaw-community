---
name: argocd-advanced
description: Advanced ArgoCD operations beyond the core CLI/API — multi-cluster ApplicationSet generators, automated image updates, new-cluster bootstrapping, and workload onboarding via templated ApplicationSets. USE WHEN working with ApplicationSet CRDs (list, cluster, git, matrix, merge, SCM, pull request, plugin generators), configuring ArgoCD Image Updater (semver/digest/newest-build update strategies + git write-back), bootstrapping a new Kubernetes cluster into a multi-repo GitOps setup, registering clusters with proper labels for ApplicationSet targeting, onboarding a new workload via the standard ApplicationSet template, or troubleshooting any of these. For routine app sync/status/diff work use the core `argocd` skill instead.
---

# ArgoCD Advanced

Routing entrypoint for advanced/automation-oriented ArgoCD operations. Each sub-area has its own deep reference, preserved verbatim from the pre-consolidation skills, under `References/`.

## Scope routing

| If you need to… | Read |
|---|---|
| Implement multi-cluster app propagation with ApplicationSet generators (list / cluster / git / matrix / merge / SCM / pull-request / plugin) | `References/applicationset.md` plus `References/applicationset/` for deep-dive reference docs |
| Automate container image updates for ArgoCD-managed workloads (update strategies, ImageUpdater CRD, git write-back) | `References/image-updater.md` + `References/image-updater/` + `References/ArgocdImageUpdater/` + `Samples/image-updater/` |
| Bootstrap a new Kubernetes cluster into the multi-repo GitOps environment | `References/cluster-bootstrapping.md` + `References/cluster-bootstrapping/` + `References/ArgocdClusterBootstrapping/` |
| Onboard a new workload via the standardized ApplicationSet template | `References/application-install.md` + `Workflows/application-install/` + `Tools/application-install/` |

## Decision tree

```
Need new cluster registered with ArgoCD?           -> cluster-bootstrapping
Need new service deployed to existing clusters?    -> application-install
Need to fan one app definition across N clusters?  -> applicationset
Need images to roll forward automatically?         -> image-updater
```

## Gotchas

- **ApplicationSet generators are ordered.** With matrix/merge generators, the parent generator's result is the input to the child — get the order wrong and you get an empty parameter set with no error.
- **Image Updater + git write-back requires a write credential.** A read-only repo cred will silently leave images stuck on the original version. Check Image Updater pod logs for `permission denied` on push.
- **Bootstrap cluster secrets must carry the labels your ApplicationSet generators select on.** A cluster registered without the expected label key/value is invisible to existing ApplicationSets — and there is no error, just zero apps.
- **`application-install` ships a your organization/ExampleApp-specific template.** The Workflows assume the multi-repo layout. If you're not in that environment, treat it as a reference pattern, not a runnable recipe.
- **CRD versions matter.** ApplicationSet ships with ArgoCD 2.3+; certain generators (SCM, pull request) need 2.5+. Read `References/applicationset.md` Version Compatibility before adopting.
