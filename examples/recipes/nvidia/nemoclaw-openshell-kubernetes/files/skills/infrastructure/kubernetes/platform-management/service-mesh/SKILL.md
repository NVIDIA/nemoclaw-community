---
name: kubernetes-platform-service-mesh
description: Service mesh implementation with Istio, Linkerd for traffic management
sasmp_version: "1.3.0"
eqhm_enabled: true
bonded_agent: 08-service-mesh-expert
bond_type: PRIMARY_BOND
capabilities: ["Istio configuration", "Linkerd setup", "Traffic management", "mTLS", "Circuit breaking", "Canary deployments", "Observability", "Authorization policies"]
input_schema:
  type: object
  properties:
    action:
      type: string
      enum: ["configure", "route", "secure", "observe", "debug"]
    mesh:
      type: string
      enum: ["istio", "linkerd"]
    traffic_policy:
      type: string
output_schema:
  type: object
  properties:
    mesh_status:
      type: string
    traffic_flow:
      type: object
    metrics:
      type: array
---

# Service Mesh

## Executive Summary
Production-grade service mesh implementation covering Istio and Linkerd for traffic management, security, and observability. This skill provides deep expertise in implementing zero-trust networking, progressive delivery, and distributed system resilience.

## Core Competencies

### 1. Istio Configuration

**Installation**
```bash
# Install Istio with production profile
istioctl install --set profile=default \
  --set meshConfig.enableAutoMtls=true \
  --set meshConfig.accessLogFile=/dev/stdout

# Enable namespace injection
kubectl label namespace production istio-injection=enabled
```

**Traffic Management**
```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: api-server
spec:
  hosts:
  - api-server
  http:
  - match:
    - headers:
        x-canary:
          exact: "true"
    route:
    - destination:
        host: api-server
        subset: canary
  - route:
    - destination:
        host: api-server
        subset: stable
      weight: 90
    - destination:
        host: api-server
        subset: canary
      weight: 10
---
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: api-server
spec:
  host: api-server
  trafficPolicy:
    connectionPool:
      tcp:
        maxConnections: 100
      http:
        h2UpgradePolicy: UPGRADE
        http1MaxPendingRequests: 100
    outlierDetection:
      consecutive5xxErrors: 5
      interval: 30s
      baseEjectionTime: 30s
      maxEjectionPercent: 50
  subsets:
  - name: stable
    labels:
      version: v1
  - name: canary
    labels:
      version: v2
```

### 2. mTLS & Security

**Strict mTLS**
```yaml
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: production
spec:
  mtls:
    mode: STRICT
---
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: api-server-authz
  namespace: production
spec:
  selector:
    matchLabels:
      app: api-server
  action: ALLOW
  rules:
  - from:
    - source:
        principals: ["cluster.local/ns/production/sa/frontend"]
    to:
    - operation:
        methods: ["GET", "POST"]
        paths: ["/api/*"]
```

### 3. Circuit Breaking & Resilience

**Resilience Configuration**
```yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: api-server-resilience
spec:
  host: api-server
  trafficPolicy:
    connectionPool:
      tcp:
        maxConnections: 100
        connectTimeout: 5s
      http:
        http1MaxPendingRequests: 100
        http2MaxRequests: 1000
        maxRequestsPerConnection: 100
        maxRetries: 3
    outlierDetection:
      consecutive5xxErrors: 5
      interval: 10s
      baseEjectionTime: 30s
      maxEjectionPercent: 50
      minHealthPercent: 30
---
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: api-server-retry
spec:
  hosts:
  - api-server
  http:
  - route:
    - destination:
        host: api-server
    timeout: 10s
    retries:
      attempts: 3
      perTryTimeout: 3s
      retryOn: 5xx,reset,connect-failure
```

### 4. Linkerd

**Installation**
```bash
# Install Linkerd
linkerd install --crds | kubectl apply -f -
linkerd install | kubectl apply -f -

# Enable namespace
kubectl annotate namespace production linkerd.io/inject=enabled
```

**Service Profile**
```yaml
apiVersion: linkerd.io/v1alpha2
kind: ServiceProfile
metadata:
  name: api-server.production.svc.cluster.local
  namespace: production
spec:
  routes:
  - name: GET /api/users
    condition:
      method: GET
      pathRegex: /api/users/.*
    responseClasses:
    - condition:
        status:
          min: 500
          max: 599
      isFailure: true
    timeout: 5s
    retries:
      maxRetries: 3
      budget:
        retryratio: 0.2
        minRetriesPerSecond: 10
        ttl: 10s
```

### 5. Observability

**Kiali Dashboard**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: kiali
  namespace: istio-system
data:
  config.yaml: |
    auth:
      strategy: anonymous
    server:
      port: 20001
    external_services:
      prometheus:
        url: http://prometheus:9090
      grafana:
        url: http://grafana:3000
      jaeger:
        url: http://jaeger:16686
```

**Distributed Tracing**
```yaml
apiVersion: telemetry.istio.io/v1alpha1
kind: Telemetry
metadata:
  name: tracing
  namespace: istio-system
spec:
  tracing:
  - providers:
    - name: jaeger
    randomSamplingPercentage: 10
```

## Integration Patterns

### Uses skill: **storage-networking**
- Network policies
- Ingress configuration

### Coordinates with skill: **deployments**
- Canary rollouts
- Traffic shifting

### Works with skill: **monitoring**
- Mesh metrics
- Distributed tracing

## Troubleshooting Guide

### Decision Tree: Mesh Issues

```
Service Mesh Issue?
│
├── Traffic not routing
│   ├── Check VirtualService
│   ├── Verify sidecar injection
│   └── Check DestinationRule subsets
│
├── mTLS errors
│   ├── Check PeerAuthentication
│   ├── Verify certificates
│   └── Check service accounts
│
└── High latency
    ├── Check circuit breaker
    ├── Review timeout settings
    └── Check sidecar resources
```

### Debug Commands

```bash
# Istio debugging
istioctl analyze
istioctl proxy-status
istioctl proxy-config routes <pod>

# Check mTLS
istioctl authn tls-check <pod>

# Linkerd debugging
linkerd check
linkerd viz stat deploy
linkerd viz tap deploy/api-server
```

## Common Challenges & Solutions

| Challenge | Solution |
|-----------|----------|
| Sidecar injection | Check namespace labels |
| mTLS failures | Verify PeerAuthentication |
| Routing errors | Check VirtualService |
| Performance | Tune sidecar resources |

## Success Criteria

| Metric | Target |
|--------|--------|
| mTLS coverage | 100% |
| Request success | >99.9% |
| P99 overhead | <5ms |
| Tracing coverage | >90% |

## Resources
- [Istio Documentation](https://istio.io/latest/docs/)
- [Linkerd Documentation](https://linkerd.io/docs/)
