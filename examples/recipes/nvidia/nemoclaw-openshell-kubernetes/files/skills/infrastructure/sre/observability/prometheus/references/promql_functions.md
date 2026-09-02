# PromQL Functions Reference

Quick reference for commonly used PromQL functions and patterns.

## Table of Contents

1. [Aggregation Operators](#aggregation-operators)
2. [Rate Functions](#rate-functions)
3. [Aggregation Over Time](#aggregation-over-time)
4. [Math Functions](#math-functions)
5. [Date/Time Functions](#datetime-functions)
6. [Histogram Functions](#histogram-functions)
7. [Label Functions](#label-functions)
8. [Common Patterns](#common-patterns)

---

## Aggregation Operators

Aggregate across series dimensions.

| Operator | Description |
|----------|-------------|
| `sum` | Sum values |
| `min` | Minimum value |
| `max` | Maximum value |
| `avg` | Average value |
| `group` | All values are 1 |
| `stddev` | Standard deviation |
| `stdvar` | Variance |
| `count` | Count series |
| `count_values` | Count series by value |
| `bottomk` | Smallest k elements |
| `topk` | Largest k elements |
| `quantile` | Calculate quantile |

**Syntax:**

```promql
<aggr_op>([parameter,] <vector>) [without|by (<label_list>)]
```

**Examples:**

```promql
# Sum by job
sum by (job) (http_requests_total)

# Average excluding instance
avg without (instance) (node_cpu_seconds_total)

# Top 5 by memory
topk(5, container_memory_usage_bytes)

# Count series per job
count by (job) (up)

# 95th percentile
quantile(0.95, http_request_duration_seconds)
```

---

## Rate Functions

Calculate rates for counters (monotonically increasing values).

| Function | Description |
|----------|-------------|
| `rate(v[d])` | Per-second average rate over duration |
| `irate(v[d])` | Instantaneous rate (last two points) |
| `increase(v[d])` | Total increase over duration |
| `delta(v[d])` | Difference (for gauges) |
| `idelta(v[d])` | Instantaneous difference |
| `deriv(v[d])` | Per-second derivative (gauges) |

**Examples:**

```promql
# Requests per second
rate(http_requests_total[5m])

# Bytes received increase in 1h
increase(node_network_receive_bytes_total[1h])

# CPU delta over 5m
delta(process_cpu_seconds_total[5m])

# Instantaneous rate (for spiky graphs)
irate(http_requests_total[5m])
```

**Best Practice:** Use `rate()` for smooth graphs and alerting. Use `irate()` only when you need to see spikes.

---

## Aggregation Over Time

Aggregate single series across time.

| Function | Description |
|----------|-------------|
| `avg_over_time(v[d])` | Average over time |
| `min_over_time(v[d])` | Minimum over time |
| `max_over_time(v[d])` | Maximum over time |
| `sum_over_time(v[d])` | Sum over time |
| `count_over_time(v[d])` | Count samples |
| `quantile_over_time(q,v[d])` | Quantile over time |
| `stddev_over_time(v[d])` | Std deviation |
| `stdvar_over_time(v[d])` | Variance |
| `last_over_time(v[d])` | Most recent value |
| `present_over_time(v[d])` | 1 if any value exists |

**Examples:**

```promql
# Average CPU over 1h
avg_over_time(node_cpu_seconds_total[1h])

# Max memory in last day
max_over_time(container_memory_usage_bytes[1d])

# 95th percentile latency over 10m
quantile_over_time(0.95, http_request_duration_seconds[10m])

# Count samples in window
count_over_time(up[1h])
```

---

## Math Functions

| Function | Description |
|----------|-------------|
| `abs(v)` | Absolute value |
| `ceil(v)` | Round up |
| `floor(v)` | Round down |
| `round(v, to)` | Round to nearest |
| `clamp(v, min, max)` | Clamp between bounds |
| `clamp_min(v, min)` | Lower bound |
| `clamp_max(v, max)` | Upper bound |
| `exp(v)` | Exponential |
| `ln(v)` | Natural logarithm |
| `log2(v)` | Base-2 logarithm |
| `log10(v)` | Base-10 logarithm |
| `sqrt(v)` | Square root |
| `sgn(v)` | Sign (-1, 0, 1) |

**Examples:**

```promql
# Round to nearest GB
round(container_memory_usage_bytes / 1024 / 1024 / 1024, 0.1)

# Clamp values
clamp(cpu_usage, 0, 100)

# Absolute difference
abs(predicted_value - actual_value)
```

---

## Date/Time Functions

| Function | Description |
|----------|-------------|
| `time()` | Current Unix timestamp |
| `timestamp(v)` | Timestamp of samples |
| `day_of_month()` | Day (1-31) |
| `day_of_week()` | Day (0=Sun to 6=Sat) |
| `day_of_year()` | Day (1-366) |
| `days_in_month()` | Days in month |
| `hour()` | Hour (0-23) |
| `minute()` | Minute (0-59) |
| `month()` | Month (1-12) |
| `year()` | Year |

**Examples:**

```promql
# Seconds since last scrape
time() - timestamp(up)

# Filter by business hours (9-17)
http_requests_total and on() hour() >= 9 < 17

# Filter weekdays only
up and on() day_of_week() >= 1 <= 5
```

---

## Histogram Functions

| Function | Description |
|----------|-------------|
| `histogram_quantile(φ, v)` | Calculate φ-quantile from histogram |
| `histogram_count(v)` | Extract count from native histogram |
| `histogram_sum(v)` | Extract sum from native histogram |
| `histogram_avg(v)` | Calculate average from histogram |
| `histogram_fraction(l,u,v)` | Fraction between bounds |
| `histogram_stddev(v)` | Std deviation from histogram |
| `histogram_stdvar(v)` | Variance from histogram |

**Examples:**

```promql
# 99th percentile latency
histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))

# Median (50th percentile) by job
histogram_quantile(0.5, sum by (job, le) (rate(http_request_duration_seconds_bucket[5m])))

# Average request size
histogram_avg(http_request_size_bytes)
```

**Note:** For classic histograms, aggregate buckets first with `sum by (le)`.

---

## Label Functions

| Function | Description |
|----------|-------------|
| `label_join(v, dst, sep, src...)` | Join labels |
| `label_replace(v, dst, repl, src, regex)` | Regex replace |

**Examples:**

```promql
# Create full address label
label_join(up, "address", ":", "instance", "port")

# Extract host from instance
label_replace(up, "host", "$1", "instance", "([^:]+):.*")

# Rename label
label_replace(metric, "new_name", "$1", "old_name", "(.*)")
```

---

## Common Patterns

### Error Rate

```promql
# Error percentage
sum(rate(http_requests_total{status=~"5.."}[5m]))
/ sum(rate(http_requests_total[5m])) * 100
```

### Availability (SLI)

```promql
# Percentage of successful requests
sum(rate(http_requests_total{status=~"2.."}[5m]))
/ sum(rate(http_requests_total[5m])) * 100
```

### Saturation

```promql
# CPU saturation
100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

# Memory usage percentage
100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)
```

### Latency (Apdex Score)

```promql
# Apdex with 0.5s target
(
  sum(rate(http_request_duration_seconds_bucket{le="0.5"}[5m]))
  + sum(rate(http_request_duration_seconds_bucket{le="2"}[5m]))
) / 2 / sum(rate(http_request_duration_seconds_count[5m]))
```

### Prediction

```promql
# Disk will fill in 4 hours?
predict_linear(node_filesystem_avail_bytes[1h], 4*3600) < 0
```

### Changes Detection

```promql
# Config reloads in last hour
changes(prometheus_config_last_reload_successful[1h])

# Restarts
resets(process_start_time_seconds[1d])
```

### Absent Alerting

```promql
# Alert if metric missing
absent(up{job="myservice"})

# Alert if no data for duration
absent_over_time(up{job="myservice"}[5m])
```

### Vector Matching

```promql
# Divide by matching labels
http_requests_total / on(instance, job) group_left http_requests_limit

# Join with ignoring
node_memory_MemFree_bytes / ignoring(device) node_memory_MemTotal_bytes
```

---

## Operators

### Arithmetic

`+`, `-`, `*`, `/`, `%` (modulo), `^` (power)

### Comparison

`==`, `!=`, `>`, `<`, `>=`, `<=`

Add `bool` for 0/1 result: `http_requests_total > bool 100`

### Logical/Set

`and`, `or`, `unless`

```promql
# Series in both
http_requests_total and http_errors_total

# Series in first but not second
up unless on(instance) alerts

# Either
metric_a or metric_b
```
