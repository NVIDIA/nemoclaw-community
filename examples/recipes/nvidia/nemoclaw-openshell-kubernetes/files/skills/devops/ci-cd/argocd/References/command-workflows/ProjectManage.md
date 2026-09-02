# ProjectManage Workflow

Manage ArgoCD Projects - create, configure destinations, sources, and RBAC.

## Quick Commands

| Action | Command |
|--------|---------|
| List projects | `argocd proj list` |
| Get project | `argocd proj get <name>` |
| Create project | `argocd proj create <name>` |
| Delete project | `argocd proj delete <name>` |

## List Projects

```bash
# List all projects
argocd proj list

# List with specific output
argocd proj list -o wide
argocd proj list -o json
argocd proj list -o yaml
```

## Get Project Details

```bash
# Get project details
argocd proj get <project-name>

# Get as JSON
argocd proj get <project-name> -o json

# Get as YAML
argocd proj get <project-name> -o yaml

# Example
argocd proj get default
```

## Create Project

### Basic Project

```bash
# Create project with description
argocd proj create <project-name> --description "Project description"

# Create with destination
argocd proj create <project-name> \
  --dest https://kubernetes.default.svc,namespace1 \
  --dest https://kubernetes.default.svc,namespace2

# Create with source repository
argocd proj create <project-name> \
  --src https://github.com/org/repo.git
```

### Full Project Setup

```bash
# Create project
argocd proj create platform-team --description "Platform team applications"

# Add source repositories
argocd proj add-source platform-team https://github.com/org/platform-apps.git
argocd proj add-source platform-team https://charts.bitnami.com/bitnami

# Add destinations
argocd proj add-destination platform-team https://kubernetes.default.svc monitoring
argocd proj add-destination platform-team https://kubernetes.default.svc logging
argocd proj add-destination platform-team '*' '*'  # Allow all

# Allow cluster resources
argocd proj allow-cluster-resource platform-team '*' '*'

# Allow namespace resources
argocd proj allow-namespace-resource platform-team '*' '*'
```

## Edit Project

```bash
# Edit project interactively
argocd proj edit <project-name>

# Set project parameters
argocd proj set <project-name> --description "New description"
```

## Delete Project

```bash
# Delete project
argocd proj delete <project-name>
```

## Source Management

```bash
# Add source repository
argocd proj add-source <project-name> <repo-url>

# Remove source repository
argocd proj remove-source <project-name> <repo-url>

# Add source namespace (allow apps to deploy from namespace)
argocd proj add-source-namespace <project-name> <namespace>

# Remove source namespace
argocd proj remove-source-namespace <project-name> <namespace>

# Examples
argocd proj add-source platform-team https://github.com/org/repo.git
argocd proj add-source platform-team https://charts.grafana.io
```

## Destination Management

```bash
# Add destination (cluster + namespace)
argocd proj add-destination <project-name> <cluster-server> <namespace>

# Remove destination
argocd proj remove-destination <project-name> <cluster-server> <namespace>

# Add destination service account
argocd proj add-destination-service-account <project-name> <cluster-server> <namespace> <service-account>

# Remove destination service account
argocd proj remove-destination-service-account <project-name> <cluster-server> <namespace> <service-account>

# Examples
argocd proj add-destination platform-team https://kubernetes.default.svc monitoring
argocd proj add-destination platform-team '*' '*'  # All clusters, all namespaces
argocd proj add-destination platform-team 'https://example-app-dev.example.com' 'app-*'  # Wildcard namespace
```

## Resource Permissions

### Cluster-Scoped Resources

```bash
# Allow cluster resource
argocd proj allow-cluster-resource <project-name> <group> <kind>

# Deny cluster resource
argocd proj deny-cluster-resource <project-name> <group> <kind>

# Examples
argocd proj allow-cluster-resource platform-team '*' '*'  # Allow all
argocd proj allow-cluster-resource platform-team '' Namespace
argocd proj allow-cluster-resource platform-team rbac.authorization.k8s.io ClusterRole
argocd proj deny-cluster-resource platform-team '' Secret
```

### Namespace-Scoped Resources

```bash
# Allow namespace resource
argocd proj allow-namespace-resource <project-name> <group> <kind>

# Deny namespace resource
argocd proj deny-namespace-resource <project-name> <group> <kind>

# Examples
argocd proj allow-namespace-resource platform-team '*' '*'  # Allow all
argocd proj deny-namespace-resource platform-team '' Secret
```

## Sync Windows

Control when applications can sync.

```bash
# Add sync window (allow/deny)
argocd proj windows add <project-name> \
  --kind allow \
  --schedule "0 22 * * *" \
  --duration 1h \
  --applications "*"

# List sync windows
argocd proj windows list <project-name>

# Delete sync window
argocd proj windows delete <project-name> <window-id>

# Examples - Maintenance window
argocd proj windows add platform-team \
  --kind deny \
  --schedule "0 9 * * 1-5" \
  --duration 8h \
  --applications "*" \
  --namespaces "production"
```

## Role Management

### List Roles

```bash
argocd proj role list <project-name>
```

### Create Role

```bash
# Create role
argocd proj role create <project-name> <role-name>

# Add policy to role
argocd proj role add-policy <project-name> <role-name> \
  --action get \
  --permission allow \
  --object "*"

# Add group to role
argocd proj role add-group <project-name> <role-name> <group-name>

# Example: Read-only role
argocd proj role create platform-team viewer
argocd proj role add-policy platform-team viewer -a get -p allow -o "*"
argocd proj role add-group platform-team viewer "platform-viewers"
```

### Delete Role

```bash
argocd proj role delete <project-name> <role-name>
```

### Generate Role Token

```bash
# Generate JWT token for role
argocd proj role create-token <project-name> <role-name>

# With expiration
argocd proj role create-token <project-name> <role-name> --expires-in 24h
```

## Orphaned Resources

```bash
# Add orphaned resource ignore
argocd proj add-orphaned-ignore <project-name> <group> <kind> --name <resource-name>

# Remove orphaned resource ignore
argocd proj remove-orphaned-ignore <project-name> <group> <kind> --name <resource-name>

# Example: Ignore ConfigMaps created by operators
argocd proj add-orphaned-ignore platform-team "" ConfigMap --name "kube-root-ca.crt"
```

## Signature Keys (GPG)

```bash
# Add signature key
argocd proj add-signature-key <project-name> <key-id>

# Remove signature key
argocd proj remove-signature-key <project-name> <key-id>
```

## Project YAML Example

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: platform-team
  namespace: argocd
spec:
  description: Platform team applications

  # Source repositories
  sourceRepos:
    - https://github.com/org/platform-apps.git
    - https://charts.grafana.io
    - '*'  # Allow all (not recommended for production)

  # Destination clusters and namespaces
  destinations:
    - server: https://kubernetes.default.svc
      namespace: monitoring
    - server: https://kubernetes.default.svc
      namespace: logging
    - server: '*'
      namespace: '*'

  # Cluster-scoped resources
  clusterResourceWhitelist:
    - group: ''
      kind: Namespace
    - group: rbac.authorization.k8s.io
      kind: ClusterRole
    - group: rbac.authorization.k8s.io
      kind: ClusterRoleBinding

  # Namespace-scoped resources
  namespaceResourceBlacklist:
    - group: ''
      kind: ResourceQuota
    - group: ''
      kind: LimitRange

  # Roles
  roles:
    - name: admin
      description: Admin role
      policies:
        - p, proj:platform-team:admin, applications, *, platform-team/*, allow
      groups:
        - platform-admins
    - name: viewer
      description: Read-only access
      policies:
        - p, proj:platform-team:viewer, applications, get, platform-team/*, allow
      groups:
        - platform-viewers

  # Sync windows
  syncWindows:
    - kind: deny
      schedule: '0 9 * * 1-5'
      duration: 8h
      applications:
        - '*'
      namespaces:
        - production
```

## Troubleshooting

```bash
# Check project exists
argocd proj get <project-name>

# Validate application against project
argocd app create --validate-only ...

# Check RBAC policies
argocd admin settings rbac validate --policy <policy-file>
```
