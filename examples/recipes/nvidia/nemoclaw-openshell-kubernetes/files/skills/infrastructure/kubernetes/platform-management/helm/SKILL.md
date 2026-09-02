---
name: kubernetes-platform-helm
description: Helm package management, chart development, and release management
sasmp_version: "1.3.0"
eqhm_enabled: true
bonded_agent: 07-development-gitops
bond_type: PRIMARY_BOND
capabilities: ["Chart development", "Template syntax", "Values management", "Release lifecycle", "Repository management", "Dependencies", "Hooks", "Testing"]
input_schema:
  type: object
  properties:
    action:
      type: string
      enum: ["install", "upgrade", "rollback", "template", "lint", "test"]
    release_name:
      type: string
    chart:
      type: string
    values:
      type: object
output_schema:
  type: object
  properties:
    release_info:
      type: object
    revision:
      type: integer
    status:
      type: string
---

# Helm Package Management

## Executive Summary
Production-grade Helm chart development and management covering template syntax, values schema, release lifecycle, and CI/CD integration. This skill provides deep expertise in creating maintainable, reusable charts for enterprise Kubernetes deployments.

## Core Competencies

### 1. Chart Structure

**Production Chart Layout**
```
myapp/
├── Chart.yaml
├── Chart.lock
├── values.yaml
├── values.schema.json
├── README.md
├── templates/
│   ├── _helpers.tpl
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── hpa.yaml
│   ├── pdb.yaml
│   ├── serviceaccount.yaml
│   ├── servicemonitor.yaml
│   └── NOTES.txt
├── charts/
└── tests/
    └── test-connection.yaml
```

**Chart.yaml**
```yaml
apiVersion: v2
name: kubernetes-platform-helm
description: Production API Server
type: application
version: 1.2.0
appVersion: "2.1.0"
keywords:
- api
- backend
maintainers:
- name: Platform Team
  email: platform@example.com
dependencies:
- name: redis
  version: "18.x.x"
  repository: https://charts.bitnami.com/bitnami
  condition: redis.enabled
```

### 2. Template Best Practices

**_helpers.tpl**
```yaml
{{- define "myapp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "myapp.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "myapp.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "myapp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Values.image.tag | default .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "myapp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "myapp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
```

**deployment.yaml**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    {{- include "myapp.labels" . | nindent 4 }}
spec:
  {{- if not .Values.autoscaling.enabled }}
  replicas: {{ .Values.replicaCount }}
  {{- end }}
  selector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
      labels:
        {{- include "myapp.selectorLabels" . | nindent 8 }}
    spec:
      serviceAccountName: {{ include "myapp.fullname" . }}
      securityContext:
        {{- toYaml .Values.podSecurityContext | nindent 8 }}
      containers:
      - name: {{ .Chart.Name }}
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
        imagePullPolicy: {{ .Values.image.pullPolicy }}
        ports:
        - name: http
          containerPort: {{ .Values.service.targetPort }}
        {{- with .Values.resources }}
        resources:
          {{- toYaml . | nindent 12 }}
        {{- end }}
        {{- if .Values.probes.liveness.enabled }}
        livenessProbe:
          httpGet:
            path: {{ .Values.probes.liveness.path }}
            port: http
          initialDelaySeconds: {{ .Values.probes.liveness.initialDelaySeconds }}
        {{- end }}
```

### 3. Values Schema

**values.schema.json**
```json
{
  "$schema": "https://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["image", "replicaCount"],
  "properties": {
    "replicaCount": {
      "type": "integer",
      "minimum": 1,
      "description": "Number of replicas"
    },
    "image": {
      "type": "object",
      "required": ["repository"],
      "properties": {
        "repository": {
          "type": "string"
        },
        "tag": {
          "type": "string"
        },
        "pullPolicy": {
          "type": "string",
          "enum": ["Always", "IfNotPresent", "Never"]
        }
      }
    },
    "resources": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "object"
        },
        "limits": {
          "type": "object"
        }
      }
    }
  }
}
```

### 4. Release Management

**Common Operations**
```bash
# Install with values
helm install myapp ./myapp \
  -n production \
  -f values-prod.yaml \
  --set image.tag=v2.1.0

# Upgrade
helm upgrade myapp ./myapp \
  -n production \
  -f values-prod.yaml \
  --atomic \
  --timeout 5m

# Rollback
helm rollback myapp 2 -n production

# History
helm history myapp -n production

# Diff (with helm-diff plugin)
helm diff upgrade myapp ./myapp -n production -f values-prod.yaml
```

### 5. Hooks

**Pre-upgrade Migration**
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "myapp.fullname" . }}-migrate
  annotations:
    "helm.sh/hook": pre-upgrade
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": hook-succeeded
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: migrate
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
        command: ["./migrate.sh"]
```

## Integration Patterns

### Uses skill: **gitops**
- Chart versioning
- ArgoCD integration

### Coordinates with skill: **deployments**
- Release strategies
- Rollback management

### Works with skill: **monitoring**
- ServiceMonitor templates
- Metrics configuration

## Troubleshooting Guide

### Decision Tree: Helm Issues

```
Helm Problem?
│
├── Template error
│   ├── helm template . --debug
│   ├── Check indentation
│   └── Verify values exist
│
├── Upgrade failed
│   ├── Check hook failures
│   ├── Verify resources
│   └── Use --atomic
│
└── Release stuck
    ├── helm rollback
    ├── Check pending hooks
    └── Delete stuck resources
```

### Debug Commands

```bash
# Debug template
helm template myapp . --debug 2>&1 | head -100

# Dry run
helm upgrade myapp . --dry-run --debug

# Get values
helm get values myapp -n production
helm get manifest myapp -n production

# Lint
helm lint .
```

## Common Challenges & Solutions

| Challenge | Solution |
|-----------|----------|
| Complex values | Use schema validation |
| Template errors | Use --debug flag |
| Upgrade failures | Use --atomic |
| Version conflicts | Lock dependencies |

## Success Criteria

| Metric | Target |
|--------|--------|
| Lint passing | 100% |
| Schema validation | All charts |
| Test coverage | Core functionality |
| Documentation | README complete |

## Resources
- [Helm Documentation](https://helm.sh/docs/)
- [Chart Best Practices](https://helm.sh/docs/chart_best_practices/)
- [Helm Template Functions](https://helm.sh/docs/chart_template_guide/function_list/)
