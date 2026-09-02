#!/usr/bin/env bun
/**
 * GrafanaClient - TypeScript HTTP API Client for Grafana
 *
 * Comprehensive library for Grafana HTTP API interactions.
 * Supports dashboards, data sources, alerting, folders, annotations, and more.
 *
 * @example
 * ```typescript
 * import { GrafanaClient, createGrafanaClient } from './GrafanaClient';
 *
 * const client = createGrafanaClient(); // Uses GRAFANA_URL and GRAFANA_TOKEN env vars
 * const dashboards = await client.searchDashboards({ query: 'production' });
 * ```
 */

// =============================================================================
// Types & Interfaces
// =============================================================================

export interface GrafanaConfig {
  baseUrl: string;
  token: string;
  orgId?: number;
  timeout?: number;
}

export interface GrafanaApiError extends Error {
  statusCode: number;
  response: Record<string, unknown>;
}

export interface SearchDashboardsParams {
  query?: string;
  tag?: string;
  folderUid?: string;
  starred?: boolean;
  limit?: number;
  page?: number;
}

export interface DashboardSearchResult {
  id: number;
  uid: string;
  title: string;
  uri: string;
  url: string;
  slug: string;
  type: string;
  tags: string[];
  isStarred: boolean;
  folderId?: number;
  folderUid?: string;
  folderTitle?: string;
  folderUrl?: string;
  sortMeta: number;
}

export interface DashboardMeta {
  type: string;
  canSave: boolean;
  canEdit: boolean;
  canAdmin: boolean;
  canStar: boolean;
  canDelete: boolean;
  slug: string;
  url: string;
  expires: string;
  created: string;
  updated: string;
  updatedBy: string;
  createdBy: string;
  version: number;
  hasAcl: boolean;
  isFolder: boolean;
  folderId?: number;
  folderUid?: string;
  folderTitle?: string;
  folderUrl?: string;
  provisioned: boolean;
  provisionedExternalId?: string;
}

export interface DashboardModel {
  id?: number | null;
  uid?: string | null;
  title: string;
  tags?: string[];
  timezone?: string;
  schemaVersion?: number;
  version?: number;
  refresh?: string;
  panels?: Panel[];
  templating?: { list: TemplateVariable[] };
  annotations?: { list: AnnotationQuery[] };
  time?: { from: string; to: string };
  timepicker?: Record<string, unknown>;
  description?: string;
}

export interface Panel {
  id: number;
  type: string;
  title: string;
  gridPos: { h: number; w: number; x: number; y: number };
  targets?: Target[];
  options?: Record<string, unknown>;
  fieldConfig?: Record<string, unknown>;
  datasource?: { type: string; uid: string };
  [key: string]: unknown;
}

export interface Target {
  refId: string;
  datasource?: { type: string; uid: string };
  expr?: string;
  [key: string]: unknown;
}

export interface TemplateVariable {
  name: string;
  type: string;
  datasource?: { type: string; uid: string };
  query?: string | Record<string, unknown>;
  [key: string]: unknown;
}

export interface AnnotationQuery {
  name: string;
  datasource: { type: string; uid: string };
  enable: boolean;
  [key: string]: unknown;
}

export interface DashboardResponse {
  meta: DashboardMeta;
  dashboard: DashboardModel;
}

export interface SaveDashboardRequest {
  dashboard: DashboardModel;
  folderUid?: string;
  message?: string;
  overwrite?: boolean;
}

export interface SaveDashboardResponse {
  id: number;
  uid: string;
  url: string;
  status: string;
  version: number;
  slug: string;
}

export interface DeleteDashboardResponse {
  title: string;
  message: string;
  id: number;
}

export interface DashboardVersion {
  id: number;
  dashboardId: number;
  parentVersion: number;
  restoredFrom: number;
  version: number;
  created: string;
  createdBy: string;
  message: string;
}

export interface FolderModel {
  id: number;
  uid: string;
  title: string;
  url: string;
  hasAcl: boolean;
  canSave: boolean;
  canEdit: boolean;
  canAdmin: boolean;
  canDelete: boolean;
  createdBy: string;
  created: string;
  updatedBy: string;
  updated: string;
  version: number;
  parentUid?: string;
}

export interface CreateFolderRequest {
  title: string;
  uid?: string;
  parentUid?: string;
}

export interface DataSourceModel {
  id: number;
  uid: string;
  orgId: number;
  name: string;
  type: string;
  typeLogoUrl: string;
  access: string;
  url: string;
  basicAuth: boolean;
  isDefault: boolean;
  jsonData?: Record<string, unknown>;
  readOnly: boolean;
}

export interface AnnotationModel {
  id?: number;
  dashboardUID?: string;
  panelId?: number;
  time: number;
  timeEnd?: number;
  tags?: string[];
  text: string;
}

export interface AlertRule {
  uid?: string;
  title: string;
  ruleGroup: string;
  folderUID: string;
  noDataState?: string;
  execErrState?: string;
  for?: string;
  condition: string;
  annotations?: Record<string, string>;
  labels?: Record<string, string>;
  data: AlertRuleQuery[];
}

export interface AlertRuleQuery {
  refId: string;
  relativeTimeRange?: { from: number; to: number };
  datasourceUid: string;
  model: Record<string, unknown>;
}

// =============================================================================
// GrafanaClient Class
// =============================================================================

export class GrafanaClient {
  private baseUrl: string;
  private token: string;
  private orgId?: number;
  private timeout: number;

  constructor(config: GrafanaConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, '');
    this.token = config.token;
    this.orgId = config.orgId;
    this.timeout = config.timeout ?? 30000;
  }

  private async request<T>(
    method: string,
    endpoint: string,
    options?: {
      params?: Record<string, string | number | boolean | undefined>;
      body?: unknown;
    }
  ): Promise<T> {
    const url = new URL(`${this.baseUrl}${endpoint}`);

    if (options?.params) {
      Object.entries(options.params).forEach(([key, value]) => {
        if (value !== undefined) {
          url.searchParams.append(key, String(value));
        }
      });
    }

    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.token}`,
      'Content-Type': 'application/json',
      Accept: 'application/json',
    };

    if (this.orgId) {
      headers['X-Grafana-Org-Id'] = String(this.orgId);
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.timeout);

    try {
      const response = await fetch(url.toString(), {
        method,
        headers,
        body: options?.body ? JSON.stringify(options.body) : undefined,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      let data: unknown;
      const contentType = response.headers.get('content-type');
      if (contentType?.includes('application/json')) {
        data = await response.json();
      } else {
        data = { message: await response.text() };
      }

      if (!response.ok) {
        const error = new Error(
          (data as Record<string, unknown>)?.message?.toString() ?? 'Unknown error'
        ) as GrafanaApiError;
        error.statusCode = response.status;
        error.response = data as Record<string, unknown>;
        throw error;
      }

      return data as T;
    } catch (err) {
      clearTimeout(timeoutId);
      if (err instanceof Error && err.name === 'AbortError') {
        const error = new Error('Request timeout') as GrafanaApiError;
        error.statusCode = 408;
        error.response = { message: 'Request timeout' };
        throw error;
      }
      throw err;
    }
  }

  // ---------------------------------------------------------------------------
  // Health & Info
  // ---------------------------------------------------------------------------

  async health(): Promise<{ commit: string; database: string; version: string }> {
    return this.request('GET', '/api/health');
  }

  // ---------------------------------------------------------------------------
  // Dashboards
  // ---------------------------------------------------------------------------

  async searchDashboards(params?: SearchDashboardsParams): Promise<DashboardSearchResult[]> {
    const queryParams: Record<string, string | number | boolean | undefined> = {
      type: 'dash-db',
      limit: params?.limit ?? 100,
      page: params?.page ?? 1,
    };

    if (params?.query) queryParams.query = params.query;
    if (params?.tag) queryParams.tag = params.tag;
    if (params?.folderUid) queryParams.folderUIDs = params.folderUid;
    if (params?.starred !== undefined) queryParams.starred = params.starred;

    return this.request('GET', '/api/search', { params: queryParams });
  }

  async getDashboardByUid(uid: string): Promise<DashboardResponse> {
    return this.request('GET', `/api/dashboards/uid/${uid}`);
  }

  async saveDashboard(request: SaveDashboardRequest): Promise<SaveDashboardResponse> {
    return this.request('POST', '/api/dashboards/db', { body: request });
  }

  async deleteDashboard(uid: string): Promise<DeleteDashboardResponse> {
    return this.request('DELETE', `/api/dashboards/uid/${uid}`);
  }

  async getDashboardVersions(uid: string, limit?: number): Promise<DashboardVersion[]> {
    const params = limit && limit > 0 ? { limit } : undefined;
    return this.request('GET', `/api/dashboards/uid/${uid}/versions`, { params });
  }

  async restoreDashboardVersion(uid: string, version: number): Promise<SaveDashboardResponse> {
    return this.request('POST', `/api/dashboards/uid/${uid}/restore`, {
      body: { version },
    });
  }

  async getDashboardPermissions(
    uid: string
  ): Promise<Array<{ role?: string; teamId?: number; userId?: number; permission: number }>> {
    return this.request('GET', `/api/dashboards/uid/${uid}/permissions`);
  }

  async updateDashboardPermissions(
    uid: string,
    items: Array<{ role?: string; teamId?: number; userId?: number; permission: number }>
  ): Promise<{ message: string }> {
    return this.request('POST', `/api/dashboards/uid/${uid}/permissions`, {
      body: { items },
    });
  }

  // ---------------------------------------------------------------------------
  // Folders
  // ---------------------------------------------------------------------------

  async listFolders(limit?: number): Promise<FolderModel[]> {
    return this.request('GET', '/api/folders', { params: { limit: limit ?? 1000 } });
  }

  async getFolder(uid: string): Promise<FolderModel> {
    return this.request('GET', `/api/folders/${uid}`);
  }

  async createFolder(request: CreateFolderRequest): Promise<FolderModel> {
    return this.request('POST', '/api/folders', { body: request });
  }

  async updateFolder(uid: string, title: string, version: number, overwrite?: boolean): Promise<FolderModel> {
    return this.request('PUT', `/api/folders/${uid}`, {
      body: { title, version, overwrite: overwrite ?? false },
    });
  }

  async deleteFolder(uid: string, forceDeleteRules?: boolean): Promise<{ message: string }> {
    return this.request('DELETE', `/api/folders/${uid}`, {
      params: { forceDeleteRules: forceDeleteRules ?? false },
    });
  }

  // ---------------------------------------------------------------------------
  // Data Sources
  // ---------------------------------------------------------------------------

  async listDataSources(): Promise<DataSourceModel[]> {
    return this.request('GET', '/api/datasources');
  }

  async getDataSourceByUid(uid: string): Promise<DataSourceModel> {
    return this.request('GET', `/api/datasources/uid/${uid}`);
  }

  async getDataSourceByName(name: string): Promise<DataSourceModel> {
    return this.request('GET', `/api/datasources/name/${name}`);
  }

  async createDataSource(datasource: Partial<DataSourceModel>): Promise<DataSourceModel & { datasource: DataSourceModel }> {
    return this.request('POST', '/api/datasources', { body: datasource });
  }

  async updateDataSource(uid: string, datasource: Partial<DataSourceModel>): Promise<DataSourceModel> {
    return this.request('PUT', `/api/datasources/uid/${uid}`, { body: datasource });
  }

  async deleteDataSource(uid: string): Promise<{ message: string }> {
    return this.request('DELETE', `/api/datasources/uid/${uid}`);
  }

  async healthCheckDataSource(uid: string): Promise<{ status: string; message: string }> {
    return this.request('GET', `/api/datasources/uid/${uid}/health`);
  }

  async queryDataSource(
    queries: Array<{ refId: string; datasource: { uid: string }; [key: string]: unknown }>,
    from: string = 'now-1h',
    to: string = 'now'
  ): Promise<{ results: Record<string, unknown> }> {
    return this.request('POST', '/api/ds/query', { body: { queries, from, to } });
  }

  // ---------------------------------------------------------------------------
  // Annotations
  // ---------------------------------------------------------------------------

  async queryAnnotations(params?: {
    from?: number;
    to?: number;
    dashboardUid?: string;
    panelId?: number;
    tags?: string[];
    limit?: number;
  }): Promise<AnnotationModel[]> {
    const queryParams: Record<string, string | number | boolean | undefined> = {
      limit: params?.limit ?? 100,
    };
    if (params?.from) queryParams.from = params.from;
    if (params?.to) queryParams.to = params.to;
    if (params?.dashboardUid) queryParams.dashboardUID = params.dashboardUid;
    if (params?.panelId) queryParams.panelId = params.panelId;

    return this.request('GET', '/api/annotations', { params: queryParams });
  }

  async createAnnotation(annotation: Omit<AnnotationModel, 'id'>): Promise<AnnotationModel & { id: number }> {
    return this.request('POST', '/api/annotations', { body: annotation });
  }

  async updateAnnotation(id: number, annotation: Partial<AnnotationModel>): Promise<{ message: string }> {
    return this.request('PUT', `/api/annotations/${id}`, { body: annotation });
  }

  async deleteAnnotation(id: number): Promise<{ message: string }> {
    return this.request('DELETE', `/api/annotations/${id}`);
  }

  // ---------------------------------------------------------------------------
  // Alerting
  // ---------------------------------------------------------------------------

  async listAlertRules(): Promise<AlertRule[]> {
    return this.request('GET', '/api/v1/provisioning/alert-rules');
  }

  async getAlertRule(uid: string): Promise<AlertRule> {
    return this.request('GET', `/api/v1/provisioning/alert-rules/${uid}`);
  }

  async createAlertRule(rule: AlertRule): Promise<AlertRule> {
    return this.request('POST', '/api/v1/provisioning/alert-rules', { body: rule });
  }

  async updateAlertRule(uid: string, rule: AlertRule): Promise<AlertRule> {
    return this.request('PUT', `/api/v1/provisioning/alert-rules/${uid}`, { body: rule });
  }

  async deleteAlertRule(uid: string): Promise<void> {
    return this.request('DELETE', `/api/v1/provisioning/alert-rules/${uid}`);
  }

  async listContactPoints(): Promise<Array<Record<string, unknown>>> {
    return this.request('GET', '/api/v1/provisioning/contact-points');
  }

  async getNotificationPolicies(): Promise<Record<string, unknown>> {
    return this.request('GET', '/api/v1/provisioning/policies');
  }

  async getActiveAlerts(): Promise<Array<Record<string, unknown>>> {
    return this.request('GET', '/api/alertmanager/grafana/api/v2/alerts');
  }

  // ---------------------------------------------------------------------------
  // Users & Teams
  // ---------------------------------------------------------------------------

  async getCurrentUser(): Promise<Record<string, unknown>> {
    return this.request('GET', '/api/user');
  }

  async searchUsers(params?: { query?: string; perpage?: number; page?: number }): Promise<{ totalCount: number; users: Array<Record<string, unknown>> }> {
    return this.request('GET', '/api/users/search', {
      params: { query: params?.query, perpage: params?.perpage ?? 100, page: params?.page ?? 1 },
    });
  }

  async searchTeams(params?: { query?: string; perpage?: number; page?: number }): Promise<{ totalCount: number; teams: Array<Record<string, unknown>> }> {
    return this.request('GET', '/api/teams/search', {
      params: { query: params?.query, perpage: params?.perpage ?? 100, page: params?.page ?? 1 },
    });
  }

  async getTeam(teamId: number): Promise<Record<string, unknown>> {
    return this.request('GET', `/api/teams/${teamId}`);
  }

  async createTeam(name: string, email?: string): Promise<{ teamId: number; message: string }> {
    return this.request('POST', '/api/teams', { body: { name, email } });
  }

  async deleteTeam(teamId: number): Promise<{ message: string }> {
    return this.request('DELETE', `/api/teams/${teamId}`);
  }

  // ---------------------------------------------------------------------------
  // Service Accounts
  // ---------------------------------------------------------------------------

  async searchServiceAccounts(params?: { query?: string; perpage?: number; page?: number }): Promise<{ totalCount: number; serviceAccounts: Array<Record<string, unknown>> }> {
    return this.request('GET', '/api/serviceaccounts/search', {
      params: { query: params?.query, perpage: params?.perpage ?? 100, page: params?.page ?? 1 },
    });
  }

  async createServiceAccount(name: string, role: 'Viewer' | 'Editor' | 'Admin' = 'Viewer'): Promise<Record<string, unknown>> {
    return this.request('POST', '/api/serviceaccounts', { body: { name, role } });
  }

  async createServiceAccountToken(serviceAccountId: number, name: string, secondsToLive?: number): Promise<{ id: number; name: string; key: string }> {
    return this.request('POST', `/api/serviceaccounts/${serviceAccountId}/tokens`, {
      body: { name, secondsToLive: secondsToLive ?? 0 },
    });
  }

  // ---------------------------------------------------------------------------
  // Organizations
  // ---------------------------------------------------------------------------

  async getCurrentOrg(): Promise<Record<string, unknown>> {
    return this.request('GET', '/api/org');
  }

  async listOrgs(): Promise<Array<Record<string, unknown>>> {
    return this.request('GET', '/api/orgs');
  }

  async createOrg(name: string): Promise<{ orgId: number; message: string }> {
    return this.request('POST', '/api/orgs', { body: { name } });
  }
}

// =============================================================================
// Factory function
// =============================================================================

export function createGrafanaClient(config?: Partial<GrafanaConfig>): GrafanaClient {
  const baseUrl = config?.baseUrl ?? process.env.GRAFANA_URL;
  const token = config?.token ?? process.env.GRAFANA_TOKEN;

  if (!baseUrl) throw new Error('GRAFANA_URL environment variable or baseUrl config required');
  if (!token) throw new Error('GRAFANA_TOKEN environment variable or token config required');

  return new GrafanaClient({
    baseUrl,
    token,
    orgId: config?.orgId ?? (process.env.GRAFANA_ORG_ID ? parseInt(process.env.GRAFANA_ORG_ID) : undefined),
    timeout: config?.timeout,
  });
}
