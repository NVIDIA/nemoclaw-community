---
name: kubernetes-platform-storage-networking
description: Master Kubernetes storage management and networking architecture. Learn persistent storage, network policies, service discovery, and ingress routing.
sasmp_version: "1.3.0"
eqhm_enabled: true
bonded_agent: 04-storage-networking
bond_type: PRIMARY_BOND
capabilities: ["PersistentVolume management", "StorageClass configuration", "CSI drivers", "Network policies", "Service mesh integration", "Ingress controllers", "Gateway API", "CNI plugins"]
input_schema:
  type: object
  properties:
    action:
      type: string
      enum: ["provision", "resize", "snapshot", "route", "policy"]
    resource_type:
      type: string
      enum: ["PV", "PVC", "StorageClass", "Service", "Ingress", "NetworkPolicy"]
output_schema:
  type: object
  properties:
    status:
      type: string
    configuration:
      type: object
---

# Storage & Networking

## Executive Summary
Production-grade Kubernetes storage and networking covering persistent storage patterns, CSI driver configuration, CNI plugins, service discovery, and ingress routing. This skill provides deep expertise in building reliable, high-performance data and network infrastructure.

## Core Competencies

### 1. Storage Architecture

**Storage Stack**
```
┌─────────────────────────────────────────────────┐
│                APPLICATION POD                   │
│            Volume Mount: /data                  │
└─────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│          PERSISTENT VOLUME CLAIM (PVC)          │
│         Namespace-scoped storage request        │
└─────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│          PERSISTENT VOLUME (PV)                 │
│            Cluster-wide resource                │
└─────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│              CSI DRIVER                         │
│    aws-ebs-csi, csi-driver-nfs, etc.           │
└─────────────────────────────────────────────────┘
```

**Production StorageClass**
```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  iops: "5000"
  throughput: "250"
  encrypted: "true"
reclaimPolicy: Retain
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer
---
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: shared-efs
provisioner: efs.csi.aws.com
parameters:
  provisioningMode: efs-ap
  fileSystemId: fs-abc123
reclaimPolicy: Retain
```

**VolumeSnapshot for Backup**
```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: ebs-snapclass
driver: ebs.csi.aws.com
deletionPolicy: Retain
---
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: db-backup
spec:
  volumeSnapshotClassName: ebs-snapclass
  source:
    persistentVolumeClaimName: postgresql-data-0
```

### 2. Networking Architecture

**Network Stack**
```
┌─────────────────────────────────────────────────┐
│              EXTERNAL TRAFFIC                    │
└─────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│         LOAD BALANCER (ALB/NLB)                 │
└─────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│     INGRESS CONTROLLER / GATEWAY API            │
│         TLS termination, routing                │
└─────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│           KUBERNETES SERVICE                     │
│      ClusterIP, NodePort, LoadBalancer          │
└─────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│              CNI PLUGIN                          │
│     Cilium, Calico, AWS VPC CNI                 │
└─────────────────────────────────────────────────┘
```

**Service Configuration**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: api-server
  namespace: production
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: api-server
  ports:
  - name: http
    port: 80
    targetPort: 8080
  - name: grpc
    port: 9090
    targetPort: 9090
```

### 3. Ingress & Gateway API

**Production Ingress**
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: api-ingress
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/limit-rps: "100"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - api.example.com
    secretName: api-tls
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /v1
        pathType: Prefix
        backend:
          service:
            name: api-v1
            port:
              number: 80
```

**Gateway API**
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: production-gateway
spec:
  gatewayClassName: istio
  listeners:
  - name: https
    hostname: "*.example.com"
    port: 443
    protocol: HTTPS
    tls:
      mode: Terminate
      certificateRefs:
      - name: wildcard-tls
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-routes
spec:
  parentRefs:
  - name: production-gateway
  hostnames:
  - "api.example.com"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /api/v1
    backendRefs:
    - name: api-v1
      port: 80
      weight: 90
    - name: api-v1-canary
      port: 80
      weight: 10
```

### 4. Network Policies

**Zero-Trust Architecture**
```yaml
# Default deny all
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
---
# Allow DNS
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
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
---
# API server policy
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-server-policy
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: api-server
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-nginx
    ports:
    - protocol: TCP
      port: 8080
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: postgresql
    ports:
    - protocol: TCP
      port: 5432
```

### 5. CNI Comparison

```
┌─────────────┬─────────────┬─────────────┬─────────────┐
│ Feature     │ Cilium      │ Calico      │ AWS VPC CNI │
├─────────────┼─────────────┼─────────────┼─────────────┤
│ Performance │ Excellent   │ Very Good   │ Excellent   │
│ L7 Policy   │ ✓ (native)  │ Via Envoy   │ ✗           │
│ eBPF        │ ✓           │ ✓ (option)  │ ✗           │
│ Encryption  │ WireGuard   │ WireGuard   │ VPC native  │
│ Observ.     │ Hubble      │ Basic       │ CloudWatch  │
└─────────────┴─────────────┴─────────────┴─────────────┘
```

## Integration Patterns

### Uses skill: **cluster-admin**
- Node storage configuration
- CNI deployment

### Coordinates with skill: **security**
- Network policy enforcement
- mTLS configuration

### Works with skill: **monitoring**
- Network metrics
- Storage monitoring

## Troubleshooting Guide

### Decision Tree: Storage Issues

```
Storage Problem?
│
├── PVC Pending
│   ├── Check StorageClass exists
│   ├── Check provisioner running
│   └── WaitForFirstConsumer → Schedule pod
│
├── Pod can't mount
│   ├── Already attached → Force detach
│   ├── Permission denied → Check fsGroup
│   └── Filesystem error → Resize PVC
│
└── Performance issues
    ├── Check IOPS limits
    └── Use faster StorageClass
```

### Decision Tree: Network Issues

```
Network Problem?
│
├── Service not reachable
│   ├── No endpoints → Selector mismatch
│   ├── DNS not resolving → CoreDNS
│   └── Timeout → NetworkPolicy
│
├── Ingress not working
│   ├── 404 → Path mismatch
│   ├── 502 → Backend not ready
│   └── TLS error → Certificate
│
└── Pod-to-pod fails
    ├── Check NetworkPolicy
    └── Check CNI pods
```

### Debug Commands

```bash
# Storage
kubectl get pv,pvc -A
kubectl describe pvc <name>
kubectl get storageclass

# Network
kubectl get svc,endpoints,ingress -A
kubectl run debug --rm -it --image=nicolaka/netshoot -- nslookup <svc>
kubectl get networkpolicy -A
```

## Common Challenges & Solutions

| Challenge | Solution |
|-----------|----------|
| PVC Pending | Check StorageClass, provisioner |
| Volume timeout | Check node health, force detach |
| Ingress 502 | Check backend health |
| DNS failures | Verify CoreDNS, egress policy |

## Success Criteria

| Metric | Target |
|--------|--------|
| PVC provision time | <30s |
| Storage availability | 99.99% |
| Service latency | <10ms |
| Network policy coverage | 100% |

## Resources
- [Kubernetes Storage](https://kubernetes.io/docs/concepts/storage/)
- [Networking](https://kubernetes.io/docs/concepts/services-networking/)
- [Gateway API](https://gateway-api.sigs.k8s.io/)
