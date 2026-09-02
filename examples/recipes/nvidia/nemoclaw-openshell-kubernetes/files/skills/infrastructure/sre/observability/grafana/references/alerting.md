# Alerting API Reference

Complete reference for Grafana Alerting HTTP API endpoints (Grafana 9.0+).

## Table of Contents

- [Alert Rules](#alert-rules)
- [Rule Groups](#rule-groups)
- [Contact Points](#contact-points)
- [Notification Policies](#notification-policies)
- [Mute Timings](#mute-timings)
- [Silences](#silences)
- [Active Alerts](#active-alerts)
- [Templates](#templates)

---

## Alert Rules

### List All Alert Rules

```http
GET /api/v1/provisioning/alert-rules
```

**Example Response:**

```json
[
  {
    "id": 1,
    "uid": "cIBgcSjkk",
    "orgID": 1,
    "folderUID": "l3KqBxCMz",
    "ruleGroup": "CPU Alerts",
    "title": "High CPU Alert",
    "condition": "B",
    "data": [...],
    "updated": "2024-06-20T14:22:00Z",
    "noDataState": "OK",
    "execErrState": "OK",
    "for": "5m",
    "annotations": {"summary": "CPU usage is high"},
    "labels": {"severity": "warning"},
    "provenance": ""
  }
]
```

### Get Alert Rule by UID

```http
GET /api/v1/provisioning/alert-rules/:uid
```

### Create Alert Rule

```http
POST /api/v1/provisioning/alert-rules
```

**Complete Example:**

```json
{
  "title": "High Memory Usage",
  "ruleGroup": "Memory Alerts",
  "folderUID": "l3KqBxCMz",
  "noDataState": "NoData",
  "execErrState": "Error",
  "for": "5m",
  "orgId": 1,
  "condition": "C",
  "annotations": {
    "summary": "Memory usage above 90%",
    "description": "Host {{ $labels.instance }} memory usage is {{ $values.A }}%",
    "runbook_url": "https://wiki.example.com/runbooks/memory"
  },
  "labels": {
    "severity": "critical",
    "team": "platform"
  },
  "data": [
    {
      "refId": "A",
      "queryType": "",
      "relativeTimeRange": {"from": 600, "to": 0},
      "datasourceUid": "prometheus-uid",
      "model": {
        "expr": "(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100",
        "instant": false,
        "intervalMs": 1000,
        "maxDataPoints": 43200,
        "refId": "A"
      }
    },
    {
      "refId": "B",
      "queryType": "",
      "relativeTimeRange": {"from": 600, "to": 0},
      "datasourceUid": "-100",
      "model": {
        "type": "reduce",
        "expression": "A",
        "reducer": "last",
        "refId": "B"
      }
    },
    {
      "refId": "C",
      "queryType": "",
      "relativeTimeRange": {"from": 0, "to": 0},
      "datasourceUid": "-100",
      "model": {
        "type": "threshold",
        "expression": "B",
        "refId": "C",
        "conditions": [
          {
            "evaluator": {"type": "gt", "params": [90]},
            "operator": {"type": "and"},
            "query": {"params": ["C"]},
            "reducer": {"type": "last"}
          }
        ]
      }
    }
  ]
}
```

### Update Alert Rule

```http
PUT /api/v1/provisioning/alert-rules/:uid
```

### Delete Alert Rule

```http
DELETE /api/v1/provisioning/alert-rules/:uid
```

---

## Rule Groups

### Get Rule Group

```http
GET /api/v1/provisioning/folder/:folderUid/rule-groups/:group
```

### Update Rule Group

```http
PUT /api/v1/provisioning/folder/:folderUid/rule-groups/:group
```

**Request Body:**

```json
{
  "name": "CPU Alerts",
  "interval": "1m",
  "rules": [...]
}
```

---

## Contact Points

### List Contact Points

```http
GET /api/v1/provisioning/contact-points
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| name | string | Filter by name |

**Example Response:**

```json
[
  {
    "uid": "email-receiver",
    "name": "email-receiver",
    "type": "email",
    "settings": {
      "addresses": "alerts@example.com",
      "singleEmail": false
    },
    "disableResolveMessage": false
  }
]
```

### Create Contact Point

```http
POST /api/v1/provisioning/contact-points
```

**Email Example:**

```json
{
  "name": "ops-team-email",
  "type": "email",
  "settings": {
    "addresses": "ops@example.com;oncall@example.com",
    "singleEmail": true
  },
  "disableResolveMessage": false
}
```

**Slack Example:**

```json
{
  "name": "slack-alerts",
  "type": "slack",
  "settings": {
    "url": "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXX",
    "recipient": "#alerts",
    "username": "Grafana",
    "icon_emoji": ":grafana:",
    "mentionUsers": "U12345678",
    "mentionGroups": "S12345678",
    "mentionChannel": "here"
  }
}
```

**PagerDuty Example:**

```json
{
  "name": "pagerduty",
  "type": "pagerduty",
  "settings": {
    "integrationKey": "your-integration-key",
    "severity": "critical",
    "class": "ping failure",
    "component": "Grafana",
    "group": "Production"
  }
}
```

**Webhook Example:**

```json
{
  "name": "custom-webhook",
  "type": "webhook",
  "settings": {
    "url": "https://your-endpoint.com/alerts",
    "httpMethod": "POST",
    "username": "grafana",
    "password": "secret",
    "maxAlerts": 10
  }
}
```

### Update Contact Point

```http
PUT /api/v1/provisioning/contact-points/:uid
```

### Delete Contact Point

```http
DELETE /api/v1/provisioning/contact-points/:uid
```

---

## Notification Policies

### Get Notification Policy Tree

```http
GET /api/v1/provisioning/policies
```

**Example Response:**

```json
{
  "receiver": "email-receiver",
  "group_by": ["grafana_folder", "alertname"],
  "routes": [
    {
      "receiver": "slack-alerts",
      "object_matchers": [["severity", "=", "critical"]],
      "continue": false,
      "group_wait": "30s",
      "group_interval": "5m",
      "repeat_interval": "4h"
    }
  ],
  "group_wait": "30s",
  "group_interval": "5m",
  "repeat_interval": "4h"
}
```

### Update Notification Policy Tree

```http
PUT /api/v1/provisioning/policies
```

**Request Body:**

```json
{
  "receiver": "email-receiver",
  "group_by": ["grafana_folder", "alertname"],
  "routes": [
    {
      "receiver": "pagerduty",
      "object_matchers": [
        ["severity", "=", "critical"],
        ["team", "=", "platform"]
      ],
      "continue": false,
      "group_wait": "10s",
      "group_interval": "1m",
      "repeat_interval": "1h"
    },
    {
      "receiver": "slack-alerts",
      "object_matchers": [["severity", "=", "warning"]],
      "continue": true,
      "mute_time_intervals": ["weekends"]
    }
  ],
  "group_wait": "30s",
  "group_interval": "5m",
  "repeat_interval": "4h"
}
```

---

## Mute Timings

### List Mute Timings

```http
GET /api/v1/provisioning/mute-timings
```

### Create Mute Timing

```http
POST /api/v1/provisioning/mute-timings
```

**Weekend Mute Example:**

```json
{
  "name": "weekends",
  "time_intervals": [
    {
      "weekdays": ["saturday", "sunday"]
    }
  ]
}
```

**Business Hours Only Example:**

```json
{
  "name": "outside-business-hours",
  "time_intervals": [
    {
      "weekdays": ["monday:friday"],
      "times": [
        {"start_time": "00:00", "end_time": "09:00"},
        {"start_time": "17:00", "end_time": "24:00"}
      ]
    },
    {
      "weekdays": ["saturday", "sunday"]
    }
  ]
}
```

### Update Mute Timing

```http
PUT /api/v1/provisioning/mute-timings/:name
```

### Delete Mute Timing

```http
DELETE /api/v1/provisioning/mute-timings/:name
```

---

## Silences

### List Silences

```http
GET /api/alertmanager/grafana/api/v2/silences
```

### Create Silence

```http
POST /api/alertmanager/grafana/api/v2/silences
```

**Request Body:**

```json
{
  "matchers": [
    {"name": "alertname", "value": "HighCPU", "isRegex": false, "isEqual": true},
    {"name": "instance", "value": "server-01", "isRegex": false, "isEqual": true}
  ],
  "startsAt": "2024-06-20T10:00:00Z",
  "endsAt": "2024-06-20T18:00:00Z",
  "createdBy": "admin",
  "comment": "Scheduled maintenance window"
}
```

### Delete Silence

```http
DELETE /api/alertmanager/grafana/api/v2/silence/:silenceId
```

---

## Active Alerts

### Get All Active Alerts

```http
GET /api/alertmanager/grafana/api/v2/alerts
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| active | boolean | Show active alerts |
| silenced | boolean | Show silenced alerts |
| inhibited | boolean | Show inhibited alerts |
| filter | string | Filter by label matchers |
| receiver | string | Filter by receiver |

### Get Alert Groups

```http
GET /api/alertmanager/grafana/api/v2/alerts/groups
```

---

## Templates

### List Templates

```http
GET /api/v1/provisioning/templates
```

### Create/Update Template

```http
PUT /api/v1/provisioning/templates/:name
```

**Request Body:**

```json
{
  "template": "{{ define \"custom_email.subject\" }}\n[{{ .Status | toUpper }}{{ if eq .Status \"firing\" }}:{{ .Alerts.Firing | len }}{{ end }}] {{ .GroupLabels.alertname }}\n{{ end }}"
}
```

### Delete Template

```http
DELETE /api/v1/provisioning/templates/:name
```

---

## Expression Types

For alert rule data queries, use `datasourceUid: "-100"` for expression types:

| Type | Description |
|------|-------------|
| `reduce` | Aggregate time series (last, mean, min, max, sum, count) |
| `threshold` | Compare against threshold values |
| `classic_conditions` | Legacy condition format |
| `math` | Mathematical operations on results |
| `resample` | Resample time series data |

**Reduce Example:**

```json
{
  "refId": "B",
  "datasourceUid": "-100",
  "model": {
    "type": "reduce",
    "expression": "A",
    "reducer": "last",
    "refId": "B"
  }
}
```

**Threshold Example:**

```json
{
  "refId": "C",
  "datasourceUid": "-100",
  "model": {
    "type": "threshold",
    "expression": "B",
    "conditions": [
      {"evaluator": {"type": "gt", "params": [80]}}
    ]
  }
}
```
