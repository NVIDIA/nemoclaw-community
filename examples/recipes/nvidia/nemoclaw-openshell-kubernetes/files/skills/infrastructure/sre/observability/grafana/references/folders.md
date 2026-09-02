# Folders API Reference

Complete reference for Grafana Folder HTTP API endpoints.

## Table of Contents

- [List Folders](#list-folders)
- [Get Folder](#get-folder)
- [Create Folder](#create-folder)
- [Update Folder](#update-folder)
- [Delete Folder](#delete-folder)
- [Move Folder](#move-folder)
- [Folder Permissions](#folder-permissions)

---

## List Folders

```http
GET /api/folders
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| limit | integer | Max folders to return (default: 1000) |
| page | integer | Page number for pagination |

**Example Response:**

```json
[
  {
    "id": 1,
    "uid": "nErXDvCkzz",
    "title": "Operations",
    "url": "/dashboards/f/nErXDvCkzz/operations",
    "hasAcl": false,
    "canSave": true,
    "canEdit": true,
    "canAdmin": true,
    "canDelete": true,
    "createdBy": "admin",
    "created": "2023-01-15T10:30:00Z",
    "updatedBy": "admin",
    "updated": "2024-06-20T14:22:00Z",
    "version": 1
  }
]
```

---

## Get Folder

### By UID

```http
GET /api/folders/:uid
```

### By ID (Deprecated)

```http
GET /api/folders/id/:id
```

**Example Response:**

```json
{
  "id": 1,
  "uid": "nErXDvCkzz",
  "title": "Operations",
  "url": "/dashboards/f/nErXDvCkzz/operations",
  "hasAcl": false,
  "canSave": true,
  "canEdit": true,
  "canAdmin": true,
  "canDelete": true,
  "createdBy": "admin",
  "created": "2023-01-15T10:30:00Z",
  "updatedBy": "admin",
  "updated": "2024-06-20T14:22:00Z",
  "version": 3,
  "parentUid": ""
}
```

---

## Create Folder

```http
POST /api/folders
```

**Request Body:**

```json
{
  "uid": "my-folder-uid",
  "title": "My New Folder",
  "parentUid": "parent-folder-uid"
}
```

**Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| title | string | Yes | Folder title |
| uid | string | No | Unique identifier (auto-generated if omitted) |
| parentUid | string | No | Parent folder UID (for nested folders) |

**Example Response:**

```json
{
  "id": 5,
  "uid": "my-folder-uid",
  "title": "My New Folder",
  "url": "/dashboards/f/my-folder-uid/my-new-folder",
  "hasAcl": false,
  "canSave": true,
  "canEdit": true,
  "canAdmin": true,
  "canDelete": true,
  "createdBy": "admin",
  "created": "2024-06-20T14:22:00Z",
  "updatedBy": "admin",
  "updated": "2024-06-20T14:22:00Z",
  "version": 1,
  "parentUid": "parent-folder-uid"
}
```

---

## Update Folder

```http
PUT /api/folders/:uid
```

**Request Body:**

```json
{
  "title": "Updated Folder Title",
  "version": 1,
  "overwrite": false
}
```

**Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| title | string | Yes | New folder title |
| version | integer | Yes | Current version (for optimistic locking) |
| overwrite | boolean | No | Force update regardless of version |

**Error Response (Version Mismatch):**

```json
{
  "message": "The folder has been changed by someone else",
  "status": "version-mismatch"
}
```

---

## Delete Folder

```http
DELETE /api/folders/:uid
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| forceDeleteRules | boolean | false | Delete alert rules in folder |

**Warning:** Deleting a folder also deletes all dashboards inside it. This operation cannot be undone.

**Example Request:**

```bash
curl -X DELETE -H "Authorization: Bearer <TOKEN>" \
  "https://grafana.example.com/api/folders/nErXDvCkzz?forceDeleteRules=true"
```

**Example Response:**

```json
{
  "title": "Operations",
  "message": "Folder Operations deleted",
  "id": 1
}
```

---

## Move Folder

```http
POST /api/folders/:uid/move
```

**Note:** Only available when nested folders are enabled.

**Request Body:**

```json
{
  "parentUid": "new-parent-folder-uid"
}
```

Use empty string or omit `parentUid` to move to root level.

---

## Folder Permissions

### Get Folder Permissions

```http
GET /api/folders/:uid/permissions
```

**Example Response:**

```json
[
  {
    "id": 1,
    "folderId": 1,
    "created": "2023-01-15T10:30:00Z",
    "updated": "2024-06-20T14:22:00Z",
    "userId": 0,
    "userLogin": "",
    "userEmail": "",
    "teamId": 0,
    "team": "",
    "role": "Viewer",
    "permission": 1,
    "permissionName": "View",
    "uid": "nErXDvCkzz",
    "title": "Operations",
    "slug": "operations",
    "isFolder": true,
    "url": "/dashboards/f/nErXDvCkzz/operations",
    "inherited": false
  }
]
```

### Update Folder Permissions

```http
POST /api/folders/:uid/permissions
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

| Value | Name | Description |
|-------|------|-------------|
| 1 | View | Can view dashboards in folder |
| 2 | Edit | Can edit dashboards in folder |
| 4 | Admin | Full admin rights to folder |

---

## Search Folders and Dashboards

```http
GET /api/search
```

**Query Parameters for Folder Search:**

| Parameter | Type | Description |
|-----------|------|-------------|
| type | string | `dash-folder` for folders only |
| query | string | Search by title |
| folderIds | array | Filter by parent folder IDs |

**Example:**

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "https://grafana.example.com/api/search?type=dash-folder&query=prod"
```

---

## New Folder API (v1beta1)

Grafana is transitioning to a new Kubernetes-style API structure.

### List Folders (New API)

```http
GET /apis/folder.grafana.app/v1beta1/namespaces/default/folders
```

### Get Folder (New API)

```http
GET /apis/folder.grafana.app/v1beta1/namespaces/default/folders/:uid
```

### Create Folder (New API)

```http
POST /apis/folder.grafana.app/v1beta1/namespaces/default/folders
```

**Request Body:**

```json
{
  "metadata": {
    "name": "my-folder-uid",
    "annotations": {
      "grafana.app/folder": "parent-folder-uid"
    }
  },
  "spec": {
    "title": "My New Folder"
  }
}
```

**Response:**

```json
{
  "kind": "Folder",
  "apiVersion": "folder.grafana.app/v1beta1",
  "metadata": {
    "name": "my-folder-uid",
    "namespace": "default",
    "uid": "...",
    "resourceVersion": "...",
    "creationTimestamp": "2024-06-20T14:22:00Z",
    "annotations": {
      "grafana.app/folder": "parent-folder-uid",
      "grafana.app/createdBy": "admin",
      "grafana.app/updatedBy": "admin",
      "grafana.app/updatedTimestamp": "2024-06-20T14:22:00Z"
    }
  },
  "spec": {
    "title": "My New Folder"
  }
}
```
