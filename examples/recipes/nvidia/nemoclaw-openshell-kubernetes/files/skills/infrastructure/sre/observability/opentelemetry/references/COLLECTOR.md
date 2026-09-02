# OpenTelemetry Collector Configuration Reference

## Receivers

### OTLP Receiver (Primary)

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: ${env:MY_POD_IP}:4317
        max_recv_msg_size_mib: 4
      http:
        endpoint: ${env:MY_POD_IP}:4318
        cors:
          allowed_origins: ["*"]
```

### Prometheus Receiver

```yaml
receivers:
  prometheus:
    config:
      scrape_configs:
        - job_name: 'kubernetes-pods'
          kubernetes_sd_configs:
            - role: pod
          relabel_configs:
            - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
              action: keep
              regex: true
            - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
              action: replace
              target_label: __metrics_path__
              regex: (.+)
            - source_labels: [__address__, __meta_kubernetes_pod_annotation_prometheus_io_port]
              action: replace
              regex: ([^:]+)(?::\d+)?;(\d+)
              replacement: $1:$2
              target_label: __address__
```

### Filelog Receiver (Container Logs)

```yaml
receivers:
  filelog:
    include:
      - /var/log/pods/*/*/*.log
    exclude:
      - /var/log/pods/*/otel-collector/*.log
    start_at: beginning
    include_file_path: true
    include_file_name: false
    operators:
      - type: router
        id: get-format
        routes:
          - output: parser-docker
            expr: 'body matches "^\\{"'
          - output: parser-crio
            expr: 'body matches "^[^ Z]+ "'
          - output: parser-containerd
            expr: 'body matches "^[^ Z]+Z"'
```

### Jaeger Receiver (Legacy Support)

```yaml
receivers:
  jaeger:
    protocols:
      grpc:
        endpoint: ${env:MY_POD_IP}:14250
      thrift_http:
        endpoint: ${env:MY_POD_IP}:14268
      thrift_compact:
        endpoint: ${env:MY_POD_IP}:6831
```

### Zipkin Receiver

```yaml
receivers:
  zipkin:
    endpoint: ${env:MY_POD_IP}:9411
```

### Hostmetrics Receiver

```yaml
receivers:
  hostmetrics:
    collection_interval: 30s
    scrapers:
      cpu:
        metrics:
          system.cpu.utilization:
            enabled: true
      memory:
        metrics:
          system.memory.utilization:
            enabled: true
      disk: {}
      filesystem: {}
      network: {}
      load: {}
```

## Processors

### Batch Processor

```yaml
processors:
  batch:
    timeout: 10s           # Max time before sending
    send_batch_size: 1024  # Target batch size
    send_batch_max_size: 2048  # Hard limit
```

**Production Tuning**:

```yaml
processors:
  batch:
    timeout: 30s
    send_batch_size: 2048
    send_batch_max_size: 4096
```

### Memory Limiter Processor

```yaml
processors:
  memory_limiter:
    check_interval: 5s
    limit_percentage: 80        # % of total memory
    spike_limit_percentage: 25  # % buffer for spikes
```

### Resource Processor

```yaml
processors:
  resource:
    attributes:
      - key: cluster.name
        value: ${env:CLUSTER_NAME}
        action: upsert
      - key: deployment.environment
        value: ${env:ENVIRONMENT}
        action: upsert
```

### K8s Attributes Processor

```yaml
processors:
  k8sattributes:
    auth_type: "serviceAccount"
    passthrough: false
    filter:
      node_from_env_var: ${env:K8S_NODE_NAME}
    extract:
      metadata:
        - k8s.pod.name
        - k8s.pod.uid
        - k8s.deployment.name
        - k8s.namespace.name
        - k8s.node.name
        - k8s.pod.start_time
      annotations:
        - tag_name: service.name
          key: app.kubernetes.io/name
          from: pod
        - tag_name: service.version
          key: app.kubernetes.io/version
          from: pod
      labels:
        - tag_name: app
          key: app
          from: pod
```

### Probabilistic Sampler (Traces)

```yaml
processors:
  probabilistic_sampler:
    hash_seed: 22
    sampling_percentage: 10  # Sample 10% of traces
```

### Filter Processor

```yaml
processors:
  filter/logs:
    logs:
      exclude:
        match_type: regexp
        bodies:
          - "health.*check"
          - "GET /healthz"
```

### Transform Processor

```yaml
processors:
  transform:
    metric_statements:
      - context: datapoint
        statements:
          - set(attributes["cluster"], "my-cluster")
```

## Exporters

### Prometheus Remote Write

```yaml
exporters:
  prometheusremotewrite:
    endpoint: "http://prometheus:9090/api/v1/write"
    tls:
      insecure: true  # Use false with proper certs in production
    resource_to_telemetry_conversion:
      enabled: true
    retry_on_failure:
      enabled: true
      initial_interval: 5s
      max_interval: 30s
      max_elapsed_time: 120s
```

### Loki Exporter

```yaml
exporters:
  loki:
    endpoint: "http://loki-gateway:3100/loki/api/v1/push"
    tenant_id: "default"
    labels:
      attributes:
        cluster: ""
        namespace: ""
        pod: ""
        container: ""
      resource:
        cluster.name: "cluster"
        k8s.namespace.name: "namespace"
        k8s.pod.name: "pod"
        k8s.container.name: "container"
```

### OTLP Exporter

```yaml
exporters:
  otlp:
    endpoint: "tempo-distributor:4317"
    tls:
      insecure: true

  otlp/secure:
    endpoint: "otel-backend.example.com:4317"
    tls:
      cert_file: /etc/otel/certs/client.crt
      key_file: /etc/otel/certs/client.key
      ca_file: /etc/otel/certs/ca.crt
```

### Debug Exporter

```yaml
exporters:
  debug:
    verbosity: detailed  # basic, normal, detailed
    sampling_initial: 5
    sampling_thereafter: 200
```

## Extensions

### Health Check

```yaml
extensions:
  health_check:
    endpoint: ${env:MY_POD_IP}:13133
    path: "/health"
```

### Memory Ballast

```yaml
extensions:
  memory_ballast:
    size_in_percentage: 20  # Reserve 20% for GC optimization
```

### zPages (Debug)

```yaml
extensions:
  zpages:
    endpoint: localhost:55679
```

### pprof (Profiling)

```yaml
extensions:
  pprof:
    endpoint: localhost:1777
```

## Service Configuration

### Complete Pipeline Example

```yaml
service:
  extensions: [health_check, memory_ballast]

  telemetry:
    logs:
      level: info  # debug, info, warn, error
    metrics:
      readers:
        - pull:
            exporter:
              prometheus:
                host: ${env:MY_POD_IP}
                port: 8888

  pipelines:
    metrics:
      receivers: [prometheus, otlp]
      processors: [memory_limiter, k8sattributes, resource, batch]
      exporters: [prometheusremotewrite]

    logs:
      receivers: [otlp, filelog]
      processors: [memory_limiter, k8sattributes, resource, batch]
      exporters: [loki]

    traces:
      receivers: [otlp, jaeger, zipkin]
      processors: [memory_limiter, k8sattributes, resource, batch]
      exporters: [otlp/tempo]
```

## Environment Variables

Common environment variables for Helm deployments:

```yaml
extraEnvs:
  - name: K8S_NODE_NAME
    valueFrom:
      fieldRef:
        fieldPath: spec.nodeName
  - name: K8S_POD_NAME
    valueFrom:
      fieldRef:
        fieldPath: metadata.name
  - name: K8S_POD_NAMESPACE
    valueFrom:
      fieldRef:
        fieldPath: metadata.namespace
  - name: K8S_POD_IP
    valueFrom:
      fieldRef:
        fieldPath: status.podIP
  - name: MY_POD_IP
    valueFrom:
      fieldRef:
        fieldPath: status.podIP
  - name: CLUSTER_NAME
    value: "my-cluster"
  - name: ENVIRONMENT
    value: "production"
```

## Configuration Syntax

Use `${env:VAR_NAME}` for environment variable substitution:

```yaml
endpoint: ${env:MY_POD_IP}:4317
```

With default values:

```yaml
endpoint: ${env:MY_POD_IP:-0.0.0.0}:4317
```

## Validate Configuration

```bash
# Validate config file
otelcol validate --config=config.yaml

# List available components
otelcol components
```
