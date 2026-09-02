# OpenTelemetry Instrumentation Guide

## Overview

Instrumentation is how applications generate telemetry data. OpenTelemetry supports:

- **Zero-code/Auto-instrumentation**: Automatic via agents/libraries
- **Code-based instrumentation**: Explicit SDK usage

## Environment Variables (Universal)

All OpenTelemetry SDKs respect these environment variables:

```bash
# Exporter endpoint
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317

# Protocol (grpc or http/protobuf)
OTEL_EXPORTER_OTLP_PROTOCOL=grpc

# Service identification
OTEL_SERVICE_NAME=my-service
OTEL_SERVICE_VERSION=1.0.0

# Resource attributes
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production,service.namespace=my-ns

# Trace sampling
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1

# Exporter timeouts
OTEL_EXPORTER_OTLP_TIMEOUT=30000
```

## Kubernetes Pod Configuration

### Basic OTLP Configuration

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    spec:
      containers:
      - name: app
        env:
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: "http://otel-collector.monitoring.svc.cluster.local:4317"
        - name: OTEL_SERVICE_NAME
          value: "my-app"
        - name: OTEL_RESOURCE_ATTRIBUTES
          value: "service.namespace=my-namespace,deployment.environment=production"
```

### With Pod Metadata Injection

```yaml
env:
- name: OTEL_SERVICE_NAME
  valueFrom:
    fieldRef:
      fieldPath: metadata.labels['app.kubernetes.io/name']
- name: OTEL_RESOURCE_ATTRIBUTES
  value: "k8s.pod.name=$(POD_NAME),k8s.namespace.name=$(POD_NAMESPACE)"
- name: POD_NAME
  valueFrom:
    fieldRef:
      fieldPath: metadata.name
- name: POD_NAMESPACE
  valueFrom:
    fieldRef:
      fieldPath: metadata.namespace
```

## Language-Specific Instrumentation

### Java

**Auto-instrumentation (Agent)**:

```dockerfile
FROM eclipse-temurin:17-jre
COPY opentelemetry-javaagent.jar /opt/
ENV JAVA_TOOL_OPTIONS="-javaagent:/opt/opentelemetry-javaagent.jar"
ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
ENV OTEL_SERVICE_NAME=my-java-app
```

**Kubernetes deployment**:

```yaml
env:
- name: JAVA_TOOL_OPTIONS
  value: "-javaagent:/opt/opentelemetry-javaagent.jar"
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: "http://otel-collector.monitoring:4317"
- name: OTEL_SERVICE_NAME
  value: "my-java-app"
- name: OTEL_TRACES_EXPORTER
  value: "otlp"
- name: OTEL_METRICS_EXPORTER
  value: "otlp"
- name: OTEL_LOGS_EXPORTER
  value: "otlp"
```

**Manual instrumentation**:

```java
// Add dependencies
// io.opentelemetry:opentelemetry-api
// io.opentelemetry:opentelemetry-sdk
// io.opentelemetry:opentelemetry-exporter-otlp

import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.api.trace.Span;

Tracer tracer = GlobalOpenTelemetry.getTracer("my-instrumentation");
Span span = tracer.spanBuilder("my-operation").startSpan();
try {
    // Do work
} finally {
    span.end();
}
```

### Python

**Auto-instrumentation**:

```bash
pip install opentelemetry-distro opentelemetry-exporter-otlp
opentelemetry-bootstrap -a install
opentelemetry-instrument python app.py
```

**Kubernetes deployment**:

```yaml
env:
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: "http://otel-collector.monitoring:4317"
- name: OTEL_SERVICE_NAME
  value: "my-python-app"
- name: OTEL_PYTHON_LOG_CORRELATION
  value: "true"
command: ["opentelemetry-instrument", "python", "app.py"]
```

**Manual instrumentation**:

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# Setup
trace.set_tracer_provider(TracerProvider())
otlp_exporter = OTLPSpanExporter(endpoint="otel-collector:4317", insecure=True)
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(otlp_exporter))

# Usage
tracer = trace.get_tracer(__name__)
with tracer.start_as_current_span("my-operation") as span:
    span.set_attribute("key", "value")
    # Do work
```

### Node.js/JavaScript

**Auto-instrumentation**:

```bash
npm install @opentelemetry/auto-instrumentations-node
```

```javascript
// tracing.js - load before app
const { NodeSDK } = require('@opentelemetry/sdk-node');
const { getNodeAutoInstrumentations } = require('@opentelemetry/auto-instrumentations-node');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-grpc');

const sdk = new NodeSDK({
  traceExporter: new OTLPTraceExporter({
    url: process.env.OTEL_EXPORTER_OTLP_ENDPOINT || 'http://otel-collector:4317',
  }),
  instrumentations: [getNodeAutoInstrumentations()],
});

sdk.start();
```

**Kubernetes deployment**:

```yaml
env:
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: "http://otel-collector.monitoring:4317"
- name: OTEL_SERVICE_NAME
  value: "my-node-app"
- name: NODE_OPTIONS
  value: "--require ./tracing.js"
```

### Go

**Manual instrumentation**:

```go
import (
    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
    "go.opentelemetry.io/otel/sdk/trace"
)

func initTracer() (*trace.TracerProvider, error) {
    exporter, err := otlptracegrpc.New(ctx,
        otlptracegrpc.WithEndpoint("otel-collector:4317"),
        otlptracegrpc.WithInsecure(),
    )
    if err != nil {
        return nil, err
    }

    tp := trace.NewTracerProvider(
        trace.WithBatcher(exporter),
    )
    otel.SetTracerProvider(tp)
    return tp, nil
}

// Usage
tracer := otel.Tracer("my-instrumentation")
ctx, span := tracer.Start(ctx, "my-operation")
defer span.End()
```

### .NET

**Auto-instrumentation**:

```csharp
// Add packages
// OpenTelemetry.Extensions.Hosting
// OpenTelemetry.Instrumentation.AspNetCore
// OpenTelemetry.Exporter.OpenTelemetryProtocol

builder.Services.AddOpenTelemetry()
    .WithTracing(tracing => tracing
        .AddAspNetCoreInstrumentation()
        .AddHttpClientInstrumentation()
        .AddOtlpExporter(options =>
        {
            options.Endpoint = new Uri("http://otel-collector:4317");
        }));
```

## Kubernetes Operator (Auto-Instrumentation)

### Install Operator

```bash
kubectl apply -f https://github.com/open-telemetry/opentelemetry-operator/releases/latest/download/opentelemetry-operator.yaml
```

### Create Instrumentation Resource

```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: my-instrumentation
  namespace: my-namespace
spec:
  exporter:
    endpoint: http://otel-collector.monitoring:4317
  propagators:
    - tracecontext
    - baggage
  sampler:
    type: parentbased_traceidratio
    argument: "0.1"
  java:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:latest
  python:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-python:latest
  nodejs:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-nodejs:latest
  dotnet:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-dotnet:latest
```

### Annotate Pods for Auto-Instrumentation

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    metadata:
      annotations:
        # Choose one based on language
        instrumentation.opentelemetry.io/inject-java: "true"
        # instrumentation.opentelemetry.io/inject-python: "true"
        # instrumentation.opentelemetry.io/inject-nodejs: "true"
        # instrumentation.opentelemetry.io/inject-dotnet: "true"
```

## Semantic Conventions

Use standard attribute names for interoperability:

### Service Attributes

```
service.name
service.version
service.namespace
service.instance.id
```

### Kubernetes Attributes

```
k8s.cluster.name
k8s.namespace.name
k8s.pod.name
k8s.pod.uid
k8s.deployment.name
k8s.node.name
k8s.container.name
```

### HTTP Attributes

```
http.method
http.url
http.status_code
http.route
http.user_agent
```

### Database Attributes

```
db.system
db.name
db.operation
db.statement
```

## Testing Instrumentation

### Verify Traces

```bash
# Check collector logs for received spans
kubectl logs -n monitoring -l app.kubernetes.io/name=otel-collector | grep -i span

# Use debug exporter
kubectl logs -n monitoring -l app.kubernetes.io/name=otel-collector | grep -A 20 "ResourceSpans"
```

### Generate Test Traffic

```bash
# Simple curl test
for i in {1..10}; do
  curl -s http://my-app.default/api/test
  sleep 1
done
```

### Verify in Backend

```bash
# Grafana Tempo query
kubectl port-forward -n monitoring svc/tempo 3100:3100
curl http://localhost:3100/api/search?q=service.name=my-app

# Jaeger UI
kubectl port-forward -n monitoring svc/jaeger-query 16686:16686
# Open http://localhost:16686
```
