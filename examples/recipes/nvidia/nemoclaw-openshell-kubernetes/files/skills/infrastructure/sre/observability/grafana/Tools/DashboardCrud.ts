#!/usr/bin/env bun
/**
 * DashboardCrud - CLI tool for Grafana Dashboard CRUD operations
 *
 * @example
 * ```bash
 * bun run DashboardCrud.ts list
 * bun run DashboardCrud.ts get abc123
 * bun run DashboardCrud.ts create --file dashboard.json --folder my-folder
 * bun run DashboardCrud.ts delete abc123
 * ```
 */

import {
  GrafanaClient,
  createGrafanaClient,
  type DashboardModel,
  type DashboardSearchResult,
  type DashboardResponse,
  type SaveDashboardResponse,
  type DashboardVersion,
  type GrafanaApiError,
} from './GrafanaClient';

// =============================================================================
// Types
// =============================================================================

interface CliOptions {
  url?: string;
  token?: string;
  orgId?: number;
  output?: string;
  file?: string;
  folder?: string;
  title?: string;
  message?: string;
  overwrite?: boolean;
  query?: string;
  tag?: string;
  limit?: number;
  version?: number;
  json?: boolean;
  quiet?: boolean;
}

type Command = 'list' | 'get' | 'create' | 'update' | 'delete' | 'export' | 'import' | 'clone' | 'versions' | 'restore' | 'help';

// =============================================================================
// Utilities
// =============================================================================

function parseArgs(args: string[]): { command: Command; uid?: string; options: CliOptions } {
  const options: CliOptions = {};
  let command: Command = 'help';
  let uid: string | undefined;

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];

    if (!arg.startsWith('-')) {
      if (!command || command === 'help') {
        command = arg as Command;
      } else if (!uid) {
        uid = arg;
      }
      continue;
    }

    const nextArg = args[i + 1];

    switch (arg) {
      case '--url': case '-u': options.url = nextArg; i++; break;
      case '--token': case '-t': options.token = nextArg; i++; break;
      case '--org-id': case '-o': options.orgId = parseInt(nextArg); i++; break;
      case '--output': options.output = nextArg; i++; break;
      case '--file': case '-f': options.file = nextArg; i++; break;
      case '--folder': options.folder = nextArg; i++; break;
      case '--title': options.title = nextArg; i++; break;
      case '--message': case '-m': options.message = nextArg; i++; break;
      case '--overwrite': options.overwrite = true; break;
      case '--query': case '-q': options.query = nextArg; i++; break;
      case '--tag': options.tag = nextArg; i++; break;
      case '--limit': case '-l': options.limit = parseInt(nextArg); i++; break;
      case '--version': case '-v': options.version = parseInt(nextArg); i++; break;
      case '--json': case '-j': options.json = true; break;
      case '--quiet': options.quiet = true; break;
      case '--help': case '-h': command = 'help'; break;
    }
  }

  return { command, uid, options };
}

function error(message: string): never {
  console.error(`Error: ${message}`);
  process.exit(1);
}

async function readJsonFile(path: string): Promise<unknown> {
  try {
    const file = Bun.file(path);
    return await file.json();
  } catch {
    error(`Failed to read JSON file: ${path}`);
  }
}

async function writeJsonFile(path: string, data: unknown): Promise<void> {
  try {
    await Bun.write(path, JSON.stringify(data, null, 2));
  } catch {
    error(`Failed to write JSON file: ${path}`);
  }
}

// =============================================================================
// Commands
// =============================================================================

async function listDashboards(client: GrafanaClient, options: CliOptions): Promise<DashboardSearchResult[]> {
  const results = await client.searchDashboards({
    query: options.query,
    tag: options.tag,
    limit: options.limit,
  });

  if (!options.json) {
    console.log('\n📊 Dashboards:\n');
    console.log('─'.repeat(80));
    if (results.length === 0) {
      console.log('No dashboards found.');
    } else {
      results.forEach((dash) => {
        const tags = dash.tags.length > 0 ? ` [${dash.tags.join(', ')}]` : '';
        const folder = dash.folderTitle ? ` (${dash.folderTitle})` : '';
        console.log(`  ${dash.uid}  ${dash.title}${folder}${tags}`);
      });
    }
    console.log('─'.repeat(80));
    console.log(`Total: ${results.length} dashboards\n`);
  } else {
    console.log(JSON.stringify(results, null, 2));
  }

  return results;
}

async function getDashboard(client: GrafanaClient, uid: string, options: CliOptions): Promise<DashboardResponse> {
  const result = await client.getDashboardByUid(uid);

  if (!options.json) {
    console.log('\n📊 Dashboard Details:\n');
    console.log('─'.repeat(80));
    console.log(`  UID:      ${result.dashboard.uid}`);
    console.log(`  Title:    ${result.dashboard.title}`);
    console.log(`  Version:  ${result.meta.version}`);
    console.log(`  Folder:   ${result.meta.folderTitle ?? 'General'}`);
    console.log(`  URL:      ${result.meta.url}`);
    console.log(`  Created:  ${result.meta.created}`);
    console.log(`  Updated:  ${result.meta.updated}`);
    console.log(`  Panels:   ${result.dashboard.panels?.length ?? 0}`);
    if (result.dashboard.tags?.length) {
      console.log(`  Tags:     ${result.dashboard.tags.join(', ')}`);
    }
    console.log('─'.repeat(80));
  } else {
    console.log(JSON.stringify(result, null, 2));
  }

  return result;
}

async function createDashboard(client: GrafanaClient, options: CliOptions): Promise<SaveDashboardResponse> {
  if (!options.file) error('--file is required for create command');

  const dashboardJson = (await readJsonFile(options.file)) as DashboardModel | { dashboard: DashboardModel };
  const dashboard: DashboardModel = 'dashboard' in dashboardJson ? dashboardJson.dashboard : dashboardJson;

  if (options.title) dashboard.title = options.title;
  dashboard.id = null;
  dashboard.uid = null;

  const result = await client.saveDashboard({
    dashboard,
    folderUid: options.folder,
    message: options.message ?? 'Created via CLI',
    overwrite: options.overwrite ?? false,
  });

  if (!options.json) {
    console.log('\n✅ Dashboard Created:\n');
    console.log('─'.repeat(80));
    console.log(`  UID:      ${result.uid}`);
    console.log(`  URL:      ${result.url}`);
    console.log(`  Version:  ${result.version}`);
    console.log('─'.repeat(80));
  } else {
    console.log(JSON.stringify(result, null, 2));
  }

  return result;
}

async function updateDashboard(client: GrafanaClient, uid: string, options: CliOptions): Promise<SaveDashboardResponse> {
  if (!options.file) error('--file is required for update command');

  const existing = await client.getDashboardByUid(uid);
  const dashboardJson = (await readJsonFile(options.file)) as DashboardModel | { dashboard: DashboardModel };
  const dashboard: DashboardModel = 'dashboard' in dashboardJson ? dashboardJson.dashboard : dashboardJson;

  dashboard.uid = uid;
  dashboard.version = existing.dashboard.version;
  if (options.title) dashboard.title = options.title;

  const result = await client.saveDashboard({
    dashboard,
    folderUid: options.folder ?? existing.meta.folderUid,
    message: options.message ?? 'Updated via CLI',
    overwrite: options.overwrite ?? false,
  });

  if (!options.json) {
    console.log('\n✅ Dashboard Updated:\n');
    console.log('─'.repeat(80));
    console.log(`  UID:      ${result.uid}`);
    console.log(`  URL:      ${result.url}`);
    console.log(`  Version:  ${result.version}`);
    console.log('─'.repeat(80));
  } else {
    console.log(JSON.stringify(result, null, 2));
  }

  return result;
}

async function deleteDashboard(client: GrafanaClient, uid: string, options: CliOptions): Promise<void> {
  const result = await client.deleteDashboard(uid);

  if (!options.json) {
    console.log('\n🗑️  Dashboard Deleted:\n');
    console.log('─'.repeat(80));
    console.log(`  Title:    ${result.title}`);
    console.log(`  Message:  ${result.message}`);
    console.log('─'.repeat(80));
  } else {
    console.log(JSON.stringify(result, null, 2));
  }
}

async function exportDashboard(client: GrafanaClient, uid: string, options: CliOptions): Promise<void> {
  const result = await client.getDashboardByUid(uid);
  const outputPath = options.output ?? `${uid}.json`;
  await writeJsonFile(outputPath, result.dashboard);

  if (!options.quiet) {
    console.log(`\n✅ Dashboard exported to: ${outputPath}`);
  }
}

async function importDashboard(client: GrafanaClient, options: CliOptions): Promise<SaveDashboardResponse> {
  if (!options.file) error('--file is required for import command');

  const dashboardJson = (await readJsonFile(options.file)) as DashboardModel | { dashboard: DashboardModel; folderUid?: string };

  let dashboard: DashboardModel;
  let folderUid: string | undefined;

  if ('dashboard' in dashboardJson) {
    dashboard = dashboardJson.dashboard;
    folderUid = dashboardJson.folderUid ?? options.folder;
  } else {
    dashboard = dashboardJson;
    folderUid = options.folder;
  }

  if (options.title) dashboard.title = options.title;
  dashboard.id = null;
  if (!dashboard.uid) dashboard.uid = null;

  const result = await client.saveDashboard({
    dashboard,
    folderUid,
    message: options.message ?? 'Imported via CLI',
    overwrite: options.overwrite ?? false,
  });

  if (!options.json) {
    console.log('\n✅ Dashboard Imported:\n');
    console.log('─'.repeat(80));
    console.log(`  UID:      ${result.uid}`);
    console.log(`  URL:      ${result.url}`);
    console.log(`  Version:  ${result.version}`);
    console.log('─'.repeat(80));
  } else {
    console.log(JSON.stringify(result, null, 2));
  }

  return result;
}

async function cloneDashboard(client: GrafanaClient, uid: string, options: CliOptions): Promise<SaveDashboardResponse> {
  const source = await client.getDashboardByUid(uid);
  const dashboard = { ...source.dashboard };
  dashboard.id = null;
  dashboard.uid = null;
  dashboard.title = options.title ?? `${source.dashboard.title} (Copy)`;

  const result = await client.saveDashboard({
    dashboard,
    folderUid: options.folder ?? source.meta.folderUid,
    message: options.message ?? `Cloned from ${uid}`,
    overwrite: false,
  });

  if (!options.json) {
    console.log('\n✅ Dashboard Cloned:\n');
    console.log('─'.repeat(80));
    console.log(`  Source:   ${uid}`);
    console.log(`  New UID:  ${result.uid}`);
    console.log(`  Title:    ${dashboard.title}`);
    console.log(`  URL:      ${result.url}`);
    console.log('─'.repeat(80));
  } else {
    console.log(JSON.stringify(result, null, 2));
  }

  return result;
}

async function listVersions(client: GrafanaClient, uid: string, options: CliOptions): Promise<DashboardVersion[]> {
  const versions = await client.getDashboardVersions(uid, options.limit);

  if (!options.json) {
    console.log('\n📋 Dashboard Versions:\n');
    console.log('─'.repeat(80));
    versions.forEach((v) => {
      const restored = v.restoredFrom > 0 ? ` (restored from v${v.restoredFrom})` : '';
      console.log(`  v${v.version.toString().padStart(3)}  ${v.created}  by ${v.createdBy}  ${v.message ?? ''}${restored}`);
    });
    console.log('─'.repeat(80));
    console.log(`Total: ${versions.length} versions\n`);
  } else {
    console.log(JSON.stringify(versions, null, 2));
  }

  return versions;
}

async function restoreVersion(client: GrafanaClient, uid: string, options: CliOptions): Promise<SaveDashboardResponse> {
  if (!options.version) error('--version is required for restore command');

  const result = await client.restoreDashboardVersion(uid, options.version);

  if (!options.json) {
    console.log('\n✅ Dashboard Restored:\n');
    console.log('─'.repeat(80));
    console.log(`  UID:          ${result.uid}`);
    console.log(`  Restored to:  v${options.version}`);
    console.log(`  New version:  v${result.version}`);
    console.log(`  URL:          ${result.url}`);
    console.log('─'.repeat(80));
  } else {
    console.log(JSON.stringify(result, null, 2));
  }

  return result;
}

function showHelp(): void {
  console.log(`
╔══════════════════════════════════════════════════════════════════════════════╗
║                     Grafana Dashboard CRUD CLI                               ║
╚══════════════════════════════════════════════════════════════════════════════╝

USAGE:
  bun run DashboardCrud.ts <command> [uid] [options]

COMMANDS:
  list              List/search dashboards
  get <uid>         Get dashboard by UID
  create            Create new dashboard from JSON file
  update <uid>      Update existing dashboard from JSON file
  delete <uid>      Delete dashboard by UID
  export <uid>      Export dashboard to JSON file
  import            Import dashboard from JSON file
  clone <uid>       Clone an existing dashboard
  versions <uid>    List dashboard version history
  restore <uid>     Restore dashboard to a specific version
  help              Show this help message

GLOBAL OPTIONS:
  --url, -u         Grafana URL (default: GRAFANA_URL env var)
  --token, -t       Service account token (default: GRAFANA_TOKEN env var)
  --org-id, -o      Organization ID (default: GRAFANA_ORG_ID env var)
  --json, -j        Output as JSON
  --quiet           Suppress non-essential output

COMMAND OPTIONS:
  --file, -f        Input JSON file (for create/update/import)
  --output          Output file path (for export, default: <uid>.json)
  --folder          Target folder UID
  --title           Dashboard title (overrides JSON)
  --message, -m     Commit message for version history
  --overwrite       Force overwrite existing dashboard
  --query, -q       Search query (for list)
  --tag             Filter by tag (for list)
  --limit, -l       Limit results (for list/versions)
  --version, -v     Version number (for restore)

EXAMPLES:
  bun run DashboardCrud.ts list --query production --tag monitoring
  bun run DashboardCrud.ts get abc123
  bun run DashboardCrud.ts export abc123 --output my-dashboard.json
  bun run DashboardCrud.ts create --file dashboard.json --folder my-folder
  bun run DashboardCrud.ts clone abc123 --title "Production Copy"
  bun run DashboardCrud.ts restore abc123 --version 5

ENVIRONMENT VARIABLES:
  GRAFANA_URL       Grafana instance URL
  GRAFANA_TOKEN     Service account token
  GRAFANA_ORG_ID    Organization ID (optional)
`);
}

// =============================================================================
// Main
// =============================================================================

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const { command, uid, options } = parseArgs(args);

  if (command === 'help' || args.length === 0) {
    showHelp();
    return;
  }

  let client: GrafanaClient;
  try {
    client = createGrafanaClient({
      baseUrl: options.url,
      token: options.token,
      orgId: options.orgId,
    });
  } catch (err) {
    error((err as Error).message);
  }

  try {
    switch (command) {
      case 'list': await listDashboards(client, options); break;
      case 'get': if (!uid) error('Dashboard UID required'); await getDashboard(client, uid!, options); break;
      case 'create': await createDashboard(client, options); break;
      case 'update': if (!uid) error('Dashboard UID required'); await updateDashboard(client, uid!, options); break;
      case 'delete': if (!uid) error('Dashboard UID required'); await deleteDashboard(client, uid!, options); break;
      case 'export': if (!uid) error('Dashboard UID required'); await exportDashboard(client, uid!, options); break;
      case 'import': await importDashboard(client, options); break;
      case 'clone': if (!uid) error('Source dashboard UID required'); await cloneDashboard(client, uid!, options); break;
      case 'versions': if (!uid) error('Dashboard UID required'); await listVersions(client, uid!, options); break;
      case 'restore': if (!uid) error('Dashboard UID required'); await restoreVersion(client, uid!, options); break;
      default: error(`Unknown command: ${command}`);
    }
  } catch (err) {
    const apiError = err as GrafanaApiError;
    if (apiError.statusCode) {
      error(`[${apiError.statusCode}] ${apiError.message}`);
    } else {
      error((err as Error).message);
    }
  }
}

main();
