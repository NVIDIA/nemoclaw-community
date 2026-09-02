# OpenTelemetry Kubernetes Deployment Reference

## Helm Chart Installation

### Add Repository

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update
```

### Basic Installation

```bash
helm install otel-collector open-telemetry/opentelemetry-collector \
  --namespace monitoring \
  --create-namespace \
  --set mode=daemonset
```

### Installation with Values File

```bash
helm install otel-collector open-telemetry/opentelemetry-collector \
  --namespace monitoring \
  --create-namespace \
  -f values.yaml
```

## Deployment Modes

### DaemonSet Mode (Node-level Collection)

```yaml
mode: "daemonset"

# Required for host metrics
hostNetwork: false

# Mount host paths for log collection
presets:
  logsCollection:
    enabled: true
  hostMetrics:
    enabled: true
```

**Use DaemonSet when**:

- Collecting host-level metrics
- Collecting container logs from nodes
- Need data from every node in cluster

### Deployment Mode (Centralized Gateway)

```yaml
mode: "deployment"
replicaCount: 3

# Enable cluster-level metrics
presets:
  kubernetesEvents:
    enabled: true
  clusterMetrics:
    enabled: true

# Autoscaling
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70

# PodDisruptionBudget
podDisruptionBudget:
  enabled: true
  minAvailable: 1
```

**Use Deployment when**:

- Acting as a central gateway
- Need horizontal scaling
- Collecting cluster-wide metrics/events

### Sidecar Mode (Per-pod Collection)

```yaml
mode: "sidecar"
```

**Use Sidecar when**:

- Need per-application isolation
- Specific apps require custom processing

## Helm Values Reference

### Complete Production Values

```yaml
nameOverride: "otel-collector"
mode: "daemonset"
namespaceOverride: "monitoring"

# Presets
presets:
  logsCollection:
    enabled: true
    includeCollectorLogs: false
    storeCheckpoints: true
    maxRecombineLogSize: 102400
  hostMetrics:
    enabled: true
  kubernetesAttributes:
    enabled: true
    extractAllPodLabels: true
    extractAllPodAnnotations: false
  kubeletMetrics:
    enabled: true
  kubernetesEvents:
    enabled: false  # Enable in deployment mode
  clusterMetrics:
    enabled: false  # Enable in deployment mode

# Go Memory Management
useGOMEMLIMIT: true

# Resources
resources:
  limits:
    cpu: 500m
    memory: 1Gi
  requests:
    cpu: 100m
    memory: 256Mi

# Service Account
serviceAccount:
  create: true
  name: "otel-collector"

# ClusterRole
clusterRole:
  create: true
  rules:
    - apiGroups: [""]
      resources: ["pods", "namespaces", "nodes", "nodes/proxy", "services", "endpoints", "events"]
      verbs: ["get", "list", "watch"]
    - apiGroups: ["apps"]
      resources: ["replicasets", "deployments", "daemonsets", "statefulsets"]
      verbs: ["get", "list", "watch"]
    - apiGroups: ["batch"]
      resources: ["jobs", "cronjobs"]
      verbs: ["get", "list", "watch"]
    - nonResourceURLs: ["/metrics", "/metrics/cadvisor"]
      verbs: ["get"]

# Security Context
podSecurityContext:
  runAsNonRoot: true
  runAsUser: 10001
  fsGroup: 10001

securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - ALL
  readOnlyRootFilesystem: true

# Ports
ports:
  otlp:
    enabled: true
    containerPort: 4317
    servicePort: 4317
    hostPort: 4317
    protocol: TCP
    appProtocol: grpc
  otlp-http:
    enabled: true
    containerPort: 4318
    servicePort: 4318
    hostPort: 4318
    protocol: TCP
  metrics:
    enabled: true
    containerPort: 8888
    servicePort: 8888
    protocol: TCP

# Monitoring
serviceMonitor:
  enabled: true
  extraLabels:
    prometheus: kube-prometheus-stack
  metricsEndpoints:
    - port: metrics
      interval: 30s
      path: /metrics

podMonitor:
  enabled: true
  extraLabels:
    prometheus: kube-prometheus-stack

# Labels
podLabels:
  app.kubernetes.io/name: otel-collector
  app.kubernetes.io/component: telemetry
  app.kubernetes.io/part-of: observability-stack

podAnnotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "8888"
  prometheus.io/path: "/metrics"

# Anti-Affinity
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchExpressions:
              - key: app.kubernetes.io/name
                operator: In
                values:
                  - otel-collector
          topologyKey: kubernetes.io/hostname

# Probes
livenessProbe:
  httpGet:
    port: 13133
    path: /

readinessProbe:
  httpGet:
    port: 13133
    path: /
```

## Environment-Specific Overlays

### Development

```yaml
# Lower resources
resources:
  limits:
    cpu: 250m
    memory: 512Mi
  requests:
    cpu: 50m
    memory: 128Mi

# Spot instance tolerations (AKS)
tolerations:
  - key: kubernetes.azure.com/scalesetpriority
    operator: Equal
    value: "spot"
    effect: NoSchedule

# Debug enabled
config:
  service:
    telemetry:
      logs:
        level: debug
    pipelines:
      traces:
        exporters: [debug]
```

### Production

```yaml
# Higher resources
resources:
  limits:
    cpu: 1000m
    memory: 2Gi
  requests:
    cpu: 250m
    memory: 512Mi

# Autoscaling (deployment mode)
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80

# PDB
podDisruptionBudget:
  enabled: true
  minAvailable: 1

# Sampling
config:
  processors:
    probabilistic_sampler:
      sampling_percentage: 10
```

## ArgoCD ApplicationSet Example

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: otel
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - cluster: dev
            url: "https://dev-cluster:443"
          - cluster: prd
            url: "https://prd-cluster:443"
  template:
    metadata:
      name: "{{cluster}}-otel"
    spec:
      project: default
      sources:
        - chart: opentelemetry-collector
          repoURL: "https://open-telemetry.github.io/opentelemetry-helm-charts"
          targetRevision: "0.130.0"
          helm:
            valueFiles:
              - $values/otel/{{cluster}}/values.yaml
        - repoURL: "https://your-repo/helm-values"
          targetRevision: main
          ref: values
      destination:
        server: "{{url}}"
        namespace: monitoring
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
          - ServerSideApply=true
```

## RBAC Configuration

### ClusterRole for Full Kubernetes Access

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: otel-collector
rules:
  - apiGroups: [""]
    resources:
      - pods
      - namespaces
      - nodes
      - nodes/proxy
      - nodes/stats
      - services
      - endpoints
      - events
      - configmaps
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources:
      - replicasets
      - deployments
      - daemonsets
      - statefulsets
    verbs: ["get", "list", "watch"]
  - apiGroups: ["batch"]
    resources:
      - jobs
      - cronjobs
    verbs: ["get", "list", "watch"]
  - nonResourceURLs:
      - "/metrics"
      - "/metrics/cadvisor"
    verbs: ["get"]
```

## Network Policies

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: otel-collector
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: otel-collector
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector: {}
      ports:
        - port: 4317  # OTLP gRPC
        - port: 4318  # OTLP HTTP
        - port: 8888  # Metrics
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - port: 9090  # Prometheus
        - port: 3100  # Loki
        - port: 4317  # Tempo
```

## Verification Commands

```bash
# Check pods
kubectl get pods -n monitoring -l app.kubernetes.io/name=otel-collector

# Check DaemonSet rollout
kubectl rollout status daemonset/otel-collector -n monitoring

# Check logs
kubectl logs -n monitoring -l app.kubernetes.io/name=otel-collector --tail=100

# Check service endpoints
kubectl get endpoints -n monitoring otel-collector

# Port forward for testing
kubectl port-forward -n monitoring svc/otel-collector 4318:4318

# Check ServiceMonitor
kubectl get servicemonitor -n monitoring otel-collector -o yaml

# Describe pod for troubleshooting
kubectl describe pod -n monitoring -l app.kubernetes.io/name=otel-collector
```
