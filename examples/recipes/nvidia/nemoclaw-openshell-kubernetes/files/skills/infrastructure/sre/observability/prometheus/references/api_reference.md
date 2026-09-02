# Prometheus HTTP API Reference

Complete API documentation for Prometheus `/api/v1` endpoints.

## Table of Contents

1. [Expression Queries](#expression-queries)
2. [Metadata Endpoints](#metadata-endpoints)
3. [Targets & Service Discovery](#targets--service-discovery)
4. [Rules & Alerts](#rules--alerts)
5. [Status Endpoints](#status-endpoints)
6. [Admin APIs](#admin-apis)
7. [Response Formats](#response-formats)

---

## Expression Queries

### Instant Query

Evaluate expression at single point in time.

```
GET/POST /api/v1/query
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | PromQL expression |
| `time` | rfc3339/unix | No | Evaluation timestamp (default: now) |
| `timeout` | duration | No | Query timeout |
| `limit` | number | No | Max series returned (0=disabled) |

**Example:**

```bash
curl 'http://localhost:9090/api/v1/query?query=up&time=2024-01-01T00:00:00Z'
```

**Response:**

```json
{
  "status": "success",
  "data": {
    "resultType": "vector",
    "result": [
      {
        "metric": {"__name__": "up", "job": "prometheus", "instance": "localhost:9090"},
        "value": [1704067200, "1"]
      }
    ]
  }
}
```

### Range Query

Evaluate expression over time range.

```
GET/POST /api/v1/query_range
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | PromQL expression |
| `start` | rfc3339/unix | Yes | Start timestamp (inclusive) |
| `end` | rfc3339/unix | Yes | End timestamp (inclusive) |
| `step` | duration/float | Yes | Resolution step width |
| `timeout` | duration | No | Query timeout |
| `limit` | number | No | Max series returned |

**Example:**

```bash
curl 'http://localhost:9090/api/v1/query_range?query=up&start=2024-01-01T00:00:00Z&end=2024-01-01T01:00:00Z&step=15s'
```

**Response:**

```json
{
  "status": "success",
  "data": {
    "resultType": "matrix",
    "result": [
      {
        "metric": {"__name__": "up", "job": "prometheus"},
        "values": [
          [1704067200, "1"],
          [1704067215, "1"],
          [1704067230, "1"]
        ]
      }
    ]
  }
}
```

### Format Query

Prettify PromQL expression.

```
GET/POST /api/v1/format_query
```

**Example:**

```bash
curl 'http://localhost:9090/api/v1/format_query?query=foo/bar'
# Returns: "foo / bar"
```

---

## Metadata Endpoints

### Find Series

Return time series matching label sets.

```
GET/POST /api/v1/series
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `match[]` | series_selector | Yes | Repeated selector (at least one) |
| `start` | rfc3339/unix | No | Start timestamp |
| `end` | rfc3339/unix | No | End timestamp |
| `limit` | number | No | Max series returned |

**Example:**

```bash
curl -g 'http://localhost:9090/api/v1/series?match[]=up&match[]=process_start_time_seconds{job="prometheus"}'
```

### Label Names

Return all label names.

```
GET/POST /api/v1/labels
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `start` | rfc3339/unix | No | Start timestamp |
| `end` | rfc3339/unix | No | End timestamp |
| `match[]` | series_selector | No | Filter by series |
| `limit` | number | No | Max labels returned |

**Example:**

```bash
curl 'http://localhost:9090/api/v1/labels'
# Returns: ["__name__", "instance", "job", ...]
```

### Label Values

Return values for specific label.

```
GET /api/v1/label/<label_name>/values
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `start` | rfc3339/unix | No | Start timestamp |
| `end` | rfc3339/unix | No | End timestamp |
| `match[]` | series_selector | No | Filter by series |
| `limit` | number | No | Max values returned |

**Example:**

```bash
curl 'http://localhost:9090/api/v1/label/job/values'
# Returns: ["prometheus", "node", "alertmanager"]
```

### Metric Metadata

Return metadata for metrics.

```
GET /api/v1/metadata
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | number | No | Max metrics returned |
| `limit_per_metric` | number | No | Max metadata per metric |
| `metric` | string | No | Filter by metric name |

**Example:**

```bash
curl 'http://localhost:9090/api/v1/metadata?metric=http_requests_total'
```

**Response:**

```json
{
  "status": "success",
  "data": {
    "http_requests_total": [
      {"type": "counter", "help": "Total HTTP requests", "unit": ""}
    ]
  }
}
```

---

## Targets & Service Discovery

### Targets

Return target discovery state.

```
GET /api/v1/targets
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `state` | string | Filter: `active`, `dropped`, `any` |
| `scrapePool` | string | Filter by scrape pool name |

**Example:**

```bash
curl 'http://localhost:9090/api/v1/targets?state=active'
```

**Response:**

```json
{
  "status": "success",
  "data": {
    "activeTargets": [
      {
        "discoveredLabels": {"__address__": "127.0.0.1:9090"},
        "labels": {"instance": "127.0.0.1:9090", "job": "prometheus"},
        "scrapePool": "prometheus",
        "scrapeUrl": "http://127.0.0.1:9090/metrics",
        "lastScrape": "2024-01-01T00:00:00Z",
        "lastScrapeDuration": 0.05,
        "health": "up"
      }
    ],
    "droppedTargets": []
  }
}
```

### Target Metadata

Return metric metadata from targets.

```
GET /api/v1/targets/metadata
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `match_target` | label_selector | Filter targets |
| `metric` | string | Filter by metric name |
| `limit` | number | Max targets to match |

**Example:**

```bash
curl -G 'http://localhost:9090/api/v1/targets/metadata' \
  --data-urlencode 'metric=go_goroutines' \
  --data-urlencode 'match_target={job="prometheus"}'
```

---

## Rules & Alerts

### Rules

Return alerting and recording rules.

```
GET /api/v1/rules
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `type` | string | `alert` or `record` |
| `rule_name[]` | string | Filter by rule name |
| `rule_group[]` | string | Filter by group name |
| `file[]` | string | Filter by file path |
| `exclude_alerts` | bool | Exclude active alerts |
| `match[]` | label_selector | Filter by configured labels |

**Example:**

```bash
curl 'http://localhost:9090/api/v1/rules?type=alert'
```

**Response:**

```json
{
  "status": "success",
  "data": {
    "groups": [
      {
        "name": "example",
        "file": "/rules.yaml",
        "interval": 60,
        "rules": [
          {
            "name": "HighRequestLatency",
            "query": "job:request_latency_seconds:mean5m > 0.5",
            "duration": 600,
            "labels": {"severity": "page"},
            "annotations": {"summary": "High request latency"},
            "alerts": [],
            "health": "ok",
            "type": "alerting"
          }
        ]
      }
    ]
  }
}
```

### Alerts

Return active alerts.

```
GET /api/v1/alerts
```

**Example:**

```bash
curl 'http://localhost:9090/api/v1/alerts'
```

### Alertmanagers

Return Alertmanager discovery state.

```
GET /api/v1/alertmanagers
```

**Response:**

```json
{
  "status": "success",
  "data": {
    "activeAlertmanagers": [{"url": "http://127.0.0.1:9093/api/v1/alerts"}],
    "droppedAlertmanagers": []
  }
}
```

---

## Status Endpoints

### Config

```
GET /api/v1/status/config
```

Returns currently loaded configuration as YAML.

### Flags

```
GET /api/v1/status/flags
```

Returns CLI flag values.

### Runtime Info

```
GET /api/v1/status/runtimeinfo
```

Returns runtime properties (startTime, goroutineCount, storageRetention, etc).

### Build Info

```
GET /api/v1/status/buildinfo
```

Returns version, revision, branch, buildDate, goVersion.

### TSDB Stats

```
GET /api/v1/status/tsdb?limit=<n>
```

Returns cardinality statistics:

- `headStats`: numSeries, chunkCount, minTime, maxTime
- `seriesCountByMetricName`
- `labelValueCountByLabelName`
- `memoryInBytesByLabelName`
- `seriesCountByLabelValuePair`

### WAL Replay

```
GET /api/v1/status/walreplay
```

Returns WAL replay progress (available before server ready).

---

## Admin APIs

**Note:** Require `--web.enable-admin-api` flag.

### Snapshot

```
POST /api/v1/admin/tsdb/snapshot?skip_head=<bool>
```

Create TSDB snapshot. Returns snapshot directory name.

### Delete Series

```
POST /api/v1/admin/tsdb/delete_series
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `match[]` | series_selector | Yes | Series to delete |
| `start` | rfc3339/unix | No | Start time (default: min) |
| `end` | rfc3339/unix | No | End time (default: max) |

**Example:**

```bash
curl -X POST -g 'http://localhost:9090/api/v1/admin/tsdb/delete_series?match[]=up&match[]=process_start_time_seconds{job="prometheus"}'
```

### Clean Tombstones

```
POST /api/v1/admin/tsdb/clean_tombstones
```

Remove deleted data from disk. Returns 204 on success.

---

## Response Formats

### Result Types

**Instant Vector (vector):**

```json
[
  {
    "metric": {"__name__": "up", "job": "prometheus"},
    "value": [1704067200, "1"]
  }
]
```

**Range Vector (matrix):**

```json
[
  {
    "metric": {"__name__": "up", "job": "prometheus"},
    "values": [[1704067200, "1"], [1704067215, "1"]]
  }
]
```

**Scalar:**

```json
[1704067200, "42"]
```

**String:**

```json
[1704067200, "hello"]
```

### Native Histogram (experimental)

```json
{
  "count": "100",
  "sum": "45.5",
  "buckets": [
    [0, "-0.5", "0.5", "25"],
    [1, "0.5", "1.0", "50"]
  ]
}
```

Boundary rules: 0=open-left, 1=open-right, 2=open-both, 3=closed-both.

---

## Time & Duration Formats

**Timestamps:** RFC3339 (`2024-01-01T00:00:00Z`) or Unix epoch (`1704067200`)

**Durations:** `ms`, `s`, `m`, `h`, `d`, `w`, `y` (e.g., `5m`, `1h30m`, `7d`)

**Series Selectors:** `metric_name{label="value", label2=~"regex.*"}`

Label matchers:

- `=` exact match
- `!=` not equal
- `=~` regex match
- `!~` regex not match
