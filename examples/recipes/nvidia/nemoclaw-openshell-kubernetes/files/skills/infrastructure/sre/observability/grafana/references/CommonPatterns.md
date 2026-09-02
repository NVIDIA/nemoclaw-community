# Common Patterns Reference

Error handling, pagination, and reusable patterns for the Grafana HTTP API.

## Table of Contents

- [Error Handling](#error-handling)
- [Pagination](#pagination)
- [Rate Limiting](#rate-limiting)
- [Common Errors](#common-errors)
- [Python Client Examples](#python-client-examples)
- [Bash Script Examples](#bash-script-examples)

---

## Error Handling

### HTTP Status Codes

| Code | Meaning | Common Causes |
|------|---------|---------------|
| 200 | Success | Request completed successfully |
| 201 | Created | Resource created successfully |
| 400 | Bad Request | Invalid JSON, missing required fields |
| 401 | Unauthorized | Invalid or missing authentication |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Resource doesn't exist |
| 409 | Conflict | Resource already exists |
| 412 | Precondition Failed | Version mismatch (optimistic locking) |
| 422 | Unprocessable Entity | Validation error |
| 500 | Internal Server Error | Server-side error |

### Error Response Format

```json
{
  "message": "Dashboard not found",
  "status": "not-found"
}
```

Or with more detail:

```json
{
  "message": "Failed to save dashboard",
  "status": "validation-failed",
  "messageId": "dashboards.dashboardNotFound",
  "traceID": "abc123def456"
}
```

---

## Pagination

### List Endpoints

Most list endpoints support pagination via `limit` and `page`:

```bash
GET /api/search?limit=50&page=1
GET /api/users/search?perpage=100&page=2
```

### Response Metadata

Some endpoints return pagination metadata:

```json
{
  "totalCount": 250,
  "page": 1,
  "perPage": 100,
  "users": [...]
}
```

### Iterating All Pages

```python
def get_all_pages(grafana, endpoint, key='results', page_size=100):
    all_results = []
    page = 1

    while True:
        response = grafana.get(f"{endpoint}?perpage={page_size}&page={page}")
        results = response.get(key, response)

        if not results:
            break

        all_results.extend(results)

        total = response.get('totalCount', len(results))
        if len(all_results) >= total:
            break

        page += 1

    return all_results
```

---

## Rate Limiting

Grafana doesn't have built-in API rate limiting by default, but:

1. **Reverse proxies** may impose limits
2. **Grafana Cloud** has rate limits per tier
3. **Best practice**: Add delays between bulk operations

```python
import time

def bulk_create_with_rate_limit(items, create_func, delay=0.1):
    results = []
    for item in items:
        result = create_func(item)
        results.append(result)
        time.sleep(delay)
    return results
```

---

## Common Errors

### Dashboard Version Conflict (412)

**Error:**

```json
{
  "message": "The dashboard has been changed by someone else",
  "status": "version-mismatch"
}
```

**Solution:** Fetch latest version and retry:

```python
def update_dashboard_safely(grafana, uid, updates):
    dashboard_data = grafana.get_dashboard_by_uid(uid)
    dashboard = dashboard_data['dashboard']

    # Apply updates
    dashboard.update(updates)

    # Include version for optimistic locking
    return grafana.create_or_update_dashboard({
        'dashboard': dashboard,
        'folderUid': dashboard_data['meta'].get('folderUid'),
        'overwrite': False
    })
```

### Permission Denied (403)

**Error:**

```json
{
  "message": "Access denied"
}
```

**Common causes:**

- Token lacks required permissions
- User not in correct organization
- RBAC restrictions (Enterprise)

**Debug:** Check service account permissions in Grafana UI.

### Resource Not Found (404)

**Error:**

```json
{
  "message": "Dashboard not found",
  "status": "not-found"
}
```

**Common causes:**

- Wrong UID or ID
- Resource in different organization
- Resource was deleted

---

## Python Client Examples

### Base Client Class

```python
import requests
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin

class GrafanaAPIError(Exception):
    def __init__(self, message: str, status_code: int, response: Dict):
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(f"{status_code}: {message}")

class GrafanaClient:
    def __init__(self, base_url: str, token: str, org_id: Optional[int] = None):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        if org_id:
            self.session.headers['X-Grafana-Org-Id'] = str(org_id)

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict:
        url = urljoin(self.base_url, endpoint)
        response = self.session.request(method, url, **kwargs)

        try:
            data = response.json()
        except:
            data = {'message': response.text}

        if not response.ok:
            raise GrafanaAPIError(
                data.get('message', 'Unknown error'),
                response.status_code,
                data
            )

        return data

    def get(self, endpoint: str, params: Dict = None) -> Dict:
        return self._request('GET', endpoint, params=params)

    def post(self, endpoint: str, json: Dict = None) -> Dict:
        return self._request('POST', endpoint, json=json)

    def put(self, endpoint: str, json: Dict = None) -> Dict:
        return self._request('PUT', endpoint, json=json)

    def patch(self, endpoint: str, json: Dict = None) -> Dict:
        return self._request('PATCH', endpoint, json=json)

    def delete(self, endpoint: str) -> Dict:
        return self._request('DELETE', endpoint)
```

### Dashboard Operations

```python
class DashboardMixin:
    def search_dashboards(
        self,
        query: str = None,
        tag: str = None,
        folder_uid: str = None,
        limit: int = 100
    ) -> List[Dict]:
        params = {'type': 'dash-db', 'limit': limit}
        if query:
            params['query'] = query
        if tag:
            params['tag'] = tag
        if folder_uid:
            params['folderUIDs'] = folder_uid
        return self.get('/api/search', params=params)

    def get_dashboard_by_uid(self, uid: str) -> Dict:
        return self.get(f'/api/dashboards/uid/{uid}')

    def create_or_update_dashboard(
        self,
        dashboard: Dict,
        folder_uid: str = None,
        message: str = None,
        overwrite: bool = False
    ) -> Dict:
        payload = {
            'dashboard': dashboard,
            'overwrite': overwrite
        }
        if folder_uid:
            payload['folderUid'] = folder_uid
        if message:
            payload['message'] = message
        return self.post('/api/dashboards/db', json=payload)

    def delete_dashboard(self, uid: str) -> Dict:
        return self.delete(f'/api/dashboards/uid/{uid}')
```

### Data Source Operations

```python
class DataSourceMixin:
    def list_datasources(self) -> List[Dict]:
        return self.get('/api/datasources')

    def get_datasource_by_uid(self, uid: str) -> Dict:
        return self.get(f'/api/datasources/uid/{uid}')

    def create_datasource(self, datasource: Dict) -> Dict:
        return self.post('/api/datasources', json=datasource)

    def update_datasource(self, uid: str, datasource: Dict) -> Dict:
        return self.put(f'/api/datasources/uid/{uid}', json=datasource)

    def delete_datasource(self, uid: str) -> Dict:
        return self.delete(f'/api/datasources/uid/{uid}')

    def health_check_datasource(self, uid: str) -> Dict:
        return self.get(f'/api/datasources/uid/{uid}/health')

    def query_datasource(self, queries: List[Dict], from_time: str, to_time: str) -> Dict:
        return self.post('/api/ds/query', json={
            'queries': queries,
            'from': from_time,
            'to': to_time
        })
```

### Complete Client

```python
class GrafanaAPI(GrafanaClient, DashboardMixin, DataSourceMixin):
    """Complete Grafana API client with all mixins."""
    pass

# Usage
grafana = GrafanaAPI(
    base_url='https://grafana.example.com',
    token='your-service-account-token'
)

# Search dashboards
dashboards = grafana.search_dashboards(query='production', tag='monitoring')

# Get dashboard details
dashboard = grafana.get_dashboard_by_uid('abc123')

# Create annotation
grafana.post('/api/annotations', json={
    'dashboardUID': 'abc123',
    'time': int(time.time() * 1000),
    'tags': ['deploy'],
    'text': 'Deployment completed'
})
```

---

## Bash Script Examples

### Health Check Script

```bash
#!/bin/bash
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_TOKEN="${GRAFANA_TOKEN}"

check_health() {
    response=$(curl -s -w "\n%{http_code}" \
        -H "Authorization: Bearer $GRAFANA_TOKEN" \
        "$GRAFANA_URL/api/health")

    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | head -n-1)

    if [ "$http_code" = "200" ]; then
        echo "✓ Grafana is healthy"
        return 0
    else
        echo "✗ Grafana health check failed: $body"
        return 1
    fi
}

check_health
```

### Export All Dashboards

```bash
#!/bin/bash
GRAFANA_URL="${GRAFANA_URL}"
GRAFANA_TOKEN="${GRAFANA_TOKEN}"
OUTPUT_DIR="${OUTPUT_DIR:-./dashboards}"

mkdir -p "$OUTPUT_DIR"

# Get all dashboard UIDs
uids=$(curl -s \
    -H "Authorization: Bearer $GRAFANA_TOKEN" \
    "$GRAFANA_URL/api/search?type=dash-db" | \
    jq -r '.[].uid')

for uid in $uids; do
    echo "Exporting dashboard: $uid"
    curl -s \
        -H "Authorization: Bearer $GRAFANA_TOKEN" \
        "$GRAFANA_URL/api/dashboards/uid/$uid" | \
        jq '.dashboard' > "$OUTPUT_DIR/$uid.json"
done

echo "Exported $(echo "$uids" | wc -w) dashboards to $OUTPUT_DIR"
```

### Import Dashboard

```bash
#!/bin/bash
GRAFANA_URL="${GRAFANA_URL}"
GRAFANA_TOKEN="${GRAFANA_TOKEN}"
DASHBOARD_FILE="${1}"
FOLDER_UID="${2:-}"

if [ -z "$DASHBOARD_FILE" ]; then
    echo "Usage: $0 <dashboard.json> [folder_uid]"
    exit 1
fi

# Read dashboard and wrap it
dashboard=$(cat "$DASHBOARD_FILE")

payload=$(jq -n \
    --argjson dashboard "$dashboard" \
    --arg folderUid "$FOLDER_UID" \
    '{
        dashboard: ($dashboard | .id = null | .uid = null),
        folderUid: $folderUid,
        overwrite: false
    }')

response=$(curl -s -X POST \
    -H "Authorization: Bearer $GRAFANA_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    "$GRAFANA_URL/api/dashboards/db")

echo "$response" | jq .
```
