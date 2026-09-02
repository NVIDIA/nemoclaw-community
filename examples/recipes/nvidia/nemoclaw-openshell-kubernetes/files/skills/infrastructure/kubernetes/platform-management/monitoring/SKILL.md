---
name: kubernetes-platform-monitoring
description: Master Kubernetes observability, monitoring with Prometheus, logging, metrics, and distributed tracing. Learn to implement comprehensive monitoring strategies.
sasmp_version: "1.3.0"
eqhm_enabled: true
bonded_agent: 06-monitoring-observability
bond_type: PRIMARY_BOND
capabilities: ["Prometheus metrics", "Grafana dashboards", "Loki logging", "OpenTelemetry tracing", "Alerting", "SLO management", "Resource monitoring", "Application performance"]
input_schema:
  type: object
  properties:
    action:
      type: string
      enum: ["query", "alert", "dashboard", "trace", "analyze"]
    metric_type:
      type: string
      enum: ["cpu", "memory", "network", "custom", "slo"]
output_schema:
  type: object
  properties:
    metrics:
      type: array
    alerts:
      type: array
    recommendations:
      type: array
---

# Kubernetes Monitoring & Observability

## Executive Summary
Production-grade Kubernetes observability covering the complete stack from infrastructure metrics to application tracing. This skill provides deep expertise in implementing SLO-based monitoring, multi-signal observability, and proactive alerting for enterprise environments.

## Core Competencies

### 1. Metrics with Prometheus

**Prometheus Stack Installation**
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace \
  --set grafana.adminPassword=secure-password \
  --set prometheus.prometheusSpec.retention=30d
```

**Essential PromQL Queries**
```promql
# Pod CPU usage
sum(rate(container_cpu_usage_seconds_total{namespace="production"}[5m])) by (pod)

# Memory utilization
sum(container_memory_working_set_bytes{namespace="production"}) by (pod)
  / sum(container_spec_memory_limit_bytes{namespace="production"}) by (pod) * 100

# Request rate
sum(rate(http_requests_total[5m])) by (service)

# Error rate (5xx)
sum(rate(http_requests_total{status=~"5.."}[5m]))
  / sum(rate(http_requests_total[5m])) * 100

# P99 latency
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))
```

**ServiceMonitor**
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: api-server
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: api-server
  namespaceSelector:
    matchNames:
    - production
  endpoints:
  - port: metrics
    interval: 15s
    path: /metrics
```

### 2. Logging with Loki

**Loki Stack**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: promtail-config
data:
  promtail.yaml: |
    server:
      http_listen_port: 3101
    positions:
      filename: /tmp/positions.yaml
    clients:
    - url: http://loki:3100/loki/api/v1/push
    scrape_configs:
    - job_name: kubernetes-pods
      kubernetes_sd_configs:
      - role: pod
      relabel_configs:
      - source_labels: [__meta_kubernetes_namespace]
        target_label: namespace
      - source_labels: [__meta_kubernetes_pod_name]
        target_label: pod
```

**LogQL Queries**
```logql
# Errors in production
{namespace="production"} |= "error"

# JSON log parsing
{app="api-server"} | json | status >= 500

# Rate of errors
rate({namespace="production"} |= "error" [5m])
```

### 3. Tracing with OpenTelemetry

**OpenTelemetry Collector**
```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: OpenTelemetryCollector
metadata:
  name: otel-collector
spec:
  mode: deployment
  config: |
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
          http:
            endpoint: 0.0.0.0:4318
    processors:
      batch:
        timeout: 10s
    exporters:
      jaeger:
        endpoint: jaeger-collector:14250
        tls:
          insecure: true
    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [batch]
          exporters: [jaeger]
```

### 4. SLO-Based Alerting

**SLO Definition**
```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: api-server-slo
spec:
  groups:
  - name: slo.rules
    rules:
    # Availability SLO: 99.9%
    - record: slo:availability:ratio
      expr: |
        sum(rate(http_requests_total{status!~"5.."}[5m]))
        / sum(rate(http_requests_total[5m]))

    # Latency SLO: P99 < 200ms
    - record: slo:latency:p99
      expr: |
        histogram_quantile(0.99,
          sum(rate(http_request_duration_seconds_bucket[5m])) by (le))

  - name: slo.alerts
    rules:
    - alert: HighErrorRate
      expr: (1 - slo:availability:ratio) > 0.001
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Error rate exceeds SLO (>0.1%)"

    - alert: HighLatency
      expr: slo:latency:p99 > 0.2
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "P99 latency exceeds 200ms"
```

### 5. Alertmanager Configuration

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: alertmanager-config
stringData:
  alertmanager.yaml: |
    global:
      resolve_timeout: 5m
    route:
      receiver: 'default'
      group_by: ['alertname', 'namespace']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 12h
      routes:
      - match:
          severity: critical
        receiver: 'pagerduty'
      - match:
          severity: warning
        receiver: 'slack'
    receivers:
    - name: 'default'
      slack_configs:
      - channel: '#alerts'
        api_url: '${SLACK_WEBHOOK}'
    - name: 'pagerduty'
      pagerduty_configs:
      - service_key: '${PD_SERVICE_KEY}'
    - name: 'slack'
      slack_configs:
      - channel: '#alerts'
```

## Integration Patterns

### Uses skill: **cluster-admin**
- Control plane metrics
- Node resource monitoring

### Coordinates with skill: **deployments**
- Rollout monitoring
- Autoscaling metrics

### Works with skill: **security**
- Security event alerting
- Audit log analysis

## Troubleshooting Guide

### Decision Tree: Observability Issues

```
Monitoring Problem?
│
├── No metrics
│   ├── Check ServiceMonitor selector
│   ├── Verify /metrics endpoint
│   └── Check Prometheus targets
│
├── Missing logs
│   ├── Check Promtail/Fluentbit pods
│   ├── Verify log format
│   └── Check Loki ingestion
│
└── Alert not firing
    ├── Check PromQL expression
    ├── Verify thresholds
    └── Check Alertmanager routes
```

### Debug Commands

```bash
# Prometheus targets
kubectl port-forward -n monitoring svc/prometheus 9090
# Visit /targets

# Grafana access
kubectl port-forward -n monitoring svc/grafana 3000

# Check ServiceMonitors
kubectl get servicemonitors -A

# Alertmanager status
kubectl port-forward -n monitoring svc/alertmanager 9093
```

## Common Challenges & Solutions

| Challenge | Solution |
|-----------|----------|
| High cardinality | Reduce labels, aggregation |
| Retention costs | Tiered storage, downsampling |
| Alert fatigue | SLO-based alerting |
| Missing traces | Auto-instrumentation |

## Success Criteria

| Metric | Target |
|--------|--------|
| Metric collection | 100% services |
| Log retention | 30 days |
| Alert response | <5 minutes |
| Dashboard coverage | All critical |

## Resources
- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [OpenTelemetry](https://opentelemetry.io/docs/)
