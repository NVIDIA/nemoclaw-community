# OpenTelemetry Troubleshooting Guide

## Diagnostic Tools

### Enable Debug Logging

```yaml
config:
  service:
    telemetry:
      logs:
        level: debug
```

### Enable Debug Exporter

```yaml
config:
  exporters:
    debug:
      verbosity: detailed
      sampling_initial: 5
      sampling_thereafter: 200

  service:
    pipelines:
      traces:
        exporters: [debug]
      metrics:
        exporters: [debug]
      logs:
        exporters: [debug]
```

### Enable zPages Extension

```yaml
extensions:
  zpages:
    endpoint: localhost:55679

service:
  extensions: [zpages]
```

Access at:

- `/debug/tracez` - Trace data inspection
- `/debug/pipelinez` - Pipeline status

### Enable pprof for Profiling

```yaml
extensions:
  pprof:
    endpoint: localhost:1777

service:
  extensions: [pprof]
```

## Common Issues

### 1. Collector Not Starting

**Check logs**:

```bash
kubectl logs -n monitoring -l app.kubernetes.io/name=otel-collector --previous
```

**Common causes**:

- Invalid configuration syntax
- Missing required extensions
- Port conflicts

**Validate config**:

```bash
otelcol validate --config=config.yaml
```

### 2. Data Not Being Received

**Symptoms**: No data in exporters, empty pipelines

**Diagnostic steps**:

1. **Check receiver is listening**:

```bash
kubectl exec -n monitoring -it deploy/otel-collector -- netstat -tlnp
```

2. **Test OTLP endpoint**:

```bash
kubectl run test-otlp --image=curlimages/curl:latest --rm -it -- \
  curl -v http://otel-collector.monitoring:4318/v1/traces \
  -H "Content-Type: application/json" \
  -d '{"resourceSpans":[]}'
```

3. **Check network policies**:

```bash
kubectl get networkpolicies -n monitoring
kubectl describe networkpolicy -n monitoring
```

4. **Verify service discovery**:

```bash
kubectl get endpoints -n monitoring otel-collector
```

**Common causes**:

- Firewall/network policy blocking traffic
- Wrong endpoint configuration
- Service not ready

### 3. Data Not Being Exported

**Symptoms**: Data received but not appearing in backends

**Diagnostic steps**:

1. **Check exporter logs**:

```bash
kubectl logs -n monitoring -l app.kubernetes.io/name=otel-collector | grep -i export
```

2. **Verify backend connectivity**:

```bash
kubectl exec -n monitoring -it deploy/otel-collector -- \
  wget -O- http://prometheus:9090/-/healthy
```

3. **Check exporter metrics**:

```bash
kubectl exec -n monitoring -it deploy/otel-collector -- \
  curl localhost:8888/metrics | grep otelcol_exporter
```

**Key metrics to check**:

- `otelcol_exporter_sent_metric_points` - Successfully sent
- `otelcol_exporter_send_failed_metric_points` - Failed to send
- `otelcol_exporter_queue_size` - Queue backlog

**Common causes**:

- Backend unreachable
- TLS/authentication issues
- Rate limiting
- Backend capacity

### 4. High Memory Usage / OOM

**Symptoms**: Pods being OOMKilled, high memory consumption

**Diagnostic steps**:

1. **Check memory usage**:

```bash
kubectl top pods -n monitoring -l app.kubernetes.io/name=otel-collector
```

2. **Check memory limiter**:

```bash
kubectl logs -n monitoring -l app.kubernetes.io/name=otel-collector | grep -i "memory"
```

**Solutions**:

```yaml
# Enable memory limiter processor
processors:
  memory_limiter:
    check_interval: 5s
    limit_percentage: 80
    spike_limit_percentage: 25

# Enable GOMEMLIMIT
useGOMEMLIMIT: true

# Add memory ballast
extensions:
  memory_ballast:
    size_in_percentage: 20

# Increase limits
resources:
  limits:
    memory: 2Gi
```

### 5. Collector Restarts / Crashes

**Symptoms**: Frequent pod restarts

**Diagnostic steps**:

1. **Check restart count**:

```bash
kubectl get pods -n monitoring -l app.kubernetes.io/name=otel-collector
```

2. **Check previous logs**:

```bash
kubectl logs -n monitoring -l app.kubernetes.io/name=otel-collector --previous
```

3. **Check events**:

```bash
kubectl get events -n monitoring --sort-by='.lastTimestamp' | grep otel
```

**Common causes**:

- OOM kills
- Liveness probe failures
- Configuration errors

### 6. High CPU Usage

**Symptoms**: CPU throttling, slow processing

**Solutions**:

```yaml
# Increase batch size
processors:
  batch:
    timeout: 30s
    send_batch_size: 2048

# Enable sampling
processors:
  probabilistic_sampler:
    sampling_percentage: 10

# Increase CPU limits
resources:
  limits:
    cpu: 1000m
```

### 7. Pod Scheduling Issues

**Symptoms**: Pods pending, not scheduling

**Diagnostic steps**:

1. **Check pod events**:

```bash
kubectl describe pod -n monitoring -l app.kubernetes.io/name=otel-collector
```

2. **Check node taints**:

```bash
kubectl describe nodes | grep -A 5 Taints
```

**Solution for spot instances (AKS)**:

```yaml
tolerations:
  - key: kubernetes.azure.com/scalesetpriority
    operator: Equal
    value: "spot"
    effect: NoSchedule
```

## Metrics to Monitor

### Collector Health

```promql
# Uptime
up{job="otel-collector"}

# Process uptime
otelcol_process_uptime

# Memory usage
otelcol_process_runtime_heap_alloc_bytes
```

### Pipeline Performance

```promql
# Received data points
rate(otelcol_receiver_accepted_metric_points[5m])
rate(otelcol_receiver_accepted_spans[5m])
rate(otelcol_receiver_accepted_log_records[5m])

# Refused data points
rate(otelcol_receiver_refused_metric_points[5m])

# Exported data points
rate(otelcol_exporter_sent_metric_points[5m])
rate(otelcol_exporter_sent_spans[5m])

# Export failures
rate(otelcol_exporter_send_failed_metric_points[5m])

# Queue size
otelcol_exporter_queue_size
```

### Processor Performance

```promql
# Batch sizes
otelcol_processor_batch_batch_send_size

# Dropped data
rate(otelcol_processor_dropped_metric_points[5m])
```

## Prometheus Alerts

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: otel-collector-alerts
  namespace: monitoring
spec:
  groups:
  - name: otel-collector
    rules:
    - alert: OTelCollectorDown
      expr: up{job="otel-collector"} == 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "OTel Collector is down"
        description: "OTel Collector {{ $labels.pod }} has been down for 5 minutes"

    - alert: OTelCollectorHighMemory
      expr: |
        container_memory_usage_bytes{pod=~"otel-collector.*"}
        / container_spec_memory_limit_bytes{pod=~"otel-collector.*"} > 0.9
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "OTel Collector memory usage above 90%"

    - alert: OTelCollectorExportFailures
      expr: rate(otelcol_exporter_send_failed_metric_points[5m]) > 0
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "OTel Collector failing to export metrics"

    - alert: OTelCollectorQueueFull
      expr: otelcol_exporter_queue_size > 1000
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "OTel Collector export queue is filling up"

    - alert: OTelCollectorReceiverRefused
      expr: rate(otelcol_receiver_refused_metric_points[5m]) > 100
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "OTel Collector refusing data points"
```

## Log Analysis

### Common Log Patterns

**Successful startup**:

```
Everything is ready. Begin running and processing data.
```

**Memory pressure**:

```
Memory usage is above soft limit
Data is being dropped due to memory pressure
```

**Export failures**:

```
Exporting failed. Will retry
rpc error: code = Unavailable
connection refused
```

**Configuration errors**:

```
Error decoding config
unknown component
failed to create
```

### Useful grep commands

```bash
# Check for errors
kubectl logs -n monitoring -l app.kubernetes.io/name=otel-collector | grep -i error

# Check memory issues
kubectl logs -n monitoring -l app.kubernetes.io/name=otel-collector | grep -i memory

# Check export status
kubectl logs -n monitoring -l app.kubernetes.io/name=otel-collector | grep -i export

# Check receiver status
kubectl logs -n monitoring -l app.kubernetes.io/name=otel-collector | grep -i receiver
```

## Quick Fixes

### Restart Collector

```bash
kubectl rollout restart daemonset/otel-collector -n monitoring
# or
kubectl rollout restart deployment/otel-collector -n monitoring
```

### Force Sync ArgoCD

```bash
argocd app sync <cluster>-otel --force
```

### Scale Down/Up

```bash
kubectl scale deployment otel-collector -n monitoring --replicas=0
kubectl scale deployment otel-collector -n monitoring --replicas=3
```

### Clear Checkpoints (Log Collection)

```bash
kubectl exec -n monitoring -it <pod> -- rm -rf /var/lib/otelcol/checkpoints
```
