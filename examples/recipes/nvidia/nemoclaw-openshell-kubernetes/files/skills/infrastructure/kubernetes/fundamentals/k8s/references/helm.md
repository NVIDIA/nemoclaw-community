# Helm Operations Guide

Comprehensive reference for Helm chart management, values handling, Helmfile, and chart authoring.

---

## Table of Contents

1. [Core Commands](#core-commands)
2. [Inspection Commands](#inspection-commands)
3. [Repository Management](#repository-management)
4. [Chart Structure](#chart-structure)
5. [Values Management](#values-management)
6. [Helmfile](#helmfile)
7. [Chart Testing and Linting](#chart-testing-and-linting)
8. [Common Patterns](#common-patterns)

---

## Core Commands

### Install

```bash
# Basic install
helm install myapp ./charts/myapp -n production

# Install from repo
helm install myapp bitnami/postgresql -n production

# Install with custom values
helm install myapp ./charts/myapp -n production \
  -f values-production.yaml \
  --set image.tag=v1.2.3

# Create namespace if missing
helm install myapp ./charts/myapp -n production --create-namespace
```

### Upgrade

```bash
# Upgrade existing release
helm upgrade myapp ./charts/myapp -n production -f values-production.yaml

# Idempotent install-or-upgrade (preferred for CI/CD)
helm upgrade --install myapp ./charts/myapp -n production \
  -f values-production.yaml

# Atomic: auto-rollback on failure
helm upgrade --install myapp ./charts/myapp -n production \
  -f values-production.yaml \
  --atomic \
  --timeout 5m
```

### Rollback

```bash
# Rollback to previous revision
helm rollback myapp -n production

# Rollback to specific revision
helm rollback myapp 3 -n production

# Check history first
helm history myapp -n production
```

### Uninstall

```bash
# Remove release
helm uninstall myapp -n production

# Keep history (allows rollback after uninstall)
helm uninstall myapp -n production --keep-history
```

### Key Flags

| Flag | Purpose |
|------|---------|
| `--atomic` | Auto-rollback on failure (implies `--wait`) |
| `--wait` | Wait until all resources are healthy |
| `--timeout 5m` | Max wait time for `--wait` |
| `--dry-run` | Preview without applying |
| `--debug` | Show rendered templates and debug info |
| `--create-namespace` | Create namespace if it does not exist |
| `--force` | Force resource updates via delete/recreate |
| `--cleanup-on-fail` | Delete new resources on failed upgrade |

---

## Inspection Commands

```bash
# List releases in a namespace
helm list -n production

# List releases across all namespaces
helm list -A

# Release status
helm status myapp -n production

# Version history
helm history myapp -n production

# Get current values (user-supplied)
helm get values myapp -n production

# Get all values (including defaults)
helm get values myapp -n production --all

# Get rendered manifests
helm get manifest myapp -n production

# Get release notes
helm get notes myapp -n production

# Preview what would be rendered (without installing)
helm template myapp ./charts/myapp -f values-production.yaml

# Diff between current and proposed (requires helm-diff plugin)
helm diff upgrade myapp ./charts/myapp -f values-production.yaml -n production
```

---

## Repository Management

```bash
# Add a repo
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx

# Update repo index
helm repo update

# List repos
helm repo list

# Search for charts
helm search repo postgresql
helm search repo postgresql --versions   # Show all versions

# Show chart info
helm show chart bitnami/postgresql
helm show values bitnami/postgresql      # Show default values
helm show readme bitnami/postgresql

# OCI registries (Helm 3.8+)
helm pull oci://registry.example.com/charts/myapp --version 1.0.0
helm push myapp-1.0.0.tgz oci://registry.example.com/charts
```

---

## Chart Structure

```
myapp/
├── Chart.yaml              # Chart metadata (name, version, dependencies)
├── Chart.lock              # Locked dependency versions
├── values.yaml             # Default configuration values
├── values.schema.json      # Optional: JSON Schema for values validation
├── templates/
│   ├── _helpers.tpl        # Template helper functions
│   ├── NOTES.txt           # Post-install/upgrade instructions
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   ├── hpa.yaml
│   ├── pdb.yaml
│   └── serviceaccount.yaml
├── charts/                 # Subcharts (dependencies)
└── .helmignore             # Files to exclude from packaging
```

### .helmignore

The `.helmignore` file controls which files are excluded when packaging a chart with `helm package`. It uses the same syntax as `.gitignore`. Keeping the package lean avoids shipping unnecessary files to the cluster or OCI registry.

```
# Version control -- not needed in the packaged chart
.git
.gitignore

# OS and editor artifacts
.DS_Store
*.swp
*.bak
*.tmp
*~
.idea/
.vscode/

# Language build artifacts
__pycache__/
*.pyc

# Packaged charts -- avoid nesting .tgz inside a chart
*.tgz

# CI/CD configuration -- not part of the runtime chart
.github/
.gitlab-ci.yml
.circleci/

# Project docs and metadata -- not needed at deploy time
tests/
docs/
README.md
CHANGELOG.md
LICENSE
```

**Why it matters:**

- `helm package` includes every file under the chart directory by default. Without `.helmignore`, the `.tgz` artifact can contain git history, CI configs, documentation, and editor metadata -- none of which are useful at install time.
- Smaller chart archives mean faster pushes to OCI registries and faster `helm install` from remote repositories.
- Excluding `*.tgz` prevents accidentally nesting a previously packaged chart inside itself.

### Chart.yaml

```yaml
apiVersion: v2
name: myapp
description: My application Helm chart
type: application             # or "library"
version: 1.0.0               # Chart version (bump on chart changes)
appVersion: "2.3.1"          # Application version
dependencies:
  - name: postgresql
    version: "12.x.x"
    repository: https://charts.bitnami.com/bitnami
    condition: postgresql.enabled
```

### _helpers.tpl (Common Patterns)

```yaml
{{- define "myapp.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "myapp.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "myapp.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
```

---

## Values Management

### Precedence (lower overrides higher)

1. Chart `values.yaml` (defaults)
2. Parent chart `values.yaml` (if subchart)
3. `-f custom-values.yaml` (file override, last file wins)
4. `--set key=value` (CLI override, highest priority)

### Environment-Specific Values

```
charts/myapp/
├── values.yaml                  # Defaults
├── values-dev.yaml              # Dev overrides
├── values-staging.yaml          # Staging overrides
└── values-production.yaml       # Production overrides
```

```bash
# Deploy to staging
helm upgrade --install myapp ./charts/myapp -n staging \
  -f values.yaml \
  -f values-staging.yaml

# Deploy to production
helm upgrade --install myapp ./charts/myapp -n production \
  -f values.yaml \
  -f values-production.yaml
```

### Set Syntax

```bash
# Simple value
--set image.tag=v1.2.3

# String value (force string type)
--set-string nodeSelector."kubernetes\.io/os"=linux

# Array value
--set ingress.hosts[0].host=example.com

# Multiple values
--set replicas=3,image.tag=v1.2.3

# From file content
--set-file ca.crt=path/to/ca.crt
```

### values.yaml Best Practices

```yaml
# Group by concern with comments explaining non-obvious choices
replicaCount: 3

image:
  repository: registry.example.com/myapp
  tag: ""                            # Overridden per-environment
  pullPolicy: IfNotPresent

resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi

autoscaling:
  enabled: false                     # Enable in production values
  minReplicas: 3
  maxReplicas: 20
  targetCPUUtilization: 70

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: ""                       # Required: set per-environment
      paths:
        - path: /
          pathType: Prefix
  tls: []                            # Set per-environment

# Feature flags
monitoring:
  enabled: true
  serviceMonitor:
    enabled: true
```

---

## Helmfile

Declarative management of multiple Helm releases.

### helmfile.yaml

```yaml
repositories:
  - name: bitnami
    url: https://charts.bitnami.com/bitnami
  - name: prometheus-community
    url: https://prometheus-community.github.io/helm-charts

environments:
  dev:
    values:
      - environments/dev.yaml
  staging:
    values:
      - environments/staging.yaml
  production:
    values:
      - environments/production.yaml

releases:
  - name: myapp
    namespace: "{{ .Environment.Name }}"
    chart: ./charts/myapp
    version: 1.0.0
    values:
      - charts/myapp/values.yaml
      - charts/myapp/values-{{ .Environment.Name }}.yaml
    set:
      - name: image.tag
        value: "{{ requiredEnv \"IMAGE_TAG\" }}"

  - name: postgresql
    namespace: "{{ .Environment.Name }}"
    chart: bitnami/postgresql
    version: 12.12.10
    values:
      - charts/postgresql/values-{{ .Environment.Name }}.yaml
    needs:                           # Dependency ordering
      - "{{ .Environment.Name }}/myapp"

  - name: prometheus
    namespace: monitoring
    chart: prometheus-community/kube-prometheus-stack
    version: 55.5.0
    values:
      - charts/monitoring/values.yaml
    installed: {{ eq .Environment.Name "production" }}  # Only in production
```

### Helmfile Commands

```bash
# Preview changes (diff against live)
helmfile -e production diff

# Apply changes
helmfile -e production apply

# Sync (force desired state)
helmfile -e production sync

# Destroy all releases
helmfile -e staging destroy

# Template (preview rendered manifests)
helmfile -e production template

# Lint all charts
helmfile -e production lint
```

---

## Chart Testing and Linting

```bash
# Lint chart for issues
helm lint ./charts/myapp
helm lint ./charts/myapp -f values-production.yaml

# Template rendering (catch template errors)
helm template myapp ./charts/myapp -f values-production.yaml --debug

# Dry run against cluster (validates against API server)
helm install myapp ./charts/myapp --dry-run -n production

# Chart Testing tool (ct) for CI
ct lint --charts ./charts/myapp
ct install --charts ./charts/myapp

# Validate rendered output with kubeval/kubeconform
helm template myapp ./charts/myapp | kubeconform -strict
```

### Helm Test Hooks

```yaml
# templates/tests/test-connection.yaml
apiVersion: v1
kind: Pod
metadata:
  name: "{{ include "myapp.fullname" . }}-test"
  annotations:
    "helm.sh/hook": test
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  containers:
    - name: test
      image: curlimages/curl
      command: ['curl', '--fail', 'http://{{ include "myapp.fullname" . }}:{{ .Values.service.port }}']
  restartPolicy: Never
```

```bash
# Run tests
helm test myapp -n production
```

---

## Common Patterns

### Conditional Resources

```yaml
{{- if .Values.autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
...
{{- end }}
```

### Hook Patterns

```yaml
metadata:
  annotations:
    "helm.sh/hook": pre-upgrade       # Run before upgrade
    "helm.sh/hook-weight": "-5"       # Order (lower runs first)
    "helm.sh/hook-delete-policy": before-hook-creation
```

Common hooks: `pre-install`, `post-install`, `pre-upgrade`, `post-upgrade`, `pre-delete`, `post-delete`, `test`.

### Subchart Dependencies

```bash
# Download dependencies defined in Chart.yaml
helm dependency update ./charts/myapp

# List current dependencies
helm dependency list ./charts/myapp
```

Access subchart values:
```yaml
# In parent values.yaml
postgresql:
  auth:
    postgresPassword: "secret"
    database: myapp
```
