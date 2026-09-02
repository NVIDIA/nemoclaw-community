# Kubernetes Security Reference

Hardening patterns for RBAC, Pod Security Standards, network policies, and secrets management.

---

## Table of Contents

1. [RBAC](#rbac)
2. [Pod Security Standards](#pod-security-standards)
3. [Network Policies](#network-policies)
4. [Secrets Management](#secrets-management)

---

## RBAC

Role-Based Access Control governs who can do what in the cluster. Follow the principle of least privilege.

### Core Concepts

| Resource | Scope | Purpose |
|----------|-------|---------|
| Role | Namespace | Define permissions within a namespace |
| ClusterRole | Cluster | Define permissions cluster-wide |
| RoleBinding | Namespace | Bind a Role/ClusterRole to users in a namespace |
| ClusterRoleBinding | Cluster | Bind a ClusterRole to users cluster-wide |
| ServiceAccount | Namespace | Identity for pods (not humans) |

### Pattern: Read-Only Namespace Access

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: namespace-viewer
  namespace: production
rules:
  - apiGroups: [""]
    resources: ["pods", "services", "configmaps", "events"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets", "statefulsets"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: viewer-binding
  namespace: production
subjects:
  - kind: Group
    name: developers
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: namespace-viewer
  apiGroup: rbac.authorization.k8s.io
```

### Pattern: Deployment Operator

Can manage deployments and their dependent resources but cannot modify RBAC or secrets.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: deployment-operator
  namespace: production
rules:
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  - apiGroups: [""]
    resources: ["pods", "pods/log", "services", "configmaps"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["pods/exec"]
    verbs: ["create"]               # Allow exec for debugging
  - apiGroups: ["autoscaling"]
    resources: ["horizontalpodautoscalers"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
```

### Pattern: CI/CD Service Account (Minimal)

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ci-deployer
  namespace: production
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ci-deploy-role
  namespace: production
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "patch"]  # Only patch — cannot create/delete
    resourceNames: ["myapp"]         # Only specific deployment
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]  # Read-only for monitoring rollout
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ci-deploy-binding
  namespace: production
subjects:
  - kind: ServiceAccount
    name: ci-deployer
    namespace: production
roleRef:
  kind: Role
  name: ci-deploy-role
  apiGroup: rbac.authorization.k8s.io
```

### Pattern: Namespace Admin

Full control within a namespace but no cluster-level access.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: namespace-admin
  namespace: production
subjects:
  - kind: Group
    name: platform-team
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: admin                        # Built-in ClusterRole
  apiGroup: rbac.authorization.k8s.io
```

### RBAC Audit Commands

```bash
# Check what a user/SA can do
kubectl auth can-i --list --as=system:serviceaccount:production:ci-deployer -n production

# Check a specific permission
kubectl auth can-i create deployments -n production --as=system:serviceaccount:production:ci-deployer

# List all role bindings in a namespace
kubectl get rolebindings -n production -o wide

# List all cluster role bindings
kubectl get clusterrolebindings -o wide | grep -v "system:"
```

---

## Pod Security Standards

Three built-in security profiles enforced via Pod Security Admission (PSA).

### Levels

| Level | Use Case | Key Restrictions |
|-------|----------|-----------------|
| **Privileged** | System/infra components | No restrictions |
| **Baseline** | Standard workloads | Blocks known privilege escalations |
| **Restricted** | Security-critical (production default) | Non-root, read-only rootfs, drop all caps |

### Enforcement via Namespace Labels

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    # Enforce restricted — reject non-compliant pods
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest

    # Warn on baseline violations — log but allow
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/warn-version: latest

    # Audit for logging
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: latest
```

### Restricted-Compliant Pod Template

This security context satisfies the `restricted` Pod Security Standard:

```yaml
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: app
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
      volumeMounts:
        - name: tmp
          mountPath: /tmp            # Writable dir when rootfs is read-only
  volumes:
    - name: tmp
      emptyDir: {}
```

### Exempt System Workloads

For DaemonSets and system components that need elevated permissions, use a separate namespace with `privileged` or `baseline` enforcement:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: kube-system
  labels:
    pod-security.kubernetes.io/enforce: privileged
```

---

## Network Policies

By default, Kubernetes allows all pod-to-pod communication. Network policies restrict traffic to only what is explicitly needed.

**Prerequisite:** A CNI plugin that supports NetworkPolicy (Calico, Cilium, Weave Net). Standard kubenet does not enforce policies.

### Strategy: Default Deny + Selective Allow

**Step 1: Deny all traffic in the namespace**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: production
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
```

**Step 2: Allow DNS (required for service discovery)**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: production
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    - ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

**Step 3: Allow application-specific traffic**

```yaml
# Allow frontend to reach backend
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: frontend
      ports:
        - protocol: TCP
          port: 8080
```

### Cross-Namespace Communication

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-monitoring-scrape
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: myapp
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: monitoring        # Allow from monitoring namespace
          podSelector:
            matchLabels:
              app: prometheus
      ports:
        - protocol: TCP
          port: 9090
```

### Allow External Egress (specific endpoints)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-external-api
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: myapp
  policyTypes:
    - Egress
  egress:
    - to:
        - ipBlock:
            cidr: 203.0.113.0/24     # External API IP range
      ports:
        - protocol: TCP
          port: 443
```

---

## Secrets Management

### Built-in Secrets — Limitations

Kubernetes Secrets are base64-encoded, **not encrypted** by default. They are stored in etcd in plaintext unless you enable encryption at rest.

**Minimum safeguards:**
- Enable etcd encryption at rest
- Restrict Secret access with RBAC
- Never commit Secrets to Git
- Prefer volume mounts over env vars (env vars show in `kubectl describe pod`)

### External Secrets Operator

Syncs secrets from external providers (AWS Secrets Manager, HashiCorp Vault, Azure Key Vault, GCP Secret Manager) into Kubernetes Secrets.

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: myapp-secrets
  namespace: production
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: myapp-secrets              # K8s Secret name to create
    creationPolicy: Owner
  data:
    - secretKey: DATABASE_URL        # Key in K8s Secret
      remoteRef:
        key: production/myapp/db     # Key in AWS SM
        property: connection_string
    - secretKey: API_KEY
      remoteRef:
        key: production/myapp/api
        property: key
```

### Sealed Secrets (Bitnami)

Encrypt secrets for safe storage in Git. Only the cluster controller can decrypt.

```bash
# Install kubeseal CLI
# Encrypt a secret
kubectl create secret generic myapp-secrets \
  --from-literal=API_KEY=sk-xxx \
  --dry-run=client -o yaml | \
  kubeseal --format yaml > sealed-secret.yaml

# The sealed-secret.yaml is safe to commit to Git
kubectl apply -f sealed-secret.yaml
```

### Secret Rotation

- Use External Secrets Operator with `refreshInterval` for automatic rotation
- For manual rotation: update the Secret, then trigger a rollout restart:
  ```bash
  kubectl rollout restart deployment/myapp -n production
  ```
- For zero-downtime rotation: mount secrets as volumes (Kubernetes updates mounted volumes automatically without pod restart, though the app must re-read the file)
