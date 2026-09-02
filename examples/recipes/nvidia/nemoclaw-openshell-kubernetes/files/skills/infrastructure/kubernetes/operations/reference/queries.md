# Observability Queries

Query examples for TraceQL, PromQL, and LogQL in Grafana.

## Query Parameters from Manifest

Check `cluster/manifests/<application>/` for:
- `namespace` → `overlays/dev/namespace.yaml` or `overlays/dev/kustomization.yaml`
- `app.kubernetes.io/name` → pod labels in `base/deployment.yaml`
- `OTEL_SERVICE_NAME` → env in `base/deployment.yaml` (for traces)

| Signal | Manifest Source | Query Label |
|--------|-----------------|-------------|
| Metrics | `namespace` | `{namespace="..."}` |
| Logs | `app.kubernetes.io/name` | `{grouping="kubernetes.{ns}.{name}"}` |
| Traces | `OTEL_SERVICE_NAME` | `{ resource.service.name = "..." }` |
| Profiles | `OTEL_SERVICE_NAME` | service name in Pyroscope |

## Grafana Dashboards

| Dashboard | Path | Purpose |
|-----------|------|---------|
| Namespace | kubernetes/namespace | Per-namespace overview |
| Workload | kubernetes/workload | Deployment/StatefulSet metrics |
| Pod | kubernetes/pod | Individual pod details |
| Cluster | kubernetes/cluster | Overall cluster health |
| Node | kubernetes/node | Per-node resource usage |

## Non-Interactive Access

When a browser is unavailable, Grafana's datasource proxy serves the same queries over HTTP.
This still goes through Grafana, so it does not violate the rule against querying backends directly — the backend Services are unreachable from outside the mesh anyway.

```
curl -sk -G "https://grafana.minikube.127.0.0.1.nip.io/api/datasources/proxy/uid/prometheus/api/v1/query" \
  --data-urlencode 'query=max by (namespace,container) (max_over_time(container_memory_working_set_bytes{container!=""}[2d]))'
```

`GET /api/datasources` lists the datasource `uid` values to substitute; the path after `uid/{uid}/` is the backend's own API path.

Aggregate with `max by (...)` when a workload has churned pods — the raw series carry a distinct `id` label per container instance, so an unaggregated query returns one row per restart.
Keep `pod` in the `by` clause when sizing a single workload, then reduce across that workload's pods: the metric carries no owner label, so several workloads sharing a container name in one namespace collapse into one series and the lightest gets the heaviest one's peak.

Keep range windows within Mimir's `compactor_blocks_retention_period` (see `cluster/manifests/mimir/overlays/dev/files/mimir.yaml`) — `max_total_query_length` accepts a far longer range, so a window past retention silently resolves to whatever is retained instead of failing.

## TraceQL (Tempo)

Use in Grafana Explore with Tempo datasource:

```
# Find traces by service name
{ resource.service.name = "bakery" }

# Find slow error traces
{ resource.service.name = "bakery" && status = error } | duration > 1s

# Find traces by HTTP path pattern
{ span.http.target =~ "/api/users.*" }
```

To find a trace by ID: paste the 32-character traceid directly into Tempo's search box (not TraceQL).

## PromQL (Mimir)

Use in Grafana Explore with Mimir datasource:

```promql
# Container CPU usage by pod (excluding infra containers)
sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="bakery", container!~"POD|istio-proxy"}[5m]))

# Container CPU throttled-period share (used for limits.cpu decisions)
sum by (namespace,pod,container) (increase(container_cpu_cfs_throttled_periods_total{container!=""}[2d]))
  / sum by (namespace,pod,container) (increase(container_cpu_cfs_periods_total{container!=""}[2d]))
# Stops at the per-pod ratio — reduce across a workload's own pods yourself, since a container
# name does not identify a workload. Reduce the ratios, not the numerator and denominator
# separately, or the largest of each can come from different pods. Keeps istio-proxy, unlike
# its neighbours, because a sidecar's own quota is what throttles it.

# Container memory usage (excluding infra containers)
sum by (pod) (container_memory_usage_bytes{namespace="bakery", container!~"POD|istio-proxy"})

# Container memory working set (used for OOMKill decisions)
sum by (pod) (container_memory_working_set_bytes{namespace="bakery", container!~"POD|istio-proxy"})
# Drop the istio-proxy exclusion when comparing against pod-level requests or reasoning
# about eviction — the injected sidecar counts toward both.

# HTTP request rate by status code
sum by (response_code) (rate(istio_requests_total{destination_workload_namespace="bakery"}[5m]))

# HTTP request latency (p99)
histogram_quantile(0.99, sum by (le) (rate(istio_request_duration_milliseconds_bucket{destination_workload_namespace="bakery"}[5m])))

# Endpoint reachability (blackbox)
probe_success{job="blackbox-exporter"}
```

## LogQL (Loki)

Use in Grafana Explore with Loki datasource.

Label format: `{grouping="kubernetes.{namespace}.{app-name}"}`

```logql
# Logs from specific app in namespace
{grouping="kubernetes.bakery.bakery"}

# Logs from all apps in namespace
{grouping=~"kubernetes.bakery.*"}

# Search for errors
{grouping=~"kubernetes.bakery.*"} |= "error"

# JSON log parsing with traceid extraction
{grouping=~"kubernetes.bakery.*"} | json | traceid != ""

# Filter by pod name (from JSON field)
{grouping=~"kubernetes.bakery.*"} | json | kubernetes_pod_name=~"bakery-.*"

# Error rate over time
count_over_time({grouping=~"kubernetes.bakery.*"} |= "error"[5m])
```

## Common Debugging Patterns

**Errors in logs** → Find traceid, then trace:

```logql
{grouping=~"kubernetes.bakery.*"} |= "error" | json
```
→ Extract `traceid`, paste into Tempo search box

**Latency/5xx** → Search traces:

```
{ resource.service.name = "bakery" && status = error } | duration > 1s
```

**Resource saturation** → Check metrics:

```promql
sum by (pod) (container_memory_working_set_bytes{namespace="bakery", container!~"POD|istio-proxy"})
```

**Tip**: Align Grafana time ranges across all signals when correlating.
