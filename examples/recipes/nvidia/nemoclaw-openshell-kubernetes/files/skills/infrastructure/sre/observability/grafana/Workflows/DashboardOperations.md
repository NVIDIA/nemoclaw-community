# Dashboard Operations Workflow

Step-by-step workflow for Grafana dashboard operations using the TypeScript tools.

## Prerequisites

```bash
export GRAFANA_URL="https://grafana.example.com"
export GRAFANA_TOKEN="your-service-account-token"
```

## Workflow: List and Search

```bash
# List all dashboards
bun run Tools/DashboardCrud.ts list

# Search by name
bun run Tools/DashboardCrud.ts list --query production

# Filter by tag
bun run Tools/DashboardCrud.ts list --tag monitoring

# JSON output for scripting
bun run Tools/DashboardCrud.ts list --json
```

## Workflow: Export Dashboard

```bash
# Export to default file (uid.json)
bun run Tools/DashboardCrud.ts export abc123

# Export to custom file
bun run Tools/DashboardCrud.ts export abc123 --output my-dashboard.json
```

## Workflow: Create Dashboard

```bash
# Create dashboard
bun run Tools/DashboardCrud.ts create --file dashboard.json

# Create in specific folder
bun run Tools/DashboardCrud.ts create --file dashboard.json --folder my-folder-uid

# Create with custom title
bun run Tools/DashboardCrud.ts create --file dashboard.json --title "My Dashboard"
```

## Workflow: Update Dashboard

```bash
# Update dashboard
bun run Tools/DashboardCrud.ts update abc123 --file updated.json

# Update with commit message
bun run Tools/DashboardCrud.ts update abc123 --file updated.json --message "Added new panel"
```

## Workflow: Clone Dashboard

```bash
# Clone with auto-generated title
bun run Tools/DashboardCrud.ts clone abc123

# Clone with custom title
bun run Tools/DashboardCrud.ts clone abc123 --title "Production Copy"

# Clone to different folder
bun run Tools/DashboardCrud.ts clone abc123 --title "Dev Copy" --folder dev-folder-uid
```

## Workflow: Version Management

```bash
# View version history
bun run Tools/DashboardCrud.ts versions abc123

# Restore specific version
bun run Tools/DashboardCrud.ts restore abc123 --version 5
```

## Workflow: Delete Dashboard

```bash
bun run Tools/DashboardCrud.ts delete abc123
```

## Bulk Operations (TypeScript)

### Export All Dashboards by Tag

```typescript
import { createGrafanaClient } from './Tools/GrafanaClient';

const client = createGrafanaClient();
const dashboards = await client.searchDashboards({ tag: 'production' });

for (const dash of dashboards) {
  const full = await client.getDashboardByUid(dash.uid);
  await Bun.write(`exports/${dash.uid}.json`, JSON.stringify(full.dashboard, null, 2));
  console.log(`Exported: ${dash.uid}`);
}
```

### Update Tags in Bulk

```typescript
import { createGrafanaClient } from './Tools/GrafanaClient';

const client = createGrafanaClient();
const dashboards = await client.searchDashboards({ tag: 'old-tag' });

for (const dash of dashboards) {
  const full = await client.getDashboardByUid(dash.uid);
  full.dashboard.tags = full.dashboard.tags.filter(t => t !== 'old-tag');
  full.dashboard.tags.push('new-tag');

  await client.saveDashboard({
    dashboard: full.dashboard,
    folderUid: full.meta.folderUid,
    message: 'Updated tags'
  });
  console.log(`Updated: ${dash.uid}`);
}
```

## Error Handling

| Error | Solution |
|-------|----------|
| 412 Version Conflict | Fetch latest version first, then update |
| 403 Permission Denied | Check service account role (Viewer/Editor/Admin) |
| 404 Not Found | Verify dashboard UID and organization |
