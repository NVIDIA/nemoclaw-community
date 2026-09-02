# Users & Teams API Reference

Complete reference for Grafana User, Team, and Service Account HTTP API endpoints.

## Table of Contents

- [Current User](#current-user)
- [Users (Admin)](#users-admin)
- [Teams](#teams)
- [Team Members](#team-members)
- [Service Accounts](#service-accounts)
- [Service Account Tokens](#service-account-tokens)
- [Organizations](#organizations)
- [Organization Users](#organization-users)

---

## Current User

### Get Current User

```http
GET /api/user
```

**Example Response:**

```json
{
  "id": 1,
  "email": "admin@example.com",
  "name": "Admin User",
  "login": "admin",
  "theme": "dark",
  "orgId": 1,
  "isGrafanaAdmin": true,
  "isDisabled": false,
  "isExternal": false,
  "authLabels": [],
  "updatedAt": "2024-06-20T14:22:00Z",
  "createdAt": "2023-01-15T10:30:00Z",
  "avatarUrl": "/avatar/46d229b033af06a191ff2267bca9ae56"
}
```

### Update Current User

```http
PUT /api/user
```

```json
{
  "name": "New Name",
  "email": "newemail@example.com",
  "login": "newlogin",
  "theme": "light"
}
```

### Get Current User Organizations

```http
GET /api/user/orgs
```

### Get Current User Teams

```http
GET /api/user/teams
```

### Star/Unstar Dashboard

```http
POST /api/user/stars/dashboard/uid/:dashboardUID
DELETE /api/user/stars/dashboard/uid/:dashboardUID
```

### Change Active Organization

```http
POST /api/user/using/:orgId
```

---

## Users (Admin)

Requires Grafana Admin permission.

### Search Users

```http
GET /api/users/search
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| perpage | integer | Results per page (default: 1000) |
| page | integer | Page number |
| query | string | Search by login, email, or name |
| sort | string | Sort order (e.g., `login-asc`, `email-desc`) |

**Example Response:**

```json
{
  "totalCount": 2,
  "users": [
    {
      "id": 1,
      "name": "Admin User",
      "login": "admin",
      "email": "admin@example.com",
      "isAdmin": true,
      "isDisabled": false,
      "lastSeenAt": "2024-06-20T14:22:00Z",
      "lastSeenAtAge": "2m",
      "authLabels": ["OAuth"]
    }
  ],
  "page": 1,
  "perPage": 10
}
```

### Get User by ID

```http
GET /api/users/:id
```

### Create User

```http
POST /api/admin/users
```

```json
{
  "name": "New User",
  "email": "newuser@example.com",
  "login": "newuser",
  "password": "password123",
  "OrgId": 1
}
```

### Update User

```http
PUT /api/users/:id
```

```json
{
  "name": "Updated Name",
  "email": "updated@example.com",
  "login": "updatedlogin",
  "theme": "dark"
}
```

### Delete User

```http
DELETE /api/admin/users/:id
```

### Update User Permissions

```http
PUT /api/admin/users/:id/permissions
```

```json
{
  "isGrafanaAdmin": true
}
```

### Disable/Enable User

```http
POST /api/admin/users/:id/disable
POST /api/admin/users/:id/enable
```

---

## Teams

### Search Teams

```http
GET /api/teams/search
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| perpage | integer | Results per page (default: 1000) |
| page | integer | Page number |
| name | string | Filter by team name |
| query | string | Search query |

**Example Response:**

```json
{
  "totalCount": 1,
  "teams": [
    {
      "id": 1,
      "orgId": 1,
      "name": "Platform Team",
      "email": "platform@example.com",
      "avatarUrl": "/avatar/3f49c15916554246daa714b9bd0ee398",
      "memberCount": 5,
      "permission": 0
    }
  ],
  "page": 1,
  "perPage": 1000
}
```

### Get Team by ID

```http
GET /api/teams/:teamId
```

### Create Team

```http
POST /api/teams
```

```json
{
  "name": "DevOps Team",
  "email": "devops@example.com"
}
```

### Update Team

```http
PUT /api/teams/:teamId
```

```json
{
  "name": "Updated Team Name",
  "email": "newemail@example.com"
}
```

### Delete Team

```http
DELETE /api/teams/:teamId
```

---

## Team Members

### Get Team Members

```http
GET /api/teams/:teamId/members
```

**Example Response:**

```json
[
  {
    "orgId": 1,
    "teamId": 1,
    "userId": 2,
    "email": "user@example.com",
    "name": "User Name",
    "login": "username",
    "avatarUrl": "/avatar/46d229b033af06a191ff2267bca9ae56",
    "labels": [],
    "permission": 0
  }
]
```

### Add Team Member

```http
POST /api/teams/:teamId/members
```

```json
{
  "userId": 5
}
```

### Remove Team Member

```http
DELETE /api/teams/:teamId/members/:userId
```

### Update Team Member Permission

```http
PUT /api/teams/:teamId/members/:userId
```

```json
{
  "permission": 4
}
```

**Permission Values:**

- `0`: Member
- `4`: Admin

---

## Service Accounts

### Search Service Accounts

```http
GET /api/serviceaccounts/search
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| perpage | integer | Results per page |
| page | integer | Page number |
| query | string | Search query |
| disabled | boolean | Filter by disabled status |

**Example Response:**

```json
{
  "totalCount": 1,
  "serviceAccounts": [
    {
      "id": 1,
      "name": "automation-sa",
      "login": "sa-automation-sa",
      "orgId": 1,
      "isDisabled": false,
      "role": "Editor",
      "tokens": 2,
      "avatarUrl": "/avatar/85ec38023d90823d3e5b43ef35646af9"
    }
  ],
  "page": 1,
  "perPage": 10
}
```

### Get Service Account by ID

```http
GET /api/serviceaccounts/:id
```

### Create Service Account

```http
POST /api/serviceaccounts
```

```json
{
  "name": "automation-sa",
  "role": "Editor",
  "isDisabled": false
}
```

**Roles:** `Viewer`, `Editor`, `Admin`

### Update Service Account

```http
PATCH /api/serviceaccounts/:id
```

```json
{
  "name": "new-name",
  "role": "Admin",
  "isDisabled": false
}
```

### Delete Service Account

```http
DELETE /api/serviceaccounts/:id
```

---

## Service Account Tokens

### List Tokens

```http
GET /api/serviceaccounts/:id/tokens
```

**Example Response:**

```json
[
  {
    "id": 1,
    "name": "token-1",
    "created": "2024-06-20T14:22:00Z",
    "expiration": "2024-12-20T14:22:00Z",
    "secondsUntilExpiration": 15552000,
    "hasExpired": false,
    "lastUsedAt": "2024-06-20T14:22:00Z"
  }
]
```

### Create Token

```http
POST /api/serviceaccounts/:id/tokens
```

```json
{
  "name": "automation-token",
  "secondsToLive": 86400
}
```

Use `secondsToLive: 0` for non-expiring tokens.

**Response:**

```json
{
  "id": 2,
  "name": "automation-token",
  "key": "glsa_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

**Important:** The `key` is only shown once. Store it securely.

### Delete Token

```http
DELETE /api/serviceaccounts/:id/tokens/:tokenId
```

---

## Organizations

### Get Current Organization

```http
GET /api/org
```

### Update Current Organization

```http
PUT /api/org
```

```json
{
  "name": "New Org Name"
}
```

### List Organizations (Admin)

```http
GET /api/orgs
```

### Create Organization (Admin)

```http
POST /api/orgs
```

```json
{
  "name": "New Organization"
}
```

### Get Organization by ID (Admin)

```http
GET /api/orgs/:orgId
```

### Update Organization (Admin)

```http
PUT /api/orgs/:orgId
```

### Delete Organization (Admin)

```http
DELETE /api/orgs/:orgId
```

---

## Organization Users

### Get Current Org Users

```http
GET /api/org/users
```

**Example Response:**

```json
[
  {
    "orgId": 1,
    "userId": 1,
    "email": "admin@example.com",
    "name": "Admin",
    "avatarUrl": "/avatar/46d229b033af06a191ff2267bca9ae56",
    "login": "admin",
    "role": "Admin",
    "lastSeenAt": "2024-06-20T14:22:00Z",
    "lastSeenAtAge": "2m"
  }
]
```

### Add User to Current Org

```http
POST /api/org/users
```

```json
{
  "loginOrEmail": "user@example.com",
  "role": "Viewer"
}
```

### Update User Role in Current Org

```http
PATCH /api/org/users/:userId
```

```json
{
  "role": "Editor"
}
```

### Remove User from Current Org

```http
DELETE /api/org/users/:userId
```

### Get Org Users (Admin)

```http
GET /api/orgs/:orgId/users
```

### Add User to Org (Admin)

```http
POST /api/orgs/:orgId/users
```

```json
{
  "loginOrEmail": "user@example.com",
  "role": "Viewer"
}
```

### Update User Role in Org (Admin)

```http
PATCH /api/orgs/:orgId/users/:userId
```

### Remove User from Org (Admin)

```http
DELETE /api/orgs/:orgId/users/:userId
```
