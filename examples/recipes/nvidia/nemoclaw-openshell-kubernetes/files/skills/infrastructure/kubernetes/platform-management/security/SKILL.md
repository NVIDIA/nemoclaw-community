---
name: kubernetes-platform-security
description: Master Kubernetes security, RBAC, network policies, pod security, and compliance. Learn to secure clusters and enforce access control.
sasmp_version: "1.3.0"
eqhm_enabled: true
bonded_agent: 05-security-rbac
bond_type: PRIMARY_BOND
capabilities: ["RBAC design", "Pod Security Standards", "Network policies", "Secret management", "Policy enforcement", "Audit logging", "Supply chain security", "Compliance frameworks"]
input_schema:
  type: object
  properties:
    action:
      type: string
      enum: ["audit", "configure", "enforce", "scan", "remediate"]
    scope:
      type: string
      enum: ["rbac", "pss", "network", "secrets", "policy"]
output_schema:
  type: object
  properties:
    compliance_status:
      type: string
    findings:
      type: array
    recommendations:
      type: array
---

# Kubernetes Security

## Executive Summary
Production-grade Kubernetes security covering defense-in-depth strategies from authentication to runtime protection. This skill provides deep expertise in implementing zero-trust security models, compliance frameworks, and production-hardened configurations for SOC2, PCI-DSS, and HIPAA requirements.

## Core Competencies

### 1. RBAC Architecture

**RBAC Hierarchy**
```
User / ServiceAccount / Group
           ↓
    RoleBinding / ClusterRoleBinding
           ↓
    Role / ClusterRole
           ↓
    Rules (apiGroups, resources, verbs)
```

**Production RBAC**
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: api-server
  namespace: production
automountServiceAccountToken: false
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: api-server-role
  namespace: production
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get", "list", "watch"]
  resourceNames: ["api-config"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get"]
  resourceNames: ["api-secrets"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: api-server-binding
  namespace: production
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: api-server-role
subjects:
- kind: ServiceAccount
  name: api-server
  namespace: production
```

### 2. Pod Security Standards

**Restricted Security Context**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secure-app
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 10000
    runAsGroup: 10000
    fsGroup: 10000
    seccompProfile:
      type: RuntimeDefault
  containers:
  - name: app
    image: myregistry.io/app:v1.0.0@sha256:abc123
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop: ["ALL"]
    volumeMounts:
    - name: tmp
      mountPath: /tmp
  volumes:
  - name: tmp
    emptyDir: {}
```

**Namespace Enforcement**
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/warn: baseline
    pod-security.kubernetes.io/audit: restricted
```

### 3. Policy Enforcement

**Kyverno Policy**
```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-run-as-nonroot
spec:
  validationFailureAction: Enforce
  rules:
  - name: run-as-non-root
    match:
      any:
      - resources:
          kinds:
          - Pod
    validate:
      message: "Containers must run as non-root"
      pattern:
        spec:
          containers:
          - securityContext:
              runAsNonRoot: true
```

**OPA Gatekeeper**
```yaml
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8srequiredlabels
spec:
  crd:
    spec:
      names:
        kind: K8sRequiredLabels
  targets:
  - target: admission.k8s.gatekeeper.sh
    rego: |
      package k8srequiredlabels
      violation[{"msg": msg}] {
        provided := {l | input.review.object.metadata.labels[l]}
        required := {l | l := input.parameters.labels[_]}
        missing := required - provided
        count(missing) > 0
        msg := sprintf("Missing labels: %v", [missing])
      }
```

### 4. Secret Management

**External Secrets Operator**
```yaml
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: aws-secrets-manager
spec:
  provider:
    aws:
      service: SecretsManager
      region: us-east-1
      auth:
        jwt:
          serviceAccountRef:
            name: external-secrets-sa
            namespace: external-secrets
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: database-credentials
  namespace: production
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: db-credentials
  data:
  - secretKey: password
    remoteRef:
      key: production/database
      property: password
```

### 5. Supply Chain Security

**Image Signing with Cosign**
```bash
# Sign image
cosign sign --yes \
  --oidc-issuer=https://token.actions.githubusercontent.com \
  myregistry.io/app:v1.0.0

# Verify in admission
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signature
spec:
  validationFailureAction: Enforce
  rules:
  - name: verify-signature
    match:
      resources:
        kinds:
        - Pod
    verifyImages:
    - imageReferences:
      - "myregistry.io/*"
      attestors:
      - entries:
        - keyless:
            issuer: "https://token.actions.githubusercontent.com"
```

## Integration Patterns

### Uses skill: **cluster-admin**
- Audit logging configuration
- Node security hardening

### Coordinates with skill: **storage-networking**
- Network policy enforcement
- Secret encryption

### Works with skill: **monitoring**
- Security event alerting
- Compliance dashboards

## Troubleshooting Guide

### Decision Tree: Access Issues

```
Access Denied?
│
├── RBAC issue
│   ├── kubectl auth can-i <verb> <resource> --as=<user>
│   ├── Check RoleBindings
│   └── Verify subject matches
│
├── PSS violation
│   ├── Check namespace labels
│   └── Fix securityContext
│
└── Policy blocked
    ├── Check Kyverno/Gatekeeper logs
    └── Review policy rules
```

### Debug Commands

```bash
# RBAC debugging
kubectl auth can-i --list --as=system:serviceaccount:prod:myapp
kubectl get rolebindings,clusterrolebindings -A -o wide

# PSS testing
kubectl label ns test pod-security.kubernetes.io/enforce=restricted --dry-run=server

# Policy status
kubectl get constraints -A
kubectl get clusterpolicies
```

## Common Challenges & Solutions

| Challenge | Solution |
|-----------|----------|
| RBAC sprawl | Regular audits, automation |
| Secret rotation | External Secrets Operator |
| Policy exceptions | Document, time-limit |
| Compliance gaps | CIS Benchmark scanning |

## Success Criteria

| Metric | Target |
|--------|--------|
| RBAC least privilege | 100% |
| PSS restricted | All prod namespaces |
| Network policy coverage | 100% |
| Image signing | 100% production |

## Resources
- [RBAC Authorization](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
- [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
- [Kyverno](https://kyverno.io/)
