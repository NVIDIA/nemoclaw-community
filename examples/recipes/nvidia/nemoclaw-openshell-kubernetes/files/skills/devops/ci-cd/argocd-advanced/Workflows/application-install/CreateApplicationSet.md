# CreateApplicationSet Workflow

Create a new ArgoCD ApplicationSet for a workload using the ExampleApp multi-source template pattern.

## Voice Notification

```bash
curl -s -X POST http://localhost:8888/notify \
  -H "Content-Type: application/json" \
  -d '{"message": "Running CreateApplicationSet in ArgocdAppInstall to create new ApplicationSet"}' \
  > /dev/null 2>&1 &
```

Running the **CreateApplicationSet** workflow in the **ArgocdAppInstall** skill to create new ApplicationSet...

## Prerequisites

Before starting, gather from the user:
1. **Service name** (e.g., `grafana-oncall`)
2. **Helm chart details** (chart name, repo URL, version)
3. **Target namespace** (e.g., `monitoring`)
4. **Component category** (monitoring, security, networking, storage, etc.)
5. **Target clusters** (which clusters to deploy to)
6. **Sync wave** (-10 to 10, default 0)

If the user doesn't specify all of these, use reasonable defaults and ask for the missing critical ones (service name and chart details are mandatory).

## Step 1: Read the Template

Read the project TEMPLATE.yaml:
```
Read infra-team/applicationset/TEMPLATE.yaml
```

Also read an existing ApplicationSet for reference pattern:
```
Read infra-team/applicationset/robusta.yaml
```

## Step 2: Copy and Customize Template

Create the new ApplicationSet file at `infra-team/applicationset/<service-name>.yaml`.

### Placeholder Replacement Table

| Placeholder | Replace With | Notes |
|---|---|---|
| `<SERVICE_NAME>` | Service name (lowercase, hyphens OK) | Used everywhere: metadata, labels, template, paths |
| `<COMPONENT>` | Component category | monitoring, security, networking, storage |
| `<CHART_NAME>` | Helm chart name | From the chart repository |
| `<CHART_REPO_URL>` | Helm repository URL | Full HTTPS URL |
| `<CHART_VERSION>` | Pinned chart version | Always pin to specific version |
| `<TARGET_NAMESPACE>` | Kubernetes namespace | Where pods run |
| `<PURPOSE>` | Namespace purpose label | Same as component usually |
| `<CRITICALITY>` | high, medium, low | Based on service importance |

### Cluster Selection

Remove clusters from the `generators.list.elements` that should NOT receive this service. Use your own cluster inventory (kept outside this skill) as the source of truth for cluster URLs.

**Common patterns:**
- **All clusters**: Keep all entries from template
- **Hub only**: Keep only `example-app-hub`
- **Dev only**: Keep `example-app-dev`, `loyalty-dev` (and others as needed)
- **Prod only**: Keep `example-app-prd`, `loyalty-prd` (and others as needed)
- **Business unit specific**: Keep only clusters for that unit

### Required Labels

Every ApplicationSet MUST have these labels:
```yaml
labels:
  app.kubernetes.io/name: <SERVICE_NAME>
  app.kubernetes.io/part-of: kube-addons
  app.kubernetes.io/component: <COMPONENT>
  app.kubernetes.io/managed-by: argocd
  example.com/lifecycle: active
  example.com/managed-via: kustomization
annotations:
  example.com/owner-team: platform-engineering
```

### Safety Policy

Always include at the `spec.syncPolicy` level:
```yaml
syncPolicy:
  preserveResourcesOnDeletion: true
```

This prevents accidental cascade deletion if the ApplicationSet is removed.

## Step 3: Create Values Files

For each target cluster, create the values directory and file:

```bash
# Create directories
mkdir -p argo-cd-helm-values/kube-addons/<service-name>/<cluster-name>/

# Create values.yaml for each cluster
touch argo-cd-helm-values/kube-addons/<service-name>/<cluster-name>/values.yaml
```

### Mandatory: Spot Tolerations for Development Clusters

**ALL development cluster values MUST include spot tolerations:**

```yaml
# argo-cd-helm-values/kube-addons/<service>/example-app-dev/values.yaml
tolerations:
  - key: kubernetes.azure.com/scalesetpriority
    operator: Equal
    value: "spot"
    effect: NoSchedule
```

Development clusters that require spot tolerations:
- `example-app-dev`
- `loyalty-dev`
- `example-app2-dev`
- `example-app3-dev`

### Production Values

Production values should include at minimum:
- Resource requests and limits
- Appropriate replica counts
- PodDisruptionBudgets where applicable

## Step 4: Register in Kustomization

Add the new file to `infra-team/applicationset/kustomization.yaml` in **alphabetical order**:

```yaml
resources:
  # ... existing entries
  - <service-name>.yaml  # Add in alphabetical position
```

## Step 5: Validate

Run pre-commit validation:
```bash
pre-commit run --all-files
```

Fix any issues reported before proceeding.

## Step 6: Review the Generated Files

Before committing, verify:

1. **ApplicationSet YAML** is valid:
   - All placeholders replaced
   - Cluster URLs are correct (cross-reference with your own cluster inventory)
   - Multi-source references are correct ($values path)
   - Labels and annotations are complete
   - `preserveResourcesOnDeletion: true` is present

2. **Values files** exist for every cluster in the generator list

3. **Kustomization.yaml** includes the new file

## Step 7: Commit

```bash
git add infra-team/applicationset/<service-name>.yaml
git add infra-team/applicationset/kustomization.yaml
git add argo-cd-helm-values/kube-addons/<service-name>/
git commit -m "feat(<service-name>): add ApplicationSet for <service-name>"
```

## Step 8: Post-Deployment Verification

After push, verify in ArgoCD (inspection-only commands):
```bash
# Check ApplicationSet was created
kubectl get applicationset -n argocd <service-name>

# Check generated Applications
kubectl get applications -n argocd | grep <service-name>

# Check sync status
argocd app list | grep <service-name>
```

## Multi-Source Configuration Reference

The standard multi-source pattern used by all ApplicationSets:

```yaml
sources:
  # Source 1: Helm chart from public registry
  - chart: <CHART_NAME>
    repoURL: <CHART_REPO_URL>
    targetRevision: <CHART_VERSION>
    helm:
      releaseName: <SERVICE_NAME>
      valueFiles:
        - $values/argo-cd-helm-values/kube-addons/<SERVICE_NAME>/{{cluster}}/values.yaml

  # Source 2: Values repository (provides $values ref)
  - repoURL: https://your-org@dev.azure.com/your-org/devops-team/_git/argocd
    targetRevision: "{{branch}}"
    ref: values

  # Source 3 (Optional): Additional K8s manifests
  # - repoURL: https://your-org@dev.azure.com/your-org/devops-team/_git/argocd
  #   targetRevision: "{{branch}}"
  #   path: argo-cd-helm-values/kube-addons/<SERVICE_NAME>/{{cluster}}
  #   directory:
  #     exclude: values.yaml
```

**Source 3** is needed when you have extra Kubernetes manifests (SecretProviderClass, ConfigMaps, etc.) alongside the values.yaml. The `directory.exclude: values.yaml` prevents double-processing.
