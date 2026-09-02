# Dashboards API Reference

Complete reference for Grafana Dashboard HTTP API endpoints.

## Table of Contents

- [Search Dashboards](#search-dashboards)
- [Get Dashboard by UID](#get-dashboard-by-uid)
- [Create/Update Dashboard](#createupdate-dashboard)
- [Delete Dashboard](#delete-dashboard)
- [Get Dashboard Versions](#get-dashboard-versions)
- [Restore Dashboard Version](#restore-dashboard-version)
- [Dashboard Permissions](#dashboard-permissions)
- [Public/Shared Dashboards](#publicshared-dashboards)

---

## Search Dashboards

```http
GET /api/search
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| query | string | Search query to filter by title |
| tag | string | Filter by tag (can be repeated) |
| type | string | `dash-db` for dashboards, `dash-folder` for folders |
| dashboardIds | array | List of dashboard IDs to search for |
| dashboardUIDs | array | List of dashboard UIDs to search for |
| folderIds | array | Filter by folder IDs |
| folderUIDs | array | Filter by folder UIDs |
| starred | boolean | Filter by starred dashboards |
| limit | integer | Maximum results (default: 1000) |
| page | integer | Page number for pagination |
| sort | string | `alpha-asc`, `alpha-desc` |

**Example Request:**

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "https://grafana.example.com/api/search?type=dash-db&query=production&tag=monitoring&limit=50"
```

**Example Response:**

```json
[
  {
    "id": 163,
    "uid": "cIBgcSjkk",
    "title": "Production Overview",
    "uri": "db/production-overview",
    "url": "/d/cIBgcSjkk/production-overview",
    "slug": "",
    "type": "dash-db",
    "tags": ["monitoring", "production"],
    "isStarred": false,
    "folderId": 3,
    "folderUid": "l3KqBxCMz",
    "folderTitle": "Operations",
    "folderUrl": "/dashboards/f/l3KqBxCMz/operations",
    "sortMeta": 0
  }
]
```

---

## Get Dashboard by UID

```http
GET /api/dashboards/uid/:uid
```

**Example Request:**

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "https://grafana.example.com/api/dashboards/uid/cIBgcSjkk"
```

**Example Response:**

```json
{
  "meta": {
    "type": "db",
    "canSave": true,
    "canEdit": true,
    "canAdmin": true,
    "canStar": true,
    "canDelete": true,
    "slug": "production-overview",
    "url": "/d/cIBgcSjkk/production-overview",
    "expires": "0001-01-01T00:00:00Z",
    "created": "2023-01-15T10:30:00Z",
    "updated": "2024-06-20T14:22:00Z",
    "updatedBy": "admin",
    "createdBy": "admin",
    "version": 15,
    "hasAcl": false,
    "isFolder": false,
    "folderId": 3,
    "folderUid": "l3KqBxCMz",
    "folderTitle": "Operations",
    "folderUrl": "/dashboards/f/l3KqBxCMz/operations",
    "provisioned": false,
    "provisionedExternalId": ""
  },
  "dashboard": {
    "id": 163,
    "uid": "cIBgcSjkk",
    "title": "Production Overview",
    "tags": ["monitoring", "production"],
    "timezone": "browser",
    "schemaVersion": 38,
    "version": 15,
    "refresh": "30s",
    "panels": [...]
  }
}
```

---

## Create/Update Dashboard

```http
POST /api/dashboards/db
```

**Request Body:**

```json
{
  "dashboard": {
    "id": null,
    "uid": null,
    "title": "New Dashboard",
    "tags": ["tag1", "tag2"],
    "timezone": "browser",
    "schemaVersion": 38,
    "refresh": "30s",
    "panels": [
      {
        "id": 1,
        "type": "timeseries",
        "title": "CPU Usage",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
        "targets": [
          {
            "refId": "A",
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "expr": "100 - (avg(rate(node_cpu_seconds_total{mode=\"idle\"}[5m])) * 100)"
          }
        ]
      }
    ]
  },
  "folderUid": "l3KqBxCMz",
  "message": "Initial commit",
  "overwrite": false
}
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| dashboard.id | integer | Set to `null` for new dashboards |
| dashboard.uid | string | Unique identifier (auto-generated if null) |
| dashboard.title | string | Dashboard title (required) |
| dashboard.version | integer | Include for updates to prevent conflicts |
| folderUid | string | Target folder UID |
| folderId | integer | Target folder ID (deprecated, use folderUid) |
| message | string | Commit message for version history |
| overwrite | boolean | Force overwrite existing dashboard |

**Example Response (Success):**

```json
{
  "id": 163,
  "uid": "cIBgcSjkk",
  "url": "/d/cIBgcSjkk/new-dashboard",
  "status": "success",
  "version": 1,
  "slug": "new-dashboard"
}
```

---

## Delete Dashboard

```http
DELETE /api/dashboards/uid/:uid
```

**Example Request:**

```bash
curl -X DELETE -H "Authorization: Bearer <TOKEN>" \
  "https://grafana.example.com/api/dashboards/uid/cIBgcSjkk"
```

**Example Response:**

```json
{
  "title": "Production Overview",
  "message": "Dashboard Production Overview deleted",
  "id": 163
}
```

---

## Get Dashboard Versions

```http
GET /api/dashboards/uid/:uid/versions
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| limit | integer | Max versions to return (default: 0 = all) |
| start | integer | Start index for pagination |

**Example Response:**

```json
[
  {
    "id": 15,
    "dashboardId": 163,
    "parentVersion": 14,
    "restoredFrom": 0,
    "version": 15,
    "created": "2024-06-20T14:22:00Z",
    "createdBy": "admin",
    "message": "Updated thresholds"
  }
]
```

---

## Restore Dashboard Version

```http
POST /api/dashboards/uid/:uid/restore
```

**Request Body:**

```json
{
  "version": 10
}
```

**Example Response:**

```json
{
  "id": 163,
  "uid": "cIBgcSjkk",
  "url": "/d/cIBgcSjkk/production-overview",
  "status": "success",
  "version": 16,
  "slug": "production-overview"
}
```

---

## Dashboard Permissions

### Get Permissions

```http
GET /api/dashboards/uid/:uid/permissions
```

### Update Permissions

```http
POST /api/dashboards/uid/:uid/permissions
```

**Request Body:**

```json
{
  "items": [
    {"role": "Viewer", "permission": 1},
    {"role": "Editor", "permission": 2},
    {"teamId": 1, "permission": 1},
    {"userId": 11, "permission": 4}
  ]
}
```

**Permission Levels:**

- `1`: View
- `2`: Edit
- `4`: Admin

---

## Public/Shared Dashboards

### Create Public Dashboard

```http
POST /api/dashboards/uid/:uid/public-dashboards/
```

**Request Body:**

```json
{
  "uid": "cd56d9fd-f3d4-486d-afba-a21760e2acbe",
  "accessToken": "5c948bf96e6a4b13bd91975f9a2028b7",
  "timeSelectionEnabled": false,
  "isEnabled": true,
  "annotationsEnabled": false,
  "share": "public"
}
```

### Get Public Dashboard

```http
GET /api/dashboards/uid/:uid/public-dashboards/
```

### Update Public Dashboard

```http
PATCH /api/dashboards/uid/:uid/public-dashboards/:publicDashboardUid
```

### Delete Public Dashboard

```http
DELETE /api/dashboards/uid/:uid/public-dashboards/:publicDashboardUid
```
