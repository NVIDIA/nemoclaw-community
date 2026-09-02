<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Nik Kale -->
<!-- SPDX-License-Identifier: MIT -->

# Alert Examples

Ready-to-use Prometheus alerting rules.

## SLO-Based Alerts

### Error Budget Burn Rate

```yaml
groups:
  - name: slo-alerts
    rules:
      # Fast burn - pages immediately
      - alert: ErrorBudgetFastBurn
        expr: |
          (
            sum(rate(http_requests_total{status=~"5.."}[5m])) by (service)
            /
            sum(rate(http_requests_total[5m])) by (service)
          ) > (14.4 * 0.001)  # 14.4x burn rate on 99.9% SLO
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: '{{ $labels.service }} burning error budget rapidly'
          description: 'Error rate is {{ $value | humanizePercentage }}, consuming 30-day error budget in ~72 hours'
          runbook_url: 'https://wiki/runbooks/error-budget-burn'

      # Slow burn - tickets
      - alert: ErrorBudgetSlowBurn
        expr: |
          (
            sum(rate(http_requests_total{status=~"5.."}[1h])) by (service)
            /
            sum(rate(http_requests_total[1h])) by (service)
          ) > (3 * 0.001)  # 3x burn rate
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: '{{ $labels.service }} elevated error rate'
          description: 'Error rate is {{ $value | humanizePercentage }}'
```

### Latency SLO

```yaml
- alert: LatencySLOBreach
  expr: |
    histogram_quantile(0.99,
      sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service)
    ) > 0.5  # p99 > 500ms
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: '{{ $labels.service }} p99 latency above SLO'
    description: 'p99 latency is {{ $value | humanizeDuration }}'
```

---

## Service Health Alerts

### High Error Rate

```yaml
- alert: HighErrorRate
  expr: |
    (
      sum(rate(http_requests_total{status=~"5.."}[5m])) by (service)
      /
      sum(rate(http_requests_total[5m])) by (service)
    ) > 0.05
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: '{{ $labels.service }} error rate above 5%'
    description: 'Current error rate: {{ $value | humanizePercentage }}'
    dashboard_url: 'https://grafana/d/service/{{ $labels.service }}'
    runbook_url: 'https://wiki/runbooks/high-error-rate'
```

### Service Down

```yaml
- alert: ServiceDown
  expr: up{job="my-service"} == 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: '{{ $labels.job }} is down'
    description: '{{ $labels.instance }} has been unreachable for more than 1 minute'
```

### Elevated Latency

```yaml
- alert: ElevatedLatency
  expr: |
    histogram_quantile(0.95,
      sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service)
    ) > 1
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: '{{ $labels.service }} p95 latency above 1s'
    description: 'p95 latency: {{ $value | humanizeDuration }}'
```

---

## Resource Alerts

### High CPU Usage

```yaml
- alert: HighCPUUsage
  expr: |
    (
      sum(rate(container_cpu_usage_seconds_total[5m])) by (pod)
      /
      sum(container_spec_cpu_quota / container_spec_cpu_period) by (pod)
    ) > 0.9
  for: 15m
  labels:
    severity: warning
  annotations:
    summary: '{{ $labels.pod }} CPU usage above 90%'
    description: 'CPU usage: {{ $value | humanizePercentage }}'
```

### High Memory Usage

```yaml
- alert: HighMemoryUsage
  expr: |
    (
      sum(container_memory_working_set_bytes) by (pod)
      /
      sum(container_spec_memory_limit_bytes) by (pod)
    ) > 0.9
  for: 15m
  labels:
    severity: warning
  annotations:
    summary: '{{ $labels.pod }} memory usage above 90%'
    description: 'Memory usage: {{ $value | humanizePercentage }}'
```

### Disk Space Low

```yaml
- alert: DiskSpaceLow
  expr: |
    (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) < 0.1
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: '{{ $labels.instance }} disk space below 10%'
    description: 'Available: {{ $value | humanizePercentage }}'
```

---

## Database Alerts

### High Connection Usage

```yaml
- alert: DatabaseConnectionsHigh
  expr: |
    pg_stat_activity_count / pg_settings_max_connections > 0.8
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: 'PostgreSQL connections above 80%'
    description: '{{ $value | humanizePercentage }} of max connections in use'
```

### Slow Queries

```yaml
- alert: DatabaseSlowQueries
  expr: |
    rate(pg_stat_statements_mean_time_seconds[5m]) > 1
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: 'Database slow queries detected'
    description: 'Average query time: {{ $value | humanizeDuration }}'
```

### Replication Lag

```yaml
- alert: DatabaseReplicationLag
  expr: |
    pg_replication_lag_seconds > 30
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: 'PostgreSQL replication lag high'
    description: 'Replication lag: {{ $value | humanizeDuration }}'
```

---

## Kubernetes Alerts

### Pod CrashLooping

```yaml
- alert: PodCrashLooping
  expr: |
    rate(kube_pod_container_status_restarts_total[15m]) > 0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: '{{ $labels.pod }} is crash looping'
    description: 'Pod has restarted {{ $value }} times in the last 15 minutes'
```

### Pod Not Ready

```yaml
- alert: PodNotReady
  expr: |
    kube_pod_status_ready{condition="false"} == 1
  for: 15m
  labels:
    severity: warning
  annotations:
    summary: '{{ $labels.pod }} not ready'
    description: 'Pod has been not ready for more than 15 minutes'
```

### Deployment Replicas Mismatch

```yaml
- alert: DeploymentReplicasMismatch
  expr: |
    kube_deployment_status_replicas_available
    !=
    kube_deployment_spec_replicas
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: '{{ $labels.deployment }} replicas mismatch'
    description: 'Available: {{ $value }}, Desired: {{ $labels.replicas }}'
```

---

## Queue/Messaging Alerts

### High Queue Depth

```yaml
- alert: QueueBacklog
  expr: |
    rabbitmq_queue_messages > 10000
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: '{{ $labels.queue }} has high message backlog'
    description: 'Queue depth: {{ $value }}'
```

### Consumer Lag

```yaml
- alert: KafkaConsumerLag
  expr: |
    kafka_consumer_group_lag > 100000
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: 'Kafka consumer lag high'
    description: 'Consumer group {{ $labels.group }} lag: {{ $value }}'
```

---

## Alert Routing Example

```yaml
route:
  receiver: 'default'
  group_by: ['alertname', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - match:
        severity: critical
      receiver: 'pagerduty-critical'
      continue: true
    - match:
        severity: warning
      receiver: 'slack-warnings'
    - match:
        team: platform
      receiver: 'platform-team'

receivers:
  - name: 'pagerduty-critical'
    pagerduty_configs:
      - service_key: '<key>'

  - name: 'slack-warnings'
    slack_configs:
      - channel: '#alerts'

  - name: 'platform-team'
    email_configs:
      - to: 'platform-team@company.com'
```
