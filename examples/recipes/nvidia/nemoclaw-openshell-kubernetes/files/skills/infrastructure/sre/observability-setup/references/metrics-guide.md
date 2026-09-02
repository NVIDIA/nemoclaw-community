<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Nik Kale -->
<!-- SPDX-License-Identifier: MIT -->

# Metrics Design Guide

How to design and implement effective metrics.

## Metric Methodologies

### RED Method (Request-Driven Services)

For services that handle requests (APIs, web servers).

| Metric       | What It Measures           | Alert On                      |
| ------------ | -------------------------- | ----------------------------- |
| **R**ate     | Requests per second        | Unusual traffic (high or low) |
| **E**rrors   | Failed requests per second | Error rate > threshold        |
| **D**uration | Request latency            | Latency > SLO                 |

**Implementation**:

```
# Rate
http_requests_total{method, endpoint, status}

# Errors
http_requests_total{status=~"5.."}

# Duration
http_request_duration_seconds{method, endpoint}
```

### USE Method (Resources)

For resources (CPU, memory, queues, pools).

| Metric          | What It Measures           | Alert On             |
| --------------- | -------------------------- | -------------------- |
| **U**tilization | % of resource in use       | Sustained high usage |
| **S**aturation  | Work waiting (queue depth) | Growing queue        |
| **E**rrors      | Error count                | Any errors           |

**Implementation**:

```
# Utilization
cpu_usage_percent
memory_usage_percent
connection_pool_used / connection_pool_total

# Saturation
queue_depth
goroutines_count
thread_pool_queue_size

# Errors
connection_errors_total
oom_events_total
```

### The Four Golden Signals (Google SRE)

| Signal     | Description               | Metrics                    |
| ---------- | ------------------------- | -------------------------- |
| Latency    | Time to service a request | request_duration histogram |
| Traffic    | Demand on the system      | requests_per_second        |
| Errors     | Rate of failed requests   | error_rate                 |
| Saturation | How "full" the service is | resource_utilization       |

---

## Choosing the Right Metric Type

### Counter

Use for cumulative values that only increase.

```
# Good counter use cases
http_requests_total
errors_total
bytes_sent_total
cache_hits_total

# Bad (don't use counter)
active_connections  # Use gauge - goes up and down
queue_size          # Use gauge
```

**Query patterns**:

```promql
# Rate of increase (requests/sec)
rate(http_requests_total[5m])

# Increase over time period
increase(http_requests_total[1h])
```

### Gauge

Use for values that can go up and down.

```
# Good gauge use cases
temperature_celsius
active_connections
queue_size
memory_usage_bytes
goroutines_count
```

**Query patterns**:

```promql
# Current value
node_memory_usage_bytes

# Average over time
avg_over_time(temperature_celsius[1h])
```

### Histogram

Use for measuring distributions (latency, sizes).

```
# Good histogram use cases
http_request_duration_seconds
response_size_bytes
batch_processing_time_seconds
```

**Important**: Choose bucket boundaries carefully:

```python
# For latency (seconds)
buckets = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]

# For sizes (bytes)
buckets = [100, 1000, 10000, 100000, 1000000]
```

**Query patterns**:

```promql
# 95th percentile latency
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# Average latency
rate(http_request_duration_seconds_sum[5m])
/
rate(http_request_duration_seconds_count[5m])
```

---

## Cardinality Management

High cardinality = explosion of time series = performance problems.

### Bad (High Cardinality)

```python
# DON'T: user_id as label (millions of values)
REQUEST_COUNT.labels(
    method='GET',
    endpoint='/api/users',
    user_id=user.id  # BAD: unbounded cardinality
).inc()

# DON'T: full URL path
REQUEST_COUNT.labels(
    path=request.path  # BAD: /users/123, /users/456, etc.
).inc()
```

### Good (Bounded Cardinality)

```python
# DO: bounded label values
REQUEST_COUNT.labels(
    method='GET',           # ~5 values
    endpoint='/api/users',  # defined set of endpoints
    status='200'            # ~10 values
).inc()

# DO: normalize paths
def normalize_path(path):
    # /users/123 -> /users/:id
    return re.sub(r'/\d+', '/:id', path)
```

### Cardinality Guidelines

| Label Type  | Max Values | Example                 |
| ----------- | ---------- | ----------------------- |
| HTTP method | 5-10       | GET, POST, PUT, DELETE  |
| Status code | 10-20      | 200, 201, 400, 404, 500 |
| Endpoint    | 50-100     | /api/users, /api/orders |
| Region      | 5-20       | us-east-1, eu-west-1    |
| Service     | 10-50      | auth, api, worker       |

---

## Prometheus Best Practices

### Naming Conventions

```
# Format
<namespace>_<subsystem>_<name>_<unit>

# Examples
http_server_requests_total
http_server_request_duration_seconds
db_pool_connections_active
cache_operations_total
```

### Units

Always include unit in name:

- `_seconds` for durations
- `_bytes` for sizes
- `_total` for counters
- `_ratio` for ratios (0-1)
- `_percent` for percentages (0-100)

### Recording Rules

Pre-calculate expensive queries:

```yaml
groups:
  - name: service-slos
    rules:
      # Pre-calculate error rate
      - record: service:http_error_rate:5m
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m])) by (service)
          /
          sum(rate(http_requests_total[5m])) by (service)

      # Pre-calculate latency percentiles
      - record: service:http_latency_p99:5m
        expr: |
          histogram_quantile(0.99,
            sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service)
          )
```

---

## Common Metrics by Service Type

### Web/API Service

```
# Requests
http_requests_total{method, endpoint, status}
http_request_duration_seconds{method, endpoint}
http_request_size_bytes{method, endpoint}
http_response_size_bytes{method, endpoint}

# Connections
http_connections_active
http_connections_total

# Errors
http_errors_total{type}
```

### Database

```
# Queries
db_queries_total{operation, table}
db_query_duration_seconds{operation}

# Connections
db_connections_active
db_connections_idle
db_connections_max

# Errors
db_errors_total{type}
```

### Cache (Redis/Memcached)

```
# Operations
cache_operations_total{operation, status}
cache_operation_duration_seconds{operation}

# Hit rate
cache_hits_total
cache_misses_total

# Resources
cache_memory_used_bytes
cache_keys_count
cache_evictions_total
```

### Queue (Kafka/RabbitMQ)

```
# Messages
queue_messages_published_total{topic}
queue_messages_consumed_total{topic}
queue_message_processing_duration_seconds{topic}

# Lag
queue_consumer_lag{topic, partition}
queue_messages_pending{queue}

# Errors
queue_errors_total{type}
```
