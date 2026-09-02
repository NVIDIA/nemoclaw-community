---
name: argocd-application-install
description: Create and manage ArgoCD ApplicationSets for new workloads using the ExampleApp multi-source template pattern. USE WHEN adding a new service to ArgoCD OR creating an ApplicationSet from template OR deploying a new kube-addon OR onboarding a workload to the GitOps platform OR need to know which clusters to target for a service.
---

# ArgoCD App Install

Create ArgoCD ApplicationSets for new workloads following the ExampleApp multi-repository GitOps pattern. Uses the standardized TEMPLATE.yaml with list generator, multi-source Helm configuration, and Kustomize registration.

## Customization

**Before executing, check for user customizations at:**
`~/.claude/skills/PAI/USER/SKILLCUSTOMIZATIONS/ArgocdAppInstall/`

If this directory exists, load and apply any PREFERENCES.md, configurations, or resources found there. These override default behavior. If the directory does not exist, proceed with skill defaults.

## Voice Notification

**When executing a workflow, do BOTH:**

1. **Send voice notification**:
   ```bash
   curl -s -X POST http://localhost:8888/notify \
     -H "Content-Type: application/json" \
     -d '{"message": "Running WORKFLOWNAME in ArgocdAppInstall"}' \
     > /dev/null 2>&1 &
   ```

2. **Output text notification**:
   ```
   Running the **WorkflowName** workflow in the **ArgocdAppInstall** skill to ACTION...
   ```

**Full documentation:** `~/.claude/skills/PAI/THENOTIFICATIONSYSTEM.md`

## Workflow Routing

| Workflow | Trigger | File |
|----------|---------|------|
| **CreateApplicationSet** | "add service", "new applicationset", "deploy workload", "create appset" | `Workflows/CreateApplicationSet.md` |
| **ValidateApplicationSet** | "validate appset", "check applicationset", "verify deployment" | `Workflows/ValidateApplicationSet.md` |

## Examples

**Example 1: Add a new monitoring service**
```
User: "Add grafana-oncall to the ArgoCD platform"
-> Invokes CreateApplicationSet workflow
-> Copies TEMPLATE.yaml to grafana-oncall.yaml
-> Replaces placeholders (chart, repo, namespace, component)
-> Creates values files per cluster in argo-cd-helm-values/
-> Registers in kustomization.yaml
-> Runs pre-commit validation
```

**Example 2: Validate an existing ApplicationSet**
```
User: "Validate the robusta applicationset is correct"
-> Invokes ValidateApplicationSet workflow
-> Checks YAML syntax, cluster URLs, values file existence
-> Verifies kustomization.yaml registration
-> Reports any issues found
```

**Example 3: Add service to specific clusters only**
```
User: "Deploy phpmyadmin only to dev clusters"
-> Invokes CreateApplicationSet workflow
-> Removes production/hub clusters from generator list
-> Only includes example-app-dev, loyalty-dev entries
-> Ensures spot tolerations in dev values
```

## Quick Reference

**Key Paths:**
- Template: `infra-team/applicationset/TEMPLATE.yaml`
- ApplicationSets: `infra-team/applicationset/`
- Values: `argo-cd-helm-values/kube-addons/<service>/<cluster>/values.yaml`
- Kustomization: `infra-team/applicationset/kustomization.yaml`

**Sync Wave Order:** `-10` core infra, `-5` security, `0` default, `5` apps, `10` monitoring

**Cluster Details:** cross-reference your own cluster inventory (kept outside this skill)
