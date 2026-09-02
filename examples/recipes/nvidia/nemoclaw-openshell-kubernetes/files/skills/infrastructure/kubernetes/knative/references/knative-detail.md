# Knative Detailed Reference

## API Reference

### Serving API (serving.knative.dev/v1)

#### Service

The primary resource for deploying serverless workloads.

```yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: string                    # Required: Unique name
  namespace: string               # Optional: defaults to 'default'
  labels: {}                      # Optional: Key-value labels
  annotations:                    # Optional: Key-value annotations
    # Common annotations
    serving.knative.dev/creator: string
    serving.knative.dev/lastModifier: string
spec:
  template:                       # Required: PodTemplateSpec
    metadata:
      name: string                # Optional: Revision name (auto-generated if omitted)
      annotations:                # Autoscaling and other annotations
        autoscaling.knative.dev/class: string
        autoscaling.knative.dev/metric: string
        autoscaling.knative.dev/target: string
        autoscaling.knative.dev/min-scale: string
        autoscaling.knative.dev/max-scale: string
    spec:
      serviceAccountName: string  # Optional: Service account
      containerConcurrency: int   # Optional: Hard concurrency limit (0=unlimited)
      timeoutSeconds: int         # Optional: Request timeout (default: 300)
      containers:                 # Required: Container specs
        - name: string
          image: string           # Required: Container image
          imagePullPolicy: string # Optional: Always/IfNotPresent/Never
          command: []             # Optional: Entrypoint
          args: []                # Optional: Arguments
          env: []                 # Optional: Environment variables
          envFrom: []             # Optional: Environment from ConfigMap/Secret
          ports:                  # Optional: Container ports
            - name: string        # Optional: h2c or http1
              containerPort: int  # Required: Port number
              protocol: string    # Optional: TCP (default)
          resources:              # Recommended: Resource requirements
            requests:
              cpu: string
              memory: string
            limits:
              memory: string      # CPU limits NOT recommended
          readinessProbe: {}      # Optional: Readiness probe
          livenessProbe: {}       # Optional: Liveness probe
          volumeMounts: []        # Optional: Volume mounts
      volumes: []                 # Optional: Volumes
  traffic:                        # Optional: Traffic routing
    - revisionName: string        # Route to specific revision
      latestRevision: bool        # Or route to latest
      percent: int                # Traffic percentage (0-100)
      tag: string                 # Optional: Named tag for URL
```

#### Configuration

Manages revision history (typically managed through Service).

```yaml
apiVersion: serving.knative.dev/v1
kind: Configuration
metadata:
  name: string
spec:
  template:                       # Same as Service.spec.template
    # ...
```

#### Revision

Immutable snapshot of code and configuration (auto-created).

```yaml
apiVersion: serving.knative.dev/v1
kind: Revision
metadata:
  name: string                    # Auto-generated: {service}-{random}
  labels:
    serving.knative.dev/service: string
    serving.knative.dev/configuration: string
spec:
  # Inherited from Configuration/Service template
```

#### Route

Manages traffic routing to Revisions.

```yaml
apiVersion: serving.knative.dev/v1
kind: Route
metadata:
  name: string
spec:
  traffic:
    - revisionName: string
      percent: int
      tag: string
```

### Eventing API (eventing.knative.dev/v1)

#### Broker

Event routing hub.

```yaml
apiVersion: eventing.knative.dev/v1
kind: Broker
metadata:
  name: string
  namespace: string
  annotations:
    eventing.knative.dev/broker.class: string  # MTChannelBasedBroker, Kafka, etc.
spec:
  config:                         # Optional: Broker configuration
    apiVersion: string
    kind: string
    name: string
    namespace: string
  delivery:                       # Optional: Delivery options
    deadLetterSink:               # Dead letter queue
      ref:
        apiVersion: string
        kind: string
        name: string
    retry: int                    # Retry count
    backoffPolicy: string         # linear or exponential
    backoffDelay: string          # Duration (e.g., PT1S)
```

#### Trigger

Event subscription with filtering.

```yaml
apiVersion: eventing.knative.dev/v1
kind: Trigger
metadata:
  name: string
  namespace: string
spec:
  broker: string                  # Required: Broker name
  filter:                         # Optional: Event filtering
    attributes:                   # CloudEvent attributes
      type: string                # Event type filter
      source: string              # Event source filter
      subject: string             # Event subject filter
      # Any CloudEvent extension attribute
  subscriber:                     # Required: Event destination
    ref:                          # Reference to Kubernetes resource
      apiVersion: string
      kind: string
      name: string
      namespace: string           # Optional: defaults to Trigger namespace
    uri: string                   # Alternative: Direct URI
  delivery:                       # Optional: Per-trigger delivery options
    deadLetterSink: {}
    retry: int
    backoffPolicy: string
    backoffDelay: string
```

### Sources API (sources.knative.dev/v1)

#### PingSource

Cron-scheduled event producer.

```yaml
apiVersion: sources.knative.dev/v1
kind: PingSource
metadata:
  name: string
spec:
  schedule: string                # Required: Cron expression
  timezone: string                # Optional: Timezone (default: UTC)
  contentType: string             # Optional: application/json, text/plain
  data: string                    # Optional: Event payload
  dataBase64: string              # Optional: Base64-encoded payload
  sink:                           # Required: Event destination
    ref:
      apiVersion: string
      kind: string
      name: string
    uri: string                   # Alternative: Direct URI
```

#### ApiServerSource

Kubernetes API event producer.

```yaml
apiVersion: sources.knative.dev/v1
kind: ApiServerSource
metadata:
  name: string
spec:
  mode: string                    # Reference or Resource
  resources:                      # Required: Resources to watch
    - apiVersion: string
      kind: string
  serviceAccountName: string      # Required: SA with RBAC permissions
  sink:
    ref:
      apiVersion: string
      kind: string
      name: string
```

#### ContainerSource

Custom container event producer.

```yaml
apiVersion: sources.knative.dev/v1
kind: ContainerSource
metadata:
  name: string
spec:
  template:                       # Required: Pod template
    spec:
      containers:
        - image: string
          name: string
          env:
            - name: K_SINK        # Injected by Knative
              value: string
  sink:
    ref:
      apiVersion: string
      kind: string
      name: string
```

### Flows API (flows.knative.dev/v1)

#### Sequence

Serial event processing pipeline.

```yaml
apiVersion: flows.knative.dev/v1
kind: Sequence
metadata:
  name: string
spec:
  channelTemplate:                # Required: Channel type
    apiVersion: messaging.knative.dev/v1
    kind: InMemoryChannel         # Or KafkaChannel
  steps:                          # Required: Processing steps
    - ref:
        apiVersion: string
        kind: string
        name: string
      uri: string                 # Alternative to ref
      delivery: {}                # Optional: Per-step delivery
  reply:                          # Optional: Final destination
    ref:
      apiVersion: string
      kind: string
      name: string
```

#### Parallel

Fan-out event processing.

```yaml
apiVersion: flows.knative.dev/v1
kind: Parallel
metadata:
  name: string
spec:
  channelTemplate:
    apiVersion: messaging.knative.dev/v1
    kind: InMemoryChannel
  branches:                       # Required: Parallel branches
    - filter:                     # Optional: Branch filter
        ref:
          apiVersion: string
          kind: string
          name: string
      subscriber:                 # Required: Branch processor
        ref:
          apiVersion: string
          kind: string
          name: string
      reply:                      # Optional: Branch reply destination
        ref:
          apiVersion: string
          kind: string
          name: string
  reply:                          # Optional: Aggregated reply destination
    ref:
      apiVersion: string
      kind: string
      name: string
```

## ConfigMaps Reference

### config-autoscaler (knative-serving)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: config-autoscaler
  namespace: knative-serving
data:
  # Container concurrency target default
  container-concurrency-target-default: "100"

  # Target utilization (0.0-1.0)
  target-utilization-percentage: "70"

  # Scale bounds
  enable-scale-to-zero: "true"
  scale-to-zero-grace-period: "30s"
  scale-to-zero-pod-retention-period: "0s"

  # Scaling rates
  max-scale-up-rate: "1000"
  max-scale-down-rate: "2"

  # Stable window for metrics
  stable-window: "60s"

  # Panic mode settings
  panic-window-percentage: "10"
  panic-threshold-percentage: "200"
```

### config-defaults (knative-serving)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: config-defaults
  namespace: knative-serving
data:
  # Default revision timeout
  revision-timeout-seconds: "300"

  # Default container concurrency
  container-concurrency: "0"

  # Default resource requests
  revision-cpu-request: "400m"
  revision-memory-request: "100M"
  revision-ephemeral-storage-request: "500M"

  # Default resource limits
  revision-cpu-limit: "1000m"
  revision-memory-limit: "200M"
  revision-ephemeral-storage-limit: "750M"
```

### config-domain (knative-serving)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: config-domain
  namespace: knative-serving
data:
  # Default domain for all services
  example.com: ""

  # Selector-based domain mapping
  custom.example.com: |
    selector:
      app: special-app
```

### config-network (knative-serving)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: config-network
  namespace: knative-serving
data:
  # Ingress class (networking layer)
  ingress-class: kourier.ingress.networking.knative.dev
  # Or: istio.ingress.networking.knative.dev
  # Or: contour.ingress.networking.knative.dev

  # Certificate class for auto-TLS
  certificate-class: cert-manager.certificate.networking.knative.dev

  # Auto-TLS configuration
  auto-tls: "Enabled"
  http-protocol: "Redirected"  # or "Enabled"

  # External/Internal service visibility
  default-external-scheme: https

  # Domain template
  domain-template: "{{.Name}}.{{.Namespace}}.{{.Domain}}"
```

### config-br-defaults (knative-eventing)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: config-br-defaults
  namespace: knative-eventing
data:
  default-br-config: |
    clusterDefault:
      brokerClass: MTChannelBasedBroker
      apiVersion: v1
      kind: ConfigMap
      name: config-br-default-channel
      namespace: knative-eventing
      delivery:
        retry: 10
        backoffPolicy: exponential
        backoffDelay: PT0.2S
```

## Metrics Reference

### Serving Metrics

Exposed at `:9090/metrics` on knative-serving pods.

| Metric | Type | Description |
|--------|------|-------------|
| `revision_request_count` | Counter | Total requests per revision |
| `revision_request_latencies` | Histogram | Request latency distribution |
| `revision_app_request_count` | Counter | App-level request count |
| `revision_app_request_latencies` | Histogram | App-level latency |
| `activator_request_count` | Counter | Requests through activator |
| `autoscaler_actual_pods` | Gauge | Current pod count |
| `autoscaler_desired_pods` | Gauge | Desired pod count |
| `autoscaler_stable_request_concurrency` | Gauge | Average concurrency (stable) |
| `autoscaler_panic_request_concurrency` | Gauge | Average concurrency (panic) |

### Eventing Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `broker_dispatch_count` | Counter | Events dispatched by broker |
| `broker_dispatch_latency` | Histogram | Event dispatch latency |
| `trigger_dispatch_count` | Counter | Events dispatched by trigger |
| `trigger_filter_count` | Counter | Events filtered by trigger |
| `event_count` | Counter | Total events processed |

## CloudEvents Specification

Knative Eventing uses CloudEvents format (CNCF specification).

### Required Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `specversion` | String | CloudEvents spec version (1.0) |
| `id` | String | Unique event ID |
| `source` | URI-reference | Event source identifier |
| `type` | String | Event type (e.g., `dev.knative.example`) |

### Optional Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `datacontenttype` | String | Content type (e.g., `application/json`) |
| `dataschema` | URI | Schema for data attribute |
| `subject` | String | Event subject |
| `time` | Timestamp | Event timestamp (RFC 3339) |

### HTTP Binding

```http
POST /events HTTP/1.1
Host: broker-ingress.knative-eventing.svc.cluster.local
Content-Type: application/json
ce-specversion: 1.0
ce-type: dev.knative.example
ce-source: /my/source
ce-id: A234-1234-1234
ce-time: 2024-01-01T00:00:00Z

{
  "message": "Hello, World!"
}
```

## Annotations Reference

### Serving Annotations

| Annotation | Values | Description |
|------------|--------|-------------|
| `autoscaling.knative.dev/class` | `kpa.autoscaling.knative.dev`, `hpa.autoscaling.knative.dev` | Autoscaler implementation |
| `autoscaling.knative.dev/metric` | `concurrency`, `rps`, `cpu`, `memory` | Scaling metric |
| `autoscaling.knative.dev/target` | Number | Target value for metric |
| `autoscaling.knative.dev/min-scale` | Number | Minimum replicas |
| `autoscaling.knative.dev/max-scale` | Number | Maximum replicas |
| `autoscaling.knative.dev/initial-scale` | Number | Initial replicas on creation |
| `autoscaling.knative.dev/scale-down-delay` | Duration | Delay before scale down |
| `autoscaling.knative.dev/window` | Duration | Metrics averaging window |
| `autoscaling.knative.dev/panic-window-percentage` | Percentage | Panic mode window |
| `autoscaling.knative.dev/panic-threshold-percentage` | Percentage | Panic mode threshold |
| `serving.knative.dev/visibility` | `cluster-local` | Internal-only service |

### Eventing Annotations

| Annotation | Values | Description |
|------------|--------|-------------|
| `eventing.knative.dev/broker.class` | `MTChannelBasedBroker`, `Kafka` | Broker implementation |
| `eventing.knative.dev/injection` | `enabled`, `disabled` | Auto-inject default broker |

## Status Conditions

### Service Status

| Condition | Description |
|-----------|-------------|
| `Ready` | Service is fully operational |
| `ConfigurationsReady` | Configuration is ready |
| `RoutesReady` | Routes are configured |

### Revision Status

| Condition | Description |
|-----------|-------------|
| `Ready` | Revision is ready to serve |
| `Active` | Revision is receiving traffic |
| `ContainerHealthy` | Container passed health checks |
| `ResourcesAvailable` | Resources are provisioned |

### Broker Status

| Condition | Description |
|-----------|-------------|
| `Ready` | Broker is operational |
| `Addressable` | Broker has an address |
| `FilterReady` | Filter service is ready |
| `IngressReady` | Ingress is ready |
| `TriggerChannelReady` | Channel is ready |

### Trigger Status

| Condition | Description |
|-----------|-------------|
| `Ready` | Trigger is operational |
| `BrokerReady` | Referenced broker is ready |
| `SubscriberResolved` | Subscriber URI resolved |
| `DependencyReady` | Dependencies are ready |
