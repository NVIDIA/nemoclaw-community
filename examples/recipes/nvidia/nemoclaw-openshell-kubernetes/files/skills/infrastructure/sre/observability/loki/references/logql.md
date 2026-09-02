# LogQL Query Language Reference

LogQL is Loki's Prometheus-inspired query language for logs.

## Query Types

### Log Queries

Filter and return log lines.

### Metric Queries

Extract numeric values and aggregate.

## Stream Selectors

### Label Matchers

| Operator | Description | Example |
|----------|-------------|---------|
| `=` | Exact match | `{job="api"}` |
| `!=` | Not equal | `{job!="debug"}` |
| `=~` | Regex match | `{namespace=~"prod-.*"}` |
| `!~` | Regex not match | `{namespace!~"dev-.*"}` |

### Examples

```logql
# Single label
{job="api-server"}

# Multiple labels (AND)
{job="api-server", env="prod"}

# Regex match
{namespace=~"(prod|staging)-.*"}

# All logs from namespace
{namespace="monitoring"}

# Exclude specific job
{namespace="monitoring", job!="loki"}
```

## Line Filters

Applied after stream selector to filter log content.

| Operator | Description | Example |
|----------|-------------|---------|
| `\|=` | Contains | `\|= "error"` |
| `!=` | Not contains | `!= "debug"` |
| `\|~` | Regex match | `\|~ "err.*"` |
| `!~` | Regex not match | `!~ "debug.*"` |

### Examples

```logql
# Contains "error"
{job="api"} |= "error"

# Case-insensitive contains
{job="api"} |~ "(?i)error"

# Multiple filters (AND)
{job="api"} |= "error" != "timeout"

# Regex filter
{job="api"} |~ "status=[45][0-9]{2}"
```

## Parser Expressions

### JSON Parser

```logql
# Parse entire line as JSON
{job="api"} | json

# Extract specific keys
{job="api"} | json level, message, user_id

# Filter on parsed field
{job="api"} | json | level="error"

# Access nested fields
{job="api"} | json | request_body_user="admin"
```

### Logfmt Parser

```logql
# Parse key=value format
{job="api"} | logfmt

# Filter on parsed field
{job="api"} | logfmt | level="error"
```

### Pattern Parser

```logql
# Extract from structured patterns
{job="nginx"} | pattern "<ip> - - [<_>] \"<method> <path> <_>\" <status> <size>"

# Filter on extracted field
{job="nginx"} | pattern "<ip> - - [<_>] \"<method> <path> <_>\" <status> <size>" | status >= 400
```

### Regexp Parser

```logql
# Extract with named groups
{job="api"} | regexp "(?P<ip>\\d+\\.\\d+\\.\\d+\\.\\d+)"

# Multiple extractions
{job="api"} | regexp "user=(?P<user>\\w+).*status=(?P<status>\\d+)"
```

### Unpack Parser

```logql
# Unpack Loki's structured metadata
{job="api"} | unpack
```

## Label Filter Expressions

After parsing, filter on extracted labels:

| Operator | Description |
|----------|-------------|
| `==`, `=` | Equal |
| `!=` | Not equal |
| `>`, `>=` | Greater than |
| `<`, `<=` | Less than |
| `=~` | Regex match |
| `!~` | Regex not match |

```logql
# String comparison
{job="api"} | json | level="error"

# Numeric comparison
{job="api"} | json | status >= 400

# Regex on label
{job="api"} | json | path=~"/api/v[12]/.*"

# Multiple conditions
{job="api"} | json | level="error" and status >= 500
```

## Line Format Expression

Transform output format:

```logql
# Simple template
{job="api"} | json | line_format "{{.message}}"

# Multiple fields
{job="api"} | json | line_format "{{.timestamp}} [{{.level}}] {{.message}}"

# Conditional formatting
{job="api"} | json | line_format "{{if eq .level \"error\"}}ERROR: {{end}}{{.message}}"

# With functions
{job="api"} | json | line_format "{{.message | upper}}"
```

### Template Functions

| Function | Description | Example |
|----------|-------------|---------|
| `upper` | Uppercase | `{{.msg \| upper}}` |
| `lower` | Lowercase | `{{.msg \| lower}}` |
| `title` | Title case | `{{.msg \| title}}` |
| `trunc N` | Truncate | `{{.msg \| trunc 50}}` |
| `substr S E` | Substring | `{{.msg \| substr 0 10}}` |
| `replace O N` | Replace | `{{.msg \| replace "old" "new"}}` |
| `trim` | Trim spaces | `{{.msg \| trim}}` |
| `regexReplaceAll` | Regex replace | `{{regexReplaceAll "\\d+" .msg "X"}}` |

## Label Format Expression

Rename or modify labels:

```logql
# Rename label
{job="api"} | json | label_format app=job

# Transform label value
{job="api"} | json | label_format level=`{{.level | upper}}`

# Create new label
{job="api"} | json | label_format severity=`{{if eq .level "error"}}high{{else}}low{{end}}`
```

## Drop Labels

Remove labels from output:

```logql
# Drop specific label
{job="api"} | json | drop __error__

# Drop multiple labels
{job="api"} | json | drop __error__, __error_details__
```

## Keep Labels

Keep only specified labels:

```logql
# Keep only these labels
{job="api"} | json | keep level, message
```

## Decolorize

Remove ANSI color codes:

```logql
{job="api"} | decolorize
```

## Metric Queries

### Range Aggregations

| Function | Description |
|----------|-------------|
| `count_over_time` | Count log lines |
| `rate` | Log lines per second |
| `bytes_over_time` | Sum of bytes |
| `bytes_rate` | Bytes per second |
| `absent_over_time` | Returns 1 if no logs exist |

```logql
# Count errors in 5 minutes
count_over_time({job="api"} |= "error" [5m])

# Rate of logs per second
rate({job="api"} [5m])

# Bytes ingested
bytes_over_time({job="api"} [1h])

# Bytes per second
bytes_rate({job="api"} [5m])
```

### Unwrap Expressions

Extract numeric values from logs:

```logql
# Extract duration from logs
{job="api"} | json | unwrap duration

# Apply range function
sum_over_time({job="api"} | json | unwrap response_time [5m])

# Average response time
avg_over_time({job="api"} | json | unwrap latency_ms [5m])

# Percentile
quantile_over_time(0.99, {job="api"} | json | unwrap duration [5m])
```

### Unwrap Aggregation Functions

| Function | Description |
|----------|-------------|
| `sum_over_time` | Sum of values |
| `avg_over_time` | Average |
| `min_over_time` | Minimum |
| `max_over_time` | Maximum |
| `stdvar_over_time` | Variance |
| `stddev_over_time` | Standard deviation |
| `quantile_over_time` | Percentile |
| `first_over_time` | First value |
| `last_over_time` | Last value |

### Vector Aggregations

Aggregate across streams:

| Function | Description |
|----------|-------------|
| `sum` | Sum all values |
| `avg` | Average |
| `min` | Minimum |
| `max` | Maximum |
| `count` | Count series |
| `stddev` | Standard deviation |
| `stdvar` | Variance |
| `topk` | Top K series |
| `bottomk` | Bottom K series |

```logql
# Sum by namespace
sum by (namespace) (rate({job="api"} [5m]))

# Average excluding job
avg without (job) (rate({namespace="prod"} [5m]))

# Top 10 by volume
topk(10, sum by (namespace) (bytes_rate({} [5m])))

# Count unique streams
count(rate({namespace="prod"} [5m]))
```

### Binary Operations

```logql
# Multiply rate
rate({job="api"} [5m]) * 60

# Divide
bytes_rate({job="api"} [5m]) / 1024

# Compare
rate({job="api"} |= "error" [5m]) > 0.1

# Boolean
count_over_time({job="api"} |= "error" [5m]) > 100 and count_over_time({job="api"} |= "error" [5m]) < 1000
```

## Structured Metadata Queries

For OTLP ingested logs:

```logql
# Filter by structured metadata
{job="api"} | severity_text="ERROR"

# Access trace context
{job="api"} | trace_id="abc123"

# Combine with parsers
{job="api"} | json | severity_text="ERROR" | line_format "{{.message}}"
```

## Common Query Patterns

### Error Analysis

```logql
# Error rate
sum(rate({namespace="prod"} |= "error" [5m])) by (job)

# Error percentage
sum(rate({namespace="prod"} |= "error" [5m])) by (job)
/
sum(rate({namespace="prod"} [5m])) by (job) * 100

# Top error messages
topk(10, sum by (message) (count_over_time({job="api"} | json | level="error" [1h])))
```

### Latency Analysis

```logql
# Average response time
avg_over_time({job="api"} | json | unwrap duration_ms [5m])

# P99 latency
quantile_over_time(0.99, {job="api"} | json | unwrap duration_ms [5m])

# Slow requests
{job="api"} | json | duration_ms > 1000
```

### Traffic Analysis

```logql
# Requests per second by endpoint
sum by (path) (rate({job="nginx"} | pattern "<_> <method> <path> <_>" [5m]))

# Traffic by status code
sum by (status) (rate({job="nginx"} | json [5m]))

# Top talkers
topk(10, sum by (client_ip) (bytes_rate({job="nginx"} [5m])))
```

### Kubernetes Analysis

```logql
# Logs from specific pod
{namespace="prod", pod=~"api-.*"}

# Logs from deployment
{namespace="prod", deployment="api-server"}

# Container restarts
{namespace="prod"} |= "Starting container"

# OOMKilled events
{namespace="kube-system"} |= "OOMKilled"
```

## Query Optimization Tips

1. **Use stream selectors first** - Narrow down streams before filtering
2. **Avoid `{}`** - Always specify at least one label
3. **Use line filters before parsers** - Filter raw logs before parsing
4. **Limit time ranges** - Smaller ranges = faster queries
5. **Use `limit`** - Add `| limit 1000` for exploratory queries
6. **Avoid high-cardinality labels** - Use structured metadata instead

## API Query Parameters

```bash
# Range query
GET /loki/api/v1/query_range?query={job="api"}&start=<timestamp>&end=<timestamp>&limit=1000&step=60s

# Instant query
GET /loki/api/v1/query?query={job="api"}&time=<timestamp>&limit=100

# With direction
GET /loki/api/v1/query_range?query={job="api"}&direction=backward&limit=100
```
