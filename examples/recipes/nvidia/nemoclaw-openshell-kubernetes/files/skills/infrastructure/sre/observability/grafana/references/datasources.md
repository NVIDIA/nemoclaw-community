# Data Sources API Reference

Complete reference for Grafana Data Source HTTP API endpoints.

## Table of Contents

- [List Data Sources](#list-data-sources)
- [Get Data Source](#get-data-source)
- [Create Data Source](#create-data-source)
- [Update Data Source](#update-data-source)
- [Delete Data Source](#delete-data-source)
- [Query Data Source](#query-data-source)
- [Health Check](#health-check)
- [Data Source Resources](#data-source-resources)

---

## List Data Sources

```http
GET /api/datasources
```

**Note:** Default max returned is 5000. Pagination not currently supported.

**Example Response:**

```json
[
  {
    "id": 1,
    "uid": "PE9C8AA5B1A6E7E89",
    "orgId": 1,
    "name": "Prometheus",
    "type": "prometheus",
    "typeName": "Prometheus",
    "typeLogoUrl": "public/app/plugins/datasource/prometheus/img/prometheus_logo.svg",
    "access": "proxy",
    "url": "http://prometheus:9090",
    "user": "",
    "database": "",
    "basicAuth": false,
    "isDefault": true,
    "jsonData": {
      "httpMethod": "POST",
      "manageAlerts": true,
      "prometheusType": "Prometheus"
    },
    "readOnly": false
  }
]
```

---

## Get Data Source

### By ID (Deprecated)

```http
GET /api/datasources/:id
```

### By UID (Recommended)

```http
GET /api/datasources/uid/:uid
```

### By Name

```http
GET /api/datasources/name/:name
```

**Example Response:**

```json
{
  "id": 1,
  "uid": "PE9C8AA5B1A6E7E89",
  "orgId": 1,
  "name": "Prometheus",
  "type": "prometheus",
  "access": "proxy",
  "url": "http://prometheus:9090",
  "basicAuth": false,
  "isDefault": true,
  "jsonData": {
    "httpMethod": "POST",
    "manageAlerts": true
  },
  "secureJsonFields": {},
  "version": 1,
  "readOnly": false
}
```

---

## Create Data Source

```http
POST /api/datasources
```

### Prometheus Example

```json
{
  "name": "Prometheus",
  "type": "prometheus",
  "url": "http://prometheus:9090",
  "access": "proxy",
  "basicAuth": false,
  "isDefault": true,
  "jsonData": {
    "httpMethod": "POST",
    "manageAlerts": true,
    "prometheusType": "Prometheus",
    "prometheusVersion": "2.47.0"
  }
}
```

### InfluxDB Example

```json
{
  "name": "InfluxDB",
  "type": "influxdb",
  "url": "http://influxdb:8086",
  "access": "proxy",
  "basicAuth": false,
  "database": "telegraf",
  "jsonData": {
    "httpMode": "POST",
    "version": "Flux"
  },
  "secureJsonData": {
    "token": "your-influxdb-token"
  }
}
```

### PostgreSQL Example

```json
{
  "name": "PostgreSQL",
  "type": "postgres",
  "url": "postgres:5432",
  "access": "proxy",
  "user": "grafana",
  "database": "grafana",
  "basicAuth": false,
  "jsonData": {
    "sslmode": "disable",
    "maxOpenConns": 100,
    "maxIdleConns": 100,
    "connMaxLifetime": 14400
  },
  "secureJsonData": {
    "password": "your-password"
  }
}
```

### Loki Example

```json
{
  "name": "Loki",
  "type": "loki",
  "url": "http://loki:3100",
  "access": "proxy",
  "basicAuth": false,
  "jsonData": {
    "maxLines": 1000,
    "derivedFields": [
      {
        "matcherRegex": "traceID=(\\w+)",
        "name": "TraceID",
        "url": "${__value.raw}",
        "datasourceUid": "tempo-uid"
      }
    ]
  }
}
```

### CloudWatch Example

```json
{
  "name": "CloudWatch",
  "type": "cloudwatch",
  "access": "proxy",
  "jsonData": {
    "authType": "default",
    "defaultRegion": "us-east-1"
  }
}
```

### Azure Monitor Example

```json
{
  "name": "Azure Monitor",
  "type": "grafana-azure-monitor-datasource",
  "access": "proxy",
  "jsonData": {
    "cloudName": "azuremonitor",
    "tenantId": "your-tenant-id",
    "clientId": "your-client-id",
    "subscriptionId": "your-subscription-id"
  },
  "secureJsonData": {
    "clientSecret": "your-client-secret"
  }
}
```

---

## Update Data Source

### By ID (Deprecated)

```http
PUT /api/datasources/:id
```

### By UID (Recommended)

```http
PUT /api/datasources/uid/:uid
```

**Request Body:** Same as create, include all fields.

---

## Delete Data Source

### By ID (Deprecated)

```http
DELETE /api/datasources/:id
```

### By UID (Recommended)

```http
DELETE /api/datasources/uid/:uid
```

### By Name

```http
DELETE /api/datasources/name/:name
```

---

## Query Data Source

```http
POST /api/ds/query
```

Execute queries against any data source with a backend implementation.

### Prometheus Query Example

```json
{
  "queries": [
    {
      "refId": "A",
      "datasource": {
        "type": "prometheus",
        "uid": "PE9C8AA5B1A6E7E89"
      },
      "expr": "up{job=\"prometheus\"}",
      "instant": false,
      "range": true,
      "intervalMs": 15000,
      "maxDataPoints": 1000
    }
  ],
  "from": "now-1h",
  "to": "now"
}
```

### Loki Query Example

```json
{
  "queries": [
    {
      "refId": "A",
      "datasource": {
        "type": "loki",
        "uid": "loki-uid"
      },
      "expr": "{job=\"nginx\"} |= \"error\"",
      "queryType": "range",
      "maxLines": 1000
    }
  ],
  "from": "now-1h",
  "to": "now"
}
```

### SQL Query Example

```json
{
  "queries": [
    {
      "refId": "A",
      "datasource": {
        "type": "postgres",
        "uid": "postgres-uid"
      },
      "rawSql": "SELECT time, value FROM metrics WHERE $__timeFilter(time)",
      "format": "time_series"
    }
  ],
  "from": "now-1h",
  "to": "now"
}
```

**Response Structure:**

```json
{
  "results": {
    "A": {
      "frames": [
        {
          "schema": {
            "refId": "A",
            "fields": [
              {"name": "time", "type": "time"},
              {"name": "value", "type": "number"}
            ]
          },
          "data": {
            "values": [
              [1644488152084, 1644488212084],
              [0.95, 0.97]
            ]
          }
        }
      ]
    }
  }
}
```

---

## Health Check

```http
GET /api/datasources/uid/:uid/health
```

**Example Response (Success):**

```json
{
  "status": "OK",
  "message": "Successfully connected to Prometheus"
}
```

**Example Response (Error):**

```json
{
  "status": "ERROR",
  "message": "Post \"http://prometheus:9090/api/v1/query\": dial tcp: connection refused"
}
```

---

## Data Source Resources

Access data source-specific resources (metrics, dimensions, etc.).

```http
GET /api/datasources/uid/:uid/resources/:resource
```

### CloudWatch Dimension Keys Example

```bash
GET /api/datasources/uid/cloudwatch-uid/resources/dimension-keys?region=us-east-1&namespace=AWS/EC2
```

### Prometheus Label Values Example

```bash
GET /api/datasources/uid/prometheus-uid/resources/api/v1/label/__name__/values
```

---

## Common Data Source Types

| Type | Plugin ID |
|------|-----------|
| Prometheus | `prometheus` |
| Loki | `loki` |
| InfluxDB | `influxdb` |
| PostgreSQL | `postgres` |
| MySQL | `mysql` |
| Elasticsearch | `elasticsearch` |
| CloudWatch | `cloudwatch` |
| Azure Monitor | `grafana-azure-monitor-datasource` |
| Google Cloud Monitoring | `stackdriver` |
| Graphite | `graphite` |
| Tempo | `tempo` |
| Jaeger | `jaeger` |
| Zipkin | `zipkin` |
