---
name: argocd-applicationset
description: Implement, configure, and operate ArgoCD ApplicationSet for multi-cluster, multi-tenant GitOps deployments. Use when working with the ApplicationSet CRD, generators (list, cluster, git, matrix, merge, SCM, pull request, plugin), templating, multi-cluster app propagation, or related troubleshooting.
---

# ArgoCD ApplicationSet Skill

Comprehensive guide for implementing, configuring, and operating **ArgoCD ApplicationSet** - the powerful Kubernetes controller that automates Argo CD Application generation for multi-cluster, multi-tenant, and GitOps deployments.

**ArgoCD Version:** 2.9+ (ApplicationSet is built-in since v2.3)
**API Version:** `argoproj.io/v1alpha1`

## Overview

ApplicationSet is a Kubernetes controller that adds support for the `ApplicationSet` CustomResourceDefinition (CRD), enabling:

- **Multi-Cluster Deployment**: Deploy applications across multiple Kubernetes clusters from a single manifest
- **Monorepo Support**: Generate applications from directory structures or configuration files in Git
- **Multi-Tenant Self-Service**: Allow developers to create Applications without cluster-admin intervention
- **GitOps Automation**: Automatically create, update, and delete Argo CD Applications based on generators

## Quick Reference

| Resource | Path |
|----------|------|
| Generator Examples | `references/generators/` |
| Template Patterns | `references/templates/` |
| Common Patterns | `references/patterns/` |
| Troubleshooting | `references/troubleshooting/` |

---

## 1. ApplicationSet Structure

### Basic Structure

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: my-applicationset
  namespace: argocd
spec:
  # Generators produce parameters for templates
  generators:
    - list:
        elements:
          - cluster: dev
            url: https://dev.example.com
          - cluster: prod
            url: https://prod.example.com

  # Template defines the Application to create
  template:
    metadata:
      name: '{{.cluster}}-myapp'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/repo.git
        targetRevision: HEAD
        path: apps/myapp
      destination:
        server: '{{.url}}'
        namespace: myapp

  # Optional: Sync policy for application lifecycle
  syncPolicy:
    preserveResourcesOnDeletion: false
    applicationsSync: sync

  # Optional: Enable Go templating (recommended)
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
```

### Key Fields

| Field | Description | Required |
|-------|-------------|----------|
| `generators` | List of generators that produce parameters | Yes |
| `template` | Application template with parameter placeholders | Yes |
| `syncPolicy` | Controls application creation/update/deletion behavior | No |
| `goTemplate` | Enable Go text templating (recommended) | No |
| `goTemplateOptions` | Go template parsing options | No |
| `strategy` | Progressive sync strategy (RollingSync) | No |
| `preservedFields` | Fields to preserve during updates | No |
| `ignoreApplicationDifferences` | Fields to ignore during comparison | No |

---

## 2. Generators

Generators produce parameters that are substituted into the ApplicationSet template. Multiple generators can be combined.

### 2.1 List Generator

Creates applications from a fixed list of key/value pairs.

```yaml
generators:
  - list:
      elements:
        - cluster: engineering-dev
          url: https://kubernetes.default.svc
          environment: development
        - cluster: engineering-prod
          url: https://prod.example.com
          environment: production
```

**Use Cases:**
- Fixed set of deployment targets
- Environment-specific configurations
- Simple multi-cluster deployments

### 2.2 Cluster Generator

Automatically discovers clusters registered in Argo CD.

```yaml
generators:
  - clusters:
      # Select all clusters
      selector: {}

      # Or filter by labels
      selector:
        matchLabels:
          environment: production
        matchExpressions:
          - key: region
            operator: In
            values:
              - us-east
              - us-west

      # Pass additional values
      values:
        revision: HEAD
        helmValues: production
```

**Generated Parameters:**
- `{{.name}}` - Cluster name
- `{{.nameNormalized}}` - DNS-safe cluster name
- `{{.server}}` - Cluster API server URL
- `{{.metadata.labels.<key>}}` - Cluster labels
- `{{.metadata.annotations.<key>}}` - Cluster annotations

**Including Local Cluster:**
The local cluster (in-cluster) doesn't have a Secret by default. To include it in label selectors, edit the cluster in Argo CD UI to create its Secret.

### 2.3 Git Generator - Directory

Generates applications based on directory structure in a Git repository.

```yaml
generators:
  - git:
      repoURL: https://github.com/org/gitops-repo.git
      revision: HEAD
      directories:
        # Include all directories under clusters/
        - path: clusters/*
        # Exclude specific directories
        - path: clusters/deprecated/*
          exclude: true
```

**Generated Parameters:**
- `{{.path.path}}` - Full directory path (e.g., `clusters/dev`)
- `{{.path.basename}}` - Directory name (e.g., `dev`)
- `{{.path.basenameNormalized}}` - DNS-safe directory name
- `{{index .path.segments N}}` - Path segment at index N

### 2.4 Git Generator - File

Generates applications from JSON/YAML configuration files.

```yaml
generators:
  - git:
      repoURL: https://github.com/org/gitops-repo.git
      revision: HEAD
      files:
        - path: "config/**/config.json"
```

**Example config.json:**
```json
{
  "cluster": {
    "owner": "team-a",
    "name": "production",
    "address": "https://prod.example.com"
  },
  "app": {
    "name": "myapp",
    "namespace": "default"
  }
}
```

**Generated Parameters:**
- All JSON fields are flattened: `{{.cluster.name}}`, `{{.app.namespace}}`
- Path parameters: `{{.path.path}}`, `{{.path.basename}}`, `{{.path.filename}}`

### 2.5 Matrix Generator

Combines two generators, creating every permutation of their outputs.

```yaml
generators:
  - matrix:
      generators:
        # First generator: Git directories (apps)
        - git:
            repoURL: https://github.com/org/apps.git
            revision: HEAD
            directories:
              - path: apps/*
        # Second generator: Clusters
        - clusters:
            selector:
              matchLabels:
                environment: production
```

**Result:** If Git finds 3 apps and Cluster finds 2 clusters, Matrix produces 6 Applications.

**Restrictions:**
- Maximum 2 child generators
- Only 1 level of nesting (no nested Matrix within Matrix)
- Child generators cannot have template overrides

### 2.6 Merge Generator

Merges parameters from multiple generators using merge keys.

```yaml
generators:
  - merge:
      mergeKeys:
        - cluster
      generators:
        # Base generator: All clusters
        - clusters:
            values:
              helmValues: default
        # Override for specific clusters
        - clusters:
            selector:
              matchLabels:
                environment: production
            values:
              helmValues: production
        # Exception for specific cluster
        - list:
            elements:
              - cluster: special-cluster
                helmValues: custom
```

**Override Precedence:** Bottom-to-top (later generators override earlier ones)

### 2.7 SCM Provider Generator

Discovers repositories from SCM platforms (GitHub, GitLab, Azure DevOps, Bitbucket).

```yaml
generators:
  - scmProvider:
      # GitHub Organization
      github:
        organization: myorg
        tokenRef:
          secretName: github-token
          key: token
        allBranches: false

      # Filter repositories
      filters:
        - repositoryMatch: ^microservice-.*
        - pathsExist:
            - kubernetes/
        - labelMatch: deploy-enabled

      cloneProtocol: https
      requeueAfterSeconds: 300
```

**Azure DevOps Configuration:**
```yaml
generators:
  - scmProvider:
      azureDevOps:
        organization: myorg
        teamProject: MyProject
        accessTokenRef:
          secretName: azure-devops-token
          key: token
        allBranches: true
      filters:
        - repositoryMatch: ^app-.*
```

**Generated Parameters:**
- `{{.organization}}` - Organization/owner name
- `{{.repository}}` - Repository name
- `{{.url}}` - Clone URL
- `{{.branch}}` - Branch name
- `{{.sha}}` - Commit SHA
- `{{.short_sha}}` - Short commit SHA
- `{{.labels}}` - Repository labels/topics

### 2.8 Pull Request Generator

Generates applications for open pull requests.

```yaml
generators:
  - pullRequest:
      github:
        owner: myorg
        repo: myrepo
        tokenRef:
          secretName: github-token
          key: token
        labels:
          - preview
      requeueAfterSeconds: 300
```

**Azure DevOps Configuration:**
```yaml
generators:
  - pullRequest:
      azuredevops:
        organization: myorg
        project: MyProject
        repo: myrepo
        tokenRef:
          secretName: azure-devops-token
          key: token
```

**Generated Parameters:**
- `{{.number}}` - PR number
- `{{.branch}}` - Source branch name
- `{{.branch_slug}}` - DNS-safe branch name
- `{{.target_branch}}` - Target branch
- `{{.head_sha}}` - Head commit SHA
- `{{.head_short_sha}}` - Short head SHA
- `{{.author}}` - PR author
- `{{.title}}` - PR title

### 2.9 Plugin Generator

Custom generator using external RPC HTTP requests.

```yaml
generators:
  - plugin:
      configMapRef:
        name: my-plugin
      input:
        parameters:
          key1: value1
      requeueAfterSeconds: 300
```

---

## 3. Templates

### 3.1 Basic Template

```yaml
template:
  metadata:
    name: '{{.cluster}}-{{.app}}'
    labels:
      app: '{{.app}}'
      environment: '{{.environment}}'
    annotations:
      notifications.argoproj.io/subscribe.on-sync-failed.slack: alerts
    finalizers:
      - resources-finalizer.argocd.argoproj.io
  spec:
    project: default
    source:
      repoURL: '{{.repoURL}}'
      targetRevision: '{{.revision}}'
      path: '{{.path}}'
    destination:
      server: '{{.url}}'
      namespace: '{{.namespace}}'
    syncPolicy:
      automated:
        prune: true
        selfHeal: true
```

### 3.2 Multi-Source Template

Combine Helm charts with external values files.

```yaml
template:
  metadata:
    name: '{{.cluster}}-{{.app}}'
  spec:
    project: default
    sources:
      # Source 1: Helm chart from public repository
      - chart: '{{.chart}}'
        repoURL: '{{.chartRepo}}'
        targetRevision: '{{.chartVersion}}'
        helm:
          releaseName: '{{.app}}'
          valueFiles:
            - $values/{{.valuesPath}}/values.yaml
      # Source 2: Values from Git repository
      - repoURL: '{{.valuesRepo}}'
        targetRevision: '{{.valuesRevision}}'
        ref: values
    destination:
      server: '{{.url}}'
      namespace: '{{.namespace}}'
```

### 3.3 Generator-Level Template Override

Override specific template fields per generator.

```yaml
generators:
  - list:
      elements:
        - cluster: dev
          url: https://dev.example.com
      # Override for this generator only
      template:
        spec:
          source:
            targetRevision: develop
  - list:
      elements:
        - cluster: prod
          url: https://prod.example.com
      template:
        spec:
          source:
            targetRevision: main

# Base template (can be overridden)
template:
  metadata:
    name: '{{.cluster}}-myapp'
  spec:
    project: default
    source:
      repoURL: https://github.com/org/repo.git
      targetRevision: HEAD  # Overridden by generator templates
      path: apps/myapp
    destination:
      server: '{{.url}}'
      namespace: myapp
```

### 3.4 Template Patch (Advanced)

For non-string fields, use templatePatch with Go templating.

```yaml
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]

  generators:
    - list:
        elements:
          - cluster: dev
            replicas: 1
          - cluster: prod
            replicas: 3

  template:
    metadata:
      name: '{{.cluster}}-myapp'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/repo.git
        path: apps/myapp
      destination:
        server: '{{.url}}'

  templatePatch: |
    spec:
      source:
        helm:
          parameters:
            - name: replicas
              value: "{{.replicas}}"
```

---

## 4. Go Templating

Enable Go templating for advanced functionality.

### 4.1 Configuration

```yaml
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]  # Recommended: fail on undefined
```

### 4.2 Available Functions

**Sprig Functions** (except `env`, `expandenv`, `getHostByName`):
- String: `lower`, `upper`, `trim`, `replace`, `contains`, `hasPrefix`, `hasSuffix`
- Lists: `list`, `first`, `last`, `index`, `slice`
- Math: `add`, `sub`, `mul`, `div`
- Date: `now`, `date`, `dateModify`
- Crypto: `sha256sum`, `b64enc`, `b64dec`

**Custom Functions:**
- `normalize` - Sanitize to DNS-compliant name (lowercase, alphanumeric, hyphens, dots)
- `slugify` - Smart truncation without cutting words
- `toYaml` / `fromYaml` / `fromYamlArray` - YAML conversion

### 4.3 Common Patterns

```yaml
# Conditional with default
name: '{{.cluster}}{{dig "suffix" "" .}}'

# String manipulation
name: '{{ .cluster | lower | replace "_" "-" }}'

# Index access for labels with special characters
env: '{{ index .metadata.labels "env-type" }}'

# Conditional logic
{{- if eq .environment "production" }}
replicas: 3
{{- else }}
replicas: 1
{{- end }}

# List iteration (in templatePatch)
{{- range .namespaces }}
- namespace: {{ . }}
{{- end }}
```

### 4.4 Migration from FastTemplate

| FastTemplate | Go Template |
|--------------|-------------|
| `{{ value }}` | `{{ .value }}` |
| `{{ path }}` | `{{ .path.path }}` |
| `{{ path.basename }}` | `{{ .path.basename }}` |
| `{{ path[0] }}` | `{{ index .path.segments 0 }}` |
| `{{ metadata.labels.my-label }}` | `{{ index .metadata.labels "my-label" }}` |

---

## 5. Sync Policies

### 5.1 Application Sync Policy

Control how generated Applications are synced.

```yaml
spec:
  syncPolicy:
    # Prevent deletion of child resources when ApplicationSet is deleted
    preserveResourcesOnDeletion: true

    # Control application lifecycle: sync, create-only, create-update, create-delete
    applicationsSync: sync
```

**applicationsSync Options:**
| Value | Create | Update | Delete |
|-------|--------|--------|--------|
| `sync` (default) | Yes | Yes | Yes |
| `create-only` | Yes | No | No |
| `create-update` | Yes | Yes | No |
| `create-delete` | Yes | No | Yes |

### 5.2 Progressive Syncs (Rolling Updates)

Deploy applications in controlled stages.

```yaml
spec:
  # Enable progressive syncs (requires controller flag)
  strategy:
    type: RollingSync
    rollingSync:
      steps:
        # Step 1: Dev environments first
        - matchExpressions:
            - key: environment
              operator: In
              values:
                - dev
          maxUpdate: 100%  # All dev at once

        # Step 2: Staging
        - matchExpressions:
            - key: environment
              operator: In
              values:
                - staging
          maxUpdate: 50%  # Half at a time

        # Step 3: Production (careful rollout)
        - matchExpressions:
            - key: environment
              operator: In
              values:
                - production
          maxUpdate: 1  # One at a time
```

**Enable Progressive Syncs:**
```bash
# Via environment variable
ARGOCD_APPLICATIONSET_CONTROLLER_ENABLE_PROGRESSIVE_SYNCS=true

# Via ConfigMap
kubectl patch cm argocd-cmd-params-cm -n argocd --type merge -p '{"data":{"applicationsetcontroller.enable.progressive.syncs":"true"}}'
```

---

## 6. Ignore Differences

Prevent ApplicationSet from overwriting certain Application fields.

```yaml
spec:
  ignoreApplicationDifferences:
    # Ignore replica count changes (for HPA)
    - jsonPointers:
        - /spec/replicas

    # Ignore specific annotations
    - jqPathExpressions:
        - .metadata.annotations["kubectl.kubernetes.io/last-applied-configuration"]

    # Ignore for specific applications only
    - name: "prod-*"
      jsonPointers:
        - /spec/source/targetRevision
```

---

## 7. Security Considerations

### 7.1 Access Control

**CRITICAL:** Only admins should have permission to create, update, or delete ApplicationSets.

```yaml
# RBAC Policy - Restrict ApplicationSet access
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.csv: |
    # Only admins can manage ApplicationSets
    p, role:admin, applicationsets, *, */*, allow

    # Developers can only view
    p, role:developer, applicationsets, get, */*, allow
```

### 7.2 Project Field Security

**WARNING:** If the `project` field is templated from Git sources, ensure:
- Repository write access is restricted to admins
- PRs require admin approval
- Use non-scoped repositories (blank project in Argo CD)

```yaml
# DANGEROUS - Project templated from Git
spec:
  template:
    spec:
      project: '{{.project}}'  # Could be exploited!

# SAFER - Fixed project
spec:
  template:
    spec:
      project: my-restricted-project
```

### 7.3 Token Management

Store SCM tokens securely in Kubernetes Secrets.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: github-token
  namespace: argocd
type: Opaque
stringData:
  token: ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## 8. Common Patterns

### 8.1 Multi-Cluster Deployment

Deploy to all registered clusters.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: multi-cluster-app
  namespace: argocd
spec:
  goTemplate: true
  generators:
    - clusters:
        selector:
          matchLabels:
            deploy: "true"
  template:
    metadata:
      name: '{{.name}}-myapp'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/repo.git
        targetRevision: HEAD
        path: apps/myapp
      destination:
        server: '{{.server}}'
        namespace: myapp
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

### 8.2 Monorepo with Directory Structure

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: monorepo-apps
  namespace: argocd
spec:
  goTemplate: true
  generators:
    - git:
        repoURL: https://github.com/org/monorepo.git
        revision: HEAD
        directories:
          - path: apps/*
          - path: apps/deprecated/*
            exclude: true
  template:
    metadata:
      name: '{{.path.basename}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/monorepo.git
        targetRevision: HEAD
        path: '{{.path.path}}'
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{.path.basename}}'
```

### 8.3 Preview Environments for Pull Requests

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: pr-preview
  namespace: argocd
spec:
  goTemplate: true
  generators:
    - pullRequest:
        github:
          owner: myorg
          repo: myapp
          tokenRef:
            secretName: github-token
            key: token
          labels:
            - preview
        requeueAfterSeconds: 60
  template:
    metadata:
      name: 'preview-{{.number}}'
      labels:
        app: myapp
        pr: '{{.number}}'
    spec:
      project: previews
      source:
        repoURL: https://github.com/myorg/myapp.git
        targetRevision: '{{.head_sha}}'
        path: kubernetes
      destination:
        server: https://kubernetes.default.svc
        namespace: 'preview-{{.number}}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

### 8.4 Helm Chart with Multi-Source Values

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: helm-multi-source
  namespace: argocd
spec:
  goTemplate: true
  generators:
    - list:
        elements:
          - cluster: example-app-dev
            url: https://dev-cluster.example.com
            environment: development
            branch: main
          - cluster: example-app-prod
            url: https://prod-cluster.example.com
            environment: production
            branch: main
  template:
    metadata:
      name: '{{.cluster}}-myapp'
    spec:
      project: default
      sources:
        # Helm chart from public repo
        - chart: myapp
          repoURL: https://charts.example.com
          targetRevision: 1.0.0
          helm:
            releaseName: myapp
            valueFiles:
              - $values/helm-values/myapp/{{.cluster}}/values.yaml
        # Values from Git
        - repoURL: https://github.com/org/gitops-values.git
          targetRevision: '{{.branch}}'
          ref: values
      destination:
        server: '{{.url}}'
        namespace: myapp
```

### 8.5 App-of-Apps Pattern

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: app-of-apps
  namespace: argocd
spec:
  goTemplate: true
  generators:
    - git:
        repoURL: https://github.com/org/gitops.git
        revision: HEAD
        files:
          - path: "environments/*/apps.yaml"
  template:
    metadata:
      name: '{{.environment}}-apps'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/gitops.git
        targetRevision: HEAD
        path: 'environments/{{.environment}}'
      destination:
        server: '{{.cluster.server}}'
        namespace: argocd
```

---

## 9. Troubleshooting

### 9.1 Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Applications not created | Generator returns empty results | Check generator filters, verify source data exists |
| Template substitution errors | Missing or undefined parameters | Use `goTemplateOptions: ["missingkey=error"]` to debug |
| Applications deleted unexpectedly | Generator no longer matches | Check syncPolicy, use `preserveResourcesOnDeletion` |
| Duplicate applications | Multiple generators produce same name | Add unique prefixes/suffixes to names |
| Rate limiting from SCM | Too frequent polling | Increase `requeueAfterSeconds`, use webhooks |

### 9.2 Debug Commands

```bash
# Check ApplicationSet status
kubectl get applicationsets -n argocd

# Describe ApplicationSet for events/errors
kubectl describe applicationset <name> -n argocd

# View generated Applications
kubectl get applications -n argocd -l app.kubernetes.io/instance=<appset-name>

# Check ApplicationSet controller logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller -f

# Dry-run to see what would be generated (via argocd CLI)
argocd appset generate <appset.yaml>
```

### 9.3 Webhook Configuration

Reduce polling by configuring webhooks.

**GitHub Webhook:**
- URL: `https://argocd.example.com/api/webhook`
- Content Type: `application/json`
- Events: `Push`, `Pull Request`
- Secret: Configure in `argocd-secret`

```yaml
# argocd-secret
apiVersion: v1
kind: Secret
metadata:
  name: argocd-secret
  namespace: argocd
stringData:
  webhook.github.secret: your-webhook-secret
```

---

## 10. Best Practices

1. **Always use Go templating** with `goTemplate: true` and `goTemplateOptions: ["missingkey=error"]`

2. **Use descriptive Application names** that include cluster/environment identifiers

3. **Add labels** to generated Applications for filtering and grouping

4. **Configure finalizers** for proper cleanup: `resources-finalizer.argocd.argoproj.io`

5. **Use progressive syncs** for production deployments to reduce blast radius

6. **Restrict ApplicationSet RBAC** - only admins should create/modify ApplicationSets

7. **Never template the project field** from untrusted sources

8. **Use webhooks** instead of polling for faster response to changes

9. **Set appropriate requeue intervals** to balance responsiveness and API rate limits

10. **Use ignoreApplicationDifferences** for fields managed by other controllers (HPA, etc.)

---

## 11. Reference Files

Additional templates and examples are in the `references/` directory:

**Generators:**
- `references/generators/list-generator.yaml`
- `references/generators/cluster-generator.yaml`
- `references/generators/git-directory-generator.yaml`
- `references/generators/git-file-generator.yaml`
- `references/generators/matrix-generator.yaml`
- `references/generators/merge-generator.yaml`
- `references/generators/scm-provider-generator.yaml`
- `references/generators/pull-request-generator.yaml`

**Templates:**
- `references/templates/basic-template.yaml`
- `references/templates/multi-source-template.yaml`
- `references/templates/helm-values-template.yaml`

**Patterns:**
- `references/patterns/multi-cluster.yaml`
- `references/patterns/monorepo.yaml`
- `references/patterns/preview-environments.yaml`
- `references/patterns/progressive-rollout.yaml`
- `references/patterns/azure-devops-integration.yaml`

**Troubleshooting:**
- `references/troubleshooting/common-issues.md`
- `references/troubleshooting/debug-checklist.md`

---

## Related Skills

- `argocd-skill` - General ArgoCD operations
- `gitops-principles-skill` - GitOps methodology
- `kargo-skill` - Progressive delivery with Kargo
- `helm-skill` - Helm chart management
