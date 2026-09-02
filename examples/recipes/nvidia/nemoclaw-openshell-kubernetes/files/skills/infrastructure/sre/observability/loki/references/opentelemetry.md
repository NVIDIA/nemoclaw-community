# OpenTelemetry Integration Reference

## Overview

Grafana Loki supports two methods for OpenTelemetry log ingestion:

1. **Native OTLP Endpoint** (Recommended - Loki 3.0+)
2. **LokiExporter** (Deprecated)

## Native OTLP Integration (Recommended)

### Key Benefits

- Log body stored as plain text (not JSON encoded)
- 17 default resource attributes auto-indexed as labels
- Structured metadata for non-indexed attributes
- Simpler queries without JSON parsing
- Better storage efficiency
- All future enhancements focus on this method

### Loki Configuration

```yaml
loki:
  limits_config:
    # Required for OTLP (default in Loki 3.0+)
    allow_structured_metadata: true

    # Optional: Customize OTLP attribute mapping
    otlp_config:
      resource_attributes:
        attributes_config:
          # Promote additional attributes to index labels
          - action: index_label
            attributes:
              - custom.attribute
          # Drop sensitive attributes
          - action: drop
            attributes:
              - sensitive.field
```

### OpenTelemetry Collector Configuration

**Basic Configuration:**

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

exporters:
  otlphttp:
    endpoint: http://loki-gateway:3100/otlp

service:
  pipelines:
    logs:
      receivers: [otlp]
      exporters: [otlphttp]
```

**With Authentication:**

```yaml
extensions:
  basicauth:
    client_auth:
      username: ${LOKI_USERNAME}
      password: ${LOKI_PASSWORD}

exporters:
  otlphttp:
    endpoint: http://loki-gateway:3100/otlp
    auth:
      authenticator: basicauth

service:
  extensions: [basicauth]
  pipelines:
    logs:
      receivers: [otlp]
      exporters: [otlphttp]
```

**With Multi-Tenancy:**

```yaml
exporters:
  otlphttp:
    endpoint: http://loki-gateway:3100/otlp
    headers:
      X-Scope-OrgID: "my-tenant"
```

### Resource Attribute Mapping

Loki automatically indexes these default resource attributes as labels:

| OTLP Resource Attribute | Loki Label |
|------------------------|------------|
| `service.name` | `service_name` |
| `service.namespace` | `service_namespace` |
| `service.instance.id` | `service_instance_id` |
| `k8s.pod.name` | `k8s_pod_name` |
| `k8s.pod.uid` | `k8s_pod_uid` |
| `k8s.namespace.name` | `k8s_namespace_name` |
| `k8s.container.name` | `k8s_container_name` |
| `k8s.replicaset.name` | `k8s_replicaset_name` |
| `k8s.deployment.name` | `k8s_deployment_name` |
| `k8s.statefulset.name` | `k8s_statefulset_name` |
| `k8s.daemonset.name` | `k8s_daemonset_name` |
| `k8s.cronjob.name` | `k8s_cronjob_name` |
| `k8s.job.name` | `k8s_job_name` |
| `k8s.node.name` | `k8s_node_name` |
| `cloud.provider` | `cloud_provider` |
| `cloud.region` | `cloud_region` |
| `cloud.availability_zone` | `cloud_availability_zone` |

**Transformation Rules:**

- Dots converted to underscores: `service.name` → `service_name`
- Nested attributes flattened: `http.request.body` → `http_request_body`
- Non-string values stringified automatically

### OTLP Data Model

**LogRecord Structure:**

```
LogRecord:
  Timestamp            # Event occurrence time
  ObservedTimestamp    # System detection time
  TraceContext:
    TraceId            # Links to distributed trace
    SpanId             # Links to operation span
    TraceFlags         # Sampling info
  SeverityNumber       # 1-24 scale
  SeverityText         # TRACE, DEBUG, INFO, WARN, ERROR, FATAL
  Body                 # Log message
  Resource             # Source metadata
  InstrumentationScope # Emitting library info
  Attributes           # Custom key-value pairs
```

**Severity Level Mapping:**

| SeverityNumber | SeverityText |
|---------------|--------------|
| 1-4 | TRACE |
| 5-8 | DEBUG |
| 9-12 | INFO |
| 13-16 | WARN |
| 17-20 | ERROR |
| 21-24 | FATAL |

### Querying OTLP Logs

**Direct Attribute Access:**

```logql
# Filter by severity
{service_name="api"} | severity_text="ERROR"

# Filter by trace context
{service_name="api"} | trace_id="abc123"

# Access structured metadata
{service_name="api"} | user_id="12345"
```

**Compare with LokiExporter (legacy):**

```logql
# OTLP Native (simple)
{service_name="api"} | severity_text="ERROR"

# LokiExporter (complex - requires parsing)
{job="my-namespace/api"} | json | severity="ERROR"
```

## LokiExporter (Deprecated)

**Status:** No longer recommended. No new feature development.

### Why Deprecated

- All data encoded into JSON blobs
- Requires query-time JSON parsing
- Fixed index labels only: `job`, `instance`, `exporter`, `level`
- Higher query overhead
- Inefficient storage

### Migration to Native OTLP

**Step 1: Update Loki Configuration**

```yaml
loki:
  limits_config:
    allow_structured_metadata: true
```

**Step 2: Update Collector Configuration**

```yaml
# Old (LokiExporter)
exporters:
  loki:
    endpoint: http://loki:3100/loki/api/v1/push
    labels:
      attributes:
        severity: ""

# New (Native OTLP)
exporters:
  otlphttp:
    endpoint: http://loki:3100/otlp
```

**Step 3: Update LogQL Queries**

```logql
# Old (LokiExporter)
{job="namespace/service"} | json | level="error"

# New (Native OTLP)
{service_name="service", service_namespace="namespace"} | severity_text="ERROR"
```

## Grafana Alloy Configuration

Grafana Alloy is the recommended collector for Loki.

**Basic OTLP to Loki:**

```river
otelcol.receiver.otlp "default" {
  grpc {
    endpoint = "0.0.0.0:4317"
  }
  http {
    endpoint = "0.0.0.0:4318"
  }

  output {
    logs = [otelcol.exporter.otlphttp.loki.input]
  }
}

otelcol.exporter.otlphttp "loki" {
  client {
    endpoint = "http://loki-gateway:3100/otlp"
    headers = {
      "X-Scope-OrgID" = "default",
    }
  }
}
```

**With Kubernetes Attributes:**

```river
otelcol.processor.k8sattributes "default" {
  extract {
    metadata = [
      "k8s.namespace.name",
      "k8s.pod.name",
      "k8s.deployment.name",
      "k8s.node.name",
    ]
  }

  output {
    logs = [otelcol.exporter.otlphttp.loki.input]
  }
}
```

## Application SDK Configuration

### Java (Log4j2)

```xml
<!-- log4j2.xml -->
<Configuration>
  <Appenders>
    <OpenTelemetry name="OpenTelemetryAppender"/>
  </Appenders>
  <Loggers>
    <Root level="INFO">
      <AppenderRef ref="OpenTelemetryAppender"/>
    </Root>
  </Loggers>
</Configuration>
```

```properties
# application.properties
otel.exporter.otlp.endpoint=http://collector:4317
otel.service.name=my-java-app
```

### Python

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

# Setup logging
logger_provider = LoggerProvider()
logger_provider.add_log_record_processor(
    BatchLogRecordProcessor(OTLPLogExporter(endpoint="http://collector:4317"))
)
```

### Go

```go
import (
    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploggrpc"
    "go.opentelemetry.io/otel/sdk/log"
)

func initLogger() {
    exporter, _ := otlploggrpc.New(ctx,
        otlploggrpc.WithEndpoint("collector:4317"),
        otlploggrpc.WithInsecure(),
    )

    provider := log.NewLoggerProvider(
        log.WithProcessor(log.NewBatchProcessor(exporter)),
    )
}
```

### Node.js

```javascript
const { OTLPLogExporter } = require('@opentelemetry/exporter-logs-otlp-grpc');
const { LoggerProvider } = require('@opentelemetry/sdk-logs');

const loggerProvider = new LoggerProvider();
loggerProvider.addLogRecordProcessor(
  new BatchLogRecordProcessor(
    new OTLPLogExporter({
      url: 'http://collector:4317',
    })
  )
);
```

## Best Practices

### Resource Attribute Strategy

1. **Use Semantic Conventions**
   - Use standard OpenTelemetry semantic conventions
   - Consistent naming across services

2. **Avoid High Cardinality**
   - Don't use request IDs, user IDs as resource attributes
   - Store high-cardinality data in log attributes (structured metadata)

3. **Kubernetes-Native Attributes**
   - Let collector auto-detect k8s attributes
   - Use k8sattributes processor in collector

### Query Optimization

1. **Index Labels First**

   ```logql
   # Good - uses indexed labels
   {service_name="api", k8s_namespace_name="prod"} | severity_text="ERROR"

   # Bad - no index filter
   {} | severity_text="ERROR" | service_name="api"
   ```

2. **Use Structured Metadata for Secondary Filters**

   ```logql
   {service_name="api"} | user_id="12345"
   ```

### Trace Correlation

```logql
# Find logs for a specific trace
{service_name="api"} | trace_id="abc123def456"

# Link to Grafana Tempo
# Use trace_id to navigate from logs to traces
```

## Troubleshooting

### OTLP Payloads Rejected

**Error:** `malformed request` or structured metadata errors

**Solution:**

```yaml
loki:
  limits_config:
    allow_structured_metadata: true
```

### Missing Attributes in Labels

**Issue:** Resource attributes not appearing as index labels

**Check:**

1. Verify attribute is in default list or custom config
2. Check attribute naming follows conventions
3. Verify collector is sending attributes

### High Cardinality Warnings

**Issue:** Too many unique label values

**Solution:**

1. Move high-cardinality attributes to structured metadata
2. Use `otlp_config` to drop or not index certain attributes

### Connection Issues

```bash
# Test collector to Loki connectivity
curl -v http://loki-gateway:3100/ready

# Check collector logs
kubectl logs -l app=otel-collector -c collector

# Verify endpoint format
# Correct: http://loki:3100/otlp
# Wrong: http://loki:3100/loki/api/v1/push (that's the push API)
```
