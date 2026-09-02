# Annotations API Reference

Complete reference for Grafana Annotations HTTP API endpoints.

## Table of Contents

- [Query Annotations](#query-annotations)
- [Create Annotation](#create-annotation)
- [Create Graphite Annotation](#create-graphite-annotation)
- [Update Annotation](#update-annotation)
- [Patch Annotation](#patch-annotation)
- [Delete Annotation](#delete-annotation)
- [Find Annotation by ID](#find-annotation-by-id)
- [Annotation Tags](#annotation-tags)

---

## Query Annotations

```http
GET /api/annotations
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| from | integer | Start time in epoch milliseconds |
| to | integer | End time in epoch milliseconds |
| limit | integer | Max annotations to return (default: 100) |
| alertId | integer | Filter by alert ID |
| dashboardId | integer | Filter by dashboard ID |
| dashboardUID | string | Filter by dashboard UID (recommended) |
| panelId | integer | Filter by panel ID |
| userId | integer | Filter by user who created annotation |
| type | string | `alert` or `annotation` |
| tags | string | Filter by tags (repeat for multiple: `tags=tag1&tags=tag2`) |
| matchAny | boolean | Match any tag (default: false = match all) |

**Example Request:**

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "https://grafana.example.com/api/annotations?from=1506676478816&to=1507281278816&tags=deploy&tags=production&limit=100"
```

**Example Response:**

```json
[
  {
    "id": 1124,
    "alertId": 0,
    "dashboardId": 163,
    "dashboardUID": "cIBgcSjkk",
    "panelId": 2,
    "userId": 1,
    "userName": "admin",
    "newState": "",
    "prevState": "",
    "time": 1507266395000,
    "timeEnd": 1507266395000,
    "text": "Deployment completed",
    "tags": ["deploy", "production"],
    "data": {}
  }
]
```

**Annotation Types:**

- **Dashboard annotation**: Associated with a specific dashboard/panel
- **Organization annotation**: Global annotation visible across all dashboards
- **Alert annotation**: Auto-created when alert state changes

---

## Create Annotation

```http
POST /api/annotations
```

### Dashboard Annotation

```json
{
  "dashboardUID": "cIBgcSjkk",
  "panelId": 2,
  "time": 1507037197339,
  "timeEnd": 1507180805056,
  "tags": ["deploy", "production"],
  "text": "Deployment v2.1.0 completed"
}
```

### Organization Annotation (Global)

Omit `dashboardUID` and `panelId` to create a global annotation:

```json
{
  "time": 1507037197339,
  "tags": ["maintenance", "infrastructure"],
  "text": "Scheduled maintenance window started"
}
```

### Point Annotation (Single Moment)

```json
{
  "dashboardUID": "cIBgcSjkk",
  "time": 1507037197339,
  "tags": ["incident"],
  "text": "Service outage detected"
}
```

### Region Annotation (Time Range)

Include `timeEnd` to create a region:

```json
{
  "dashboardUID": "cIBgcSjkk",
  "time": 1507037197339,
  "timeEnd": 1507040797339,
  "tags": ["maintenance"],
  "text": "Maintenance window"
}
```

**Request Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| text | string | Yes | Annotation text/description |
| time | integer | Yes | Start time in epoch milliseconds |
| timeEnd | integer | No | End time for region annotations |
| dashboardUID | string | No | Dashboard UID (omit for org annotation) |
| dashboardId | integer | No | Dashboard ID (deprecated, use UID) |
| panelId | integer | No | Panel ID |
| tags | array | No | Array of tag strings |
| data | object | No | Custom JSON data |

**Example Response:**

```json
{
  "message": "Annotation added",
  "id": 1125
}
```

---

## Create Graphite Annotation

```http
POST /api/annotations/graphite
```

Compatible with Graphite event format:

```json
{
  "what": "Event - deploy",
  "tags": ["deploy", "production"],
  "when": 1467844481,
  "data": "deploy of main branch happened at Wed Jul 6 22:34:41 UTC 2016"
}
```

**Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| what | string | Yes | Event description |
| tags | array/string | No | Tags (array or space-separated string) |
| when | integer | No | Time in epoch seconds (default: now) |
| data | string | No | Additional event data |

---

## Update Annotation

```http
PUT /api/annotations/:annotationId
```

Replaces all properties of the annotation:

```json
{
  "time": 1507037197339,
  "timeEnd": 1507040797339,
  "text": "Updated annotation text",
  "tags": ["updated", "deploy"]
}
```

---

## Patch Annotation

```http
PATCH /api/annotations/:annotationId
```

Updates only specified properties:

```json
{
  "text": "Partially updated text"
}
```

**Example - Update only tags:**

```json
{
  "tags": ["new-tag", "updated"]
}
```

**Example - Extend time range:**

```json
{
  "timeEnd": 1507050797339
}
```

---

## Delete Annotation

```http
DELETE /api/annotations/:annotationId
```

**Example Request:**

```bash
curl -X DELETE -H "Authorization: Bearer <TOKEN>" \
  "https://grafana.example.com/api/annotations/1124"
```

**Example Response:**

```json
{
  "message": "Annotation deleted"
}
```

---

## Find Annotation by ID

```http
GET /api/annotations/:annotationId
```

**Example Response:**

```json
{
  "id": 1124,
  "alertId": 0,
  "dashboardId": 163,
  "dashboardUID": "cIBgcSjkk",
  "panelId": 2,
  "userId": 1,
  "userName": "admin",
  "newState": "",
  "prevState": "",
  "time": 1507266395000,
  "timeEnd": 1507270000000,
  "text": "Deployment completed",
  "tags": ["deploy", "production"],
  "data": {}
}
```

---

## Annotation Tags

### Get Annotation Tags

```http
GET /api/annotations/tags
```

Returns all unique tags used in annotations.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| limit | integer | Max tags to return (default: 100) |
| tag | string | Filter tags containing this string |

**Example Response:**

```json
{
  "result": {
    "tags": [
      {"tag": "deploy", "count": 15},
      {"tag": "production", "count": 12},
      {"tag": "incident", "count": 5},
      {"tag": "maintenance", "count": 8}
    ]
  }
}
```

---

## Common Patterns

### Deploy Marker

```python
import time
import requests

def create_deploy_annotation(grafana_url, token, dashboard_uid, version, env):
    response = requests.post(
        f"{grafana_url}/api/annotations",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json={
            "dashboardUID": dashboard_uid,
            "time": int(time.time() * 1000),
            "tags": ["deploy", env, f"v{version}"],
            "text": f"Deployed version {version} to {env}"
        }
    )
    return response.json()
```

### Maintenance Window

```python
def create_maintenance_window(grafana_url, token, start_ms, end_ms, description):
    response = requests.post(
        f"{grafana_url}/api/annotations",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json={
            "time": start_ms,
            "timeEnd": end_ms,
            "tags": ["maintenance", "scheduled"],
            "text": description
        }
    )
    return response.json()
```

### Clean Up Old Annotations

```python
def delete_old_annotations(grafana_url, token, older_than_ms, tags=None):
    params = {
        "from": 0,
        "to": older_than_ms,
        "limit": 1000
    }
    if tags:
        params["tags"] = tags

    response = requests.get(
        f"{grafana_url}/api/annotations",
        headers={"Authorization": f"Bearer {token}"},
        params=params
    )

    annotations = response.json()
    for ann in annotations:
        requests.delete(
            f"{grafana_url}/api/annotations/{ann['id']}",
            headers={"Authorization": f"Bearer {token}"}
        )

    return len(annotations)
```
