# ValidateApplicationSet Workflow

Validate an existing ArgoCD ApplicationSet for correctness and completeness.

## Voice Notification

```bash
curl -s -X POST http://localhost:8888/notify \
  -H "Content-Type: application/json" \
  -d '{"message": "Running ValidateApplicationSet in ArgocdAppInstall to validate ApplicationSet"}' \
  > /dev/null 2>&1 &
```

Running the **ValidateApplicationSet** workflow in the **ArgocdAppInstall** skill to validate ApplicationSet...

## Step 1: Identify the Target

Determine which ApplicationSet to validate from the user's request. The file is at:
```
infra-team/applicationset/<service-name>.yaml
```

Read the ApplicationSet file.

## Step 2: Structural Validation

Check the following against the TEMPLATE.yaml pattern:

### Required Fields
- [ ] `apiVersion: argoproj.io/v1alpha1`
- [ ] `kind: ApplicationSet`
- [ ] `metadata.name` matches service name
- [ ] `metadata.namespace: argocd`
- [ ] Required labels present (`app.kubernetes.io/name`, `part-of`, `component`, `managed-by`)
- [ ] `example.com/lifecycle: active` label
- [ ] `example.com/managed-via: kustomization` label
- [ ] `example.com/owner-team` annotation

### Safety Policy
- [ ] `spec.syncPolicy.preserveResourcesOnDeletion: true` present

### Generator
- [ ] Uses list generator pattern
- [ ] Each element has: `cluster`, `url`, `project`, `branch`, `environment`
- [ ] Cluster URLs match known inventory (cross-reference with your own cluster inventory)
- [ ] `project` matches the business unit pattern (e.g., `kube-addons`, `loyalty-kube-addons`)

### Template
- [ ] `name: "{{cluster}}-<service>"` pattern
- [ ] All standard labels and annotations present
- [ ] `revisionHistoryLimit: 10`
- [ ] `project: "{{project}}"` uses template variable

### Multi-Source Configuration
- [ ] Source 1: Helm chart with `$values` reference to values file
- [ ] Source 2: Values repo with `ref: values`
- [ ] Values path: `$values/argo-cd-helm-values/kube-addons/<service>/{{cluster}}/values.yaml`

### Sync Policy
- [ ] `automated.prune: true`
- [ ] `automated.selfHeal: true`
- [ ] `automated.allowEmpty: false`
- [ ] Retry configuration present
- [ ] `ServerSideApply=true` in syncOptions
- [ ] `managedNamespaceMetadata` labels present

## Step 3: Values Files Validation

For each cluster in the generator list, verify:

```bash
# Check values files exist
ls argo-cd-helm-values/kube-addons/<service>/<cluster>/values.yaml
```

- [ ] Values file exists for every cluster in generator
- [ ] Dev cluster values include spot tolerations
- [ ] Values files are valid YAML

## Step 4: Kustomization Registration

Check `infra-team/applicationset/kustomization.yaml`:
- [ ] Service file is listed in resources
- [ ] Listed in alphabetical order

## Step 5: Pre-commit Validation

```bash
pre-commit run --all-files
```

- [ ] All pre-commit hooks pass

## Step 6: Report

Present findings as a checklist with pass/fail for each item. If any items fail, provide specific remediation steps.
