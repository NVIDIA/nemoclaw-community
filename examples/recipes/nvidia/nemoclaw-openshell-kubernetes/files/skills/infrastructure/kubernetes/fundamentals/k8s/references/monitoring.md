# Kubernetes Monitoring & Alerting Guide

Patterns for Prometheus alerting, ServiceMonitor configuration, Grafana dashboards, and key metrics.

---

## Table of Contents

1. [Key Metrics Methodology](#key-metrics-methodology)
2. [Prometheus Alerting Rules](#prometheus-alerting-rules)
3. [ServiceMonitor and PodMonitor](#servicemonitor-and-podmonitor)
4. [Grafana Dashboard Guidelines](#grafana-dashboard-guidelines)
5. [Log Patterns](#log-patterns)

---

## Key Metrics Methodology

### USE Method (for infrastructure/resources)

| Signal | Metric | What It Tells You |
|--------|--------|--------------------|
| **Utilization** | CPU/memory usage % | How saturated is the resource |
| **Saturation** | CPU throttling, memory pressure, disk IOPS queue | Is the resource overloaded |
| **Errors** | OOMKills, disk errors, network drops | Is the resource failing |

### RED Method (for services/applications)

| Signal | Metric | What It Tells You |
|--------|--------|--------------------|
| **Rate** | Requests per second | Traffic volume |
| **Errors** | Error rate / error ratio | Service health |
| **Duration** | Request latency (p50, p95, p99) | User experience |

### The Four Golden Signals (Google SRE)

1. **Latency** — Time to serve a request (separate success vs error latency)
2. **Traffic** — Demand on the system (requests/sec, sessions)
3. **Errors** — Rate of failed requests (explicit 5xx, implicit timeouts)
4. **Saturation** — How "full" the service is (CPU, memory, queue depth)

---

## Prometheus Alerting Rules

### Pod-Level Alerts

```yaml
groups:
  - name: pod-alerts
    rules:
      # Pod stuck in CrashLoopBackOff
      - alert: PodCrashLooping
        expr: |
          increase(kube_pod_container_status_restarts_total[15m]) > 3
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Pod {{ $labels.namespace }}/{{ $labels.pod }} is crash looping"
          description: "Container {{ $labels.container }} restarted {{ $value }} times in 15m"
          runbook: "Check logs: kubectl logs {{ $labels.pod }} -n {{ $labels.namespace }} --previous"

      # Pod not ready for extended period
      - alert: PodNotReady
        expr: |
          kube_pod_status_ready{condition="true"} == 0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Pod {{ $labels.namespace }}/{{ $labels.pod }} not ready for 10m"

      # OOMKilled
      - alert: ContainerOOMKilled
        expr: |
          kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Container {{ $labels.container }} in {{ $labels.namespace }}/{{ $labels.pod }} was OOMKilled"
          description: "Increase memory limits or investigate memory leak"

      # High memory usage (approaching limit)
      - alert: ContainerMemoryNearLimit
        expr: |
          container_memory_working_set_bytes / container_spec_memory_limit_bytes > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Container {{ $labels.container }} using >90% memory limit"

      # High CPU throttling
      - alert: ContainerCPUThrottled
        expr: |
          rate(container_cpu_cfs_throttled_periods_total[5m])
          / rate(container_cpu_cfs_periods_total[5m]) > 0.5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Container {{ $labels.container }} is throttled >50% of the time"
          description: "Consider increasing CPU limits"
```

### Node-Level Alerts

```yaml
groups:
  - name: node-alerts
    rules:
      # Node not ready
      - alert: NodeNotReady
        expr: kube_node_status_condition{condition="Ready",status="true"} == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Node {{ $labels.node }} is NotReady"

      # High node CPU
      - alert: NodeHighCPU
        expr: |
          100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Node {{ $labels.instance }} CPU usage >85%"

      # High node memory
      - alert: NodeHighMemory
        expr: |
          (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100 > 85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Node {{ $labels.instance }} memory usage >85%"

      # Node disk space low
      - alert: NodeDiskSpaceLow
        expr: |
          (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100 > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Node {{ $labels.instance }} root disk usage >85%"
```

### Deployment-Level Alerts

```yaml
groups:
  - name: deployment-alerts
    rules:
      # Deployment replica mismatch
      - alert: DeploymentReplicaMismatch
        expr: |
          kube_deployment_spec_replicas != kube_deployment_status_ready_replicas
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Deployment {{ $labels.namespace }}/{{ $labels.deployment }} has replica mismatch"
          description: "Desired: {{ $value }} but not all replicas are ready"

      # Deployment generation mismatch (stuck rollout)
      - alert: DeploymentStuckRollout
        expr: |
          kube_deployment_status_observed_generation != kube_deployment_metadata_generation
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Deployment {{ $labels.namespace }}/{{ $labels.deployment }} rollout is stuck"

      # HPA at max replicas
      - alert: HPAAtMaxReplicas
        expr: |
          kube_horizontalpodautoscaler_status_current_replicas
          == kube_horizontalpodautoscaler_spec_max_replicas
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "HPA {{ $labels.namespace }}/{{ $labels.horizontalpodautoscaler }} is at max replicas"
          description: "Consider increasing maxReplicas or optimizing the workload"
```

### Cluster-Level Alerts

```yaml
groups:
  - name: cluster-alerts
    rules:
      # API server latency
      - alert: APIServerHighLatency
        expr: |
          histogram_quantile(0.99, rate(apiserver_request_duration_seconds_bucket{verb!="WATCH"}[5m])) > 1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "API server p99 latency >1s"

      # Certificate expiring soon
      - alert: CertificateExpiringSoon
        expr: |
          (apiserver_client_certificate_expiration_seconds_count > 0)
          and on()
          (apiserver_client_certificate_expiration_seconds_bucket{le="604800"} > 0)
        labels:
          severity: critical
        annotations:
          summary: "A client certificate is expiring within 7 days"

      # PVC nearly full
      - alert: PVCNearlyFull
        expr: |
          kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes > 0.85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "PVC {{ $labels.namespace }}/{{ $labels.persistentvolumeclaim }} is >85% full"
```

---

## ServiceMonitor and PodMonitor

### ServiceMonitor (recommended — scrapes via Service)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: myapp
  namespace: production
  labels:
    release: prometheus              # Must match Prometheus operator selector
spec:
  selector:
    matchLabels:
      app: myapp                     # Matches Service labels
  namespaceSelector:
    matchNames:
      - production
  endpoints:
    - port: http-metrics             # Service port name
      path: /metrics
      interval: 30s
      scrapeTimeout: 10s
```

### PodMonitor (when no Service exists)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: batch-jobs
  namespace: production
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app: batch-processor
  podMetricsEndpoints:
    - port: metrics
      path: /metrics
      interval: 60s
```

### PrometheusRule (deploy alerting rules as CRDs)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: myapp-alerts
  namespace: production
  labels:
    release: prometheus              # Must match Prometheus operator selector
spec:
  groups:
    - name: myapp.rules
      rules:
        - alert: MyAppHighErrorRate
          expr: |
            rate(http_requests_total{status=~"5.."}[5m])
            / rate(http_requests_total[5m]) > 0.05
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "myapp error rate >5%"
```

---

## Grafana Dashboard Guidelines

### Dashboard Hierarchy

Structure dashboards as drill-down levels:

1. **Cluster Overview** — Node count, total CPU/memory, unhealthy pods
2. **Namespace Overview** — Resource usage per namespace, pod counts, error rates
3. **Workload Dashboard** — Per-deployment metrics (replicas, restarts, CPU, memory)
4. **Pod Detail** — Individual pod metrics, container stats, logs link

### Key Panels per Dashboard

**Cluster Overview:**
- Node count (ready vs total)
- Cluster CPU/memory utilization gauge
- Top 10 pods by CPU, top 10 by memory
- Pod status breakdown (Running, Pending, Failed)
- Recent warning events

**Workload Dashboard:**
- Replica count (desired vs ready)
- Pod restart rate
- CPU usage vs request vs limit
- Memory usage vs request vs limit
- Network I/O

**Application Dashboard (RED metrics):**
- Request rate (QPS)
- Error rate (% of 5xx)
- Latency histogram (p50, p95, p99)
- Active connections / in-flight requests

### Variable Templating

Use Grafana variables for reusable dashboards:

```
# Namespace variable
label_values(kube_pod_info, namespace)

# Deployment variable (filtered by namespace)
label_values(kube_deployment_labels{namespace="$namespace"}, deployment)

# Pod variable (filtered by namespace + deployment)
label_values(kube_pod_info{namespace="$namespace", created_by_name=~"$deployment.*"}, pod)
```

### Dashboard Best Practices

- Use consistent time ranges across panels (default: last 1h)
- Set meaningful thresholds with color coding (green/yellow/red)
- Include links between dashboards for drill-down
- Add annotations for deployments (mark deploy events on graphs)
- Keep dashboards focused — prefer multiple specific dashboards over one giant one

---

## Log Patterns

### kubectl Log Commands

```bash
# Basic logs
kubectl logs <pod> -n <ns>

# Follow live (stream)
kubectl logs <pod> -n <ns> -f

# Previous container (after crash)
kubectl logs <pod> -n <ns> --previous

# Last N lines
kubectl logs <pod> -n <ns> --tail=100

# Since time
kubectl logs <pod> -n <ns> --since=1h
kubectl logs <pod> -n <ns> --since-time="2024-01-15T10:00:00Z"

# Specific container in multi-container pod
kubectl logs <pod> -n <ns> -c <container>

# All containers in pod
kubectl logs <pod> -n <ns> --all-containers=true

# Logs from all pods matching a label
kubectl logs -l app=myapp -n <ns> --tail=50

# Prefix lines with pod name (useful with label selector)
kubectl logs -l app=myapp -n <ns> --prefix --tail=20
```

### Structured Logging Recommendations

For applications running in Kubernetes, output structured JSON logs:

```json
{"level":"error","ts":"2024-01-15T10:30:00Z","msg":"request failed","method":"POST","path":"/api/users","status":500,"duration_ms":150,"error":"connection refused"}
```

Benefits:
- Easy to parse with log aggregation tools (Loki, Fluentd, Datadog)
- Enables filtering and alerting on specific fields
- Correlates with distributed tracing via trace IDs
- Avoids regex-based log parsing which is fragile

### Log Aggregation Stack

| Tool | Purpose |
|------|---------|
| **Loki** | Log aggregation (pull-based, pairs with Grafana) |
| **Fluentd/Fluent Bit** | Log collection and forwarding |
| **Grafana** | Log visualization and querying |

Loki + Grafana is the most common Kubernetes-native logging stack (lightweight, label-based querying, integrates with Prometheus alerts).
