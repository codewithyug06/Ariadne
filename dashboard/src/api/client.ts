// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0
//
// Hand-rolled typed client. The shapes mirror the Pydantic models in
// ariadne/api and ariadne/graph/schemas.py.

export type EnforcementAction = 'ALLOW' | 'WARN' | 'ESCALATE' | 'BLOCK';
export type RunStatus = 'CLEAN' | 'WARNED' | 'ESCALATED' | 'BLOCKED';

export type NodeType =
  | 'user_request'
  | 'tool_call'
  | 'tool_result'
  | 'sub_agent_invocation'
  | 'memory_write'
  | 'final_output'
  | 'alert';

export type EdgeType =
  | 'caused_by'
  | 'informed_by'
  | 'contradicts'
  | 'escalates_privilege'
  | 'produces'
  | 'calls';

export interface RunListItem {
  session_id: string;
  started_at: string;
  ended_at: string | null;
  total_steps: number;
  final_status: RunStatus;
  max_drift_score: number;
  intent_summary: string;
  blocked_count: number;
  escalated_count: number;
  warned_count: number;
}

export interface RunListResponse {
  items: RunListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditEvent {
  event_id: string;
  session_id: string;
  step_index: number;
  tool_name: string;
  enforcement_action: EnforcementAction;
  reason: string;
  triggered_rule: string | null;
  drift_score: number | null;
  slope: number | null;
  raw_distance: number | null;
  node_id: string | null;
  latency_ms: number;
  payload: Record<string, unknown>;
  timestamp: string;
}

export interface RunSummary {
  session_id: string;
  started_at: string;
  ended_at: string | null;
  total_steps: number;
  final_status: RunStatus;
  intent_summary: string;
  max_drift_score: number;
  blocked_count: number;
  escalated_count: number;
  warned_count: number;
}

export interface RunDetail {
  run: RunSummary;
  events: AuditEvent[];
  active: boolean;
}

export interface GraphNode {
  id: string;
  session_id: string;
  node_type: NodeType;
  step_index: number;
  label: string;
  payload: Record<string, unknown>;
  drift_score: number | null;
  enforcement_action: EnforcementAction | 'PENDING' | null;
  timestamp: string;
  metadata: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source_id: string;
  target_id: string;
  edge_type: EdgeType;
  metadata: Record<string, unknown>;
}

export interface SessionGraph {
  session_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  root_cause_node_id: string | null;
}

export interface DriftUpdate {
  session_id: string;
  step_index: number;
  tool_name: string;
  drift_score: number;
  slope: number;
  raw_distance: number;
  enforcement_action: EnforcementAction;
  reason: string;
  node_id: string | null;
  timestamp: string;
}

export interface Policy {
  name: string;
  description: string;
  action: EnforcementAction;
  enabled: boolean;
  tool_name_patterns: string[];
  argument_patterns: string[];
  requires_hitl_token: boolean;
}

export interface PolicyListResponse {
  items: Policy[];
  backend: string;
}

export interface ComponentStatus {
  embedder_backend: string;
  embedder_degraded: boolean;
  graph_backend: string;
  policy_backend: string;
  fail_mode: string;
  active_sessions: number;
  pending_audit_writes: number;
  dropped_audit_events: number;
  pending_approvals: number;
  stream_subscribers: number;
  drift_thresholds: { warn: number; escalate: number; block: number };
}

export type UserRole = 'viewer' | 'admin';

export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: UserRole;
  expires_in_seconds: number;
}

export interface CurrentUser {
  id: string;
  email: string;
  role: UserRole;
}

export interface AlertItem {
  alert_id: string;
  session_id: string;
  step_index: number;
  tool_name: string;
  action: EnforcementAction;
  reason: string;
  drift_score: number | null;
  node_id: string | null;
  acknowledged: boolean;
  created_at: string;
}

export interface AlertListResponse {
  items: AlertItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface PendingApproval {
  approval_id: string;
  session_id: string;
  step_index: number;
  tool_name: string;
  arguments: Record<string, unknown>;
  reason: string;
  drift_score: number | null;
  triggered_rule: string | null;
  node_id: string | null;
  opened_at: string;
}

export interface DailyVolume {
  date: string;
  total: number;
  allowed: number;
  warned: number;
  escalated: number;
  blocked: number;
}

export interface TriggeredRuleCount {
  rule: string;
  count: number;
}

export interface AnalyticsSummary {
  since: string;
  until: string;
  total_runs: number;
  total_events: number;
  decisions_by_action: Record<string, number>;
  drift_score_buckets: Record<string, number>;
  top_triggered_rules: TriggeredRuleCount[];
  daily_volume: DailyVolume[];
}

export interface SettingsSummary {
  environment: string;
  embedding_model: string;
  embedding_device: string;
  graph_backend: string;
  hard_layer_backend: string;
  fail_mode: string;
  upstream_mcp_url: string;
  cors_origins: string[];
  rate_limit_per_minute: number;
  drift_thresholds: { warn: number; escalate: number; block: number };
  mcp_url: string | null;
}

export interface TeamMember {
  id: string;
  email: string;
  role: UserRole;
  created_at: string;
  last_login_at: string | null;
}

export interface CreatedTeamMember {
  user: TeamMember;
  temporary_password: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

const API_BASE = '/api/v1';

// The access token lives here, not in AuthContext's React state, so a plain
// fetch() helper can read it without importing React or creating a circular
// dependency between the API client and the auth context that authenticates
// it. AuthContext calls setAccessToken() on login/refresh/logout; every
// other module just calls api.* and gets the current token for free.
let accessToken: string | null = null;
let onAuthExpired: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

// AuthContext registers itself here so a silent-refresh failure (the
// httpOnly refresh cookie is gone or expired) can drop the app back to the
// login screen instead of every caller having to check for a 401.
export function onSessionExpired(callback: () => void): void {
  onAuthExpired = callback;
}

let refreshInFlight: Promise<boolean> | null = null;

async function silentRefresh(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!response.ok) return false;
      const body = (await response.json()) as { access_token: string };
      setAccessToken(body.access_token);
      return true;
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

async function request<T>(path: string, init?: RequestInit, _retried = false): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  const response = await fetch(path, { ...init, headers, credentials: 'include' });

  if (response.status === 401 && !_retried && !path.startsWith(`${API_BASE}/auth/`)) {
    if (await silentRefresh()) {
      return request<T>(path, init, true);
    }
    onAuthExpired?.();
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // Non-JSON error body; the status text is the best available message.
    }
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  listRuns: (limit = 25, offset = 0) =>
    request<RunListResponse>(`${API_BASE}/runs?limit=${limit}&offset=${offset}`),

  getRun: (sessionId: string) =>
    request<RunDetail>(`${API_BASE}/runs/${encodeURIComponent(sessionId)}`),

  getGraph: (sessionId: string) =>
    request<SessionGraph>(`${API_BASE}/runs/${encodeURIComponent(sessionId)}/graph`),

  getRootCause: (sessionId: string, nodeId: string) =>
    request<GraphNode[]>(
      `${API_BASE}/runs/${encodeURIComponent(sessionId)}/root-cause?node_id=${encodeURIComponent(nodeId)}`,
    ),

  getBlastRadius: (sessionId: string, nodeId: string) =>
    request<{ node_id: string; affected_node_ids: string[]; affected_labels: string[] }>(
      `${API_BASE}/runs/${encodeURIComponent(sessionId)}/blast-radius?node_id=${encodeURIComponent(nodeId)}`,
    ),

  listPolicies: () => request<PolicyListResponse>(`${API_BASE}/policies`),

  upsertPolicy: (policy: Policy) =>
    request<Policy>(`${API_BASE}/policies`, {
      method: 'POST',
      body: JSON.stringify(policy),
    }),

  deletePolicy: (name: string) =>
    request<void>(`${API_BASE}/policies/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  getStatus: () => request<ComponentStatus>('/status'),

  reportUrl: (sessionId: string, format: 'json' | 'markdown') =>
    `${API_BASE}/runs/${encodeURIComponent(sessionId)}/report?format=${format}`,

  liveRunUrl: (sessionId: string) => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const token = accessToken ? `?token=${encodeURIComponent(accessToken)}` : '';
    return `${protocol}//${window.location.host}/ws/runs/${encodeURIComponent(sessionId)}/live${token}`;
  },

  liveAlertsUrl: () => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const token = accessToken ? `?token=${encodeURIComponent(accessToken)}` : '';
    return `${protocol}//${window.location.host}/ws/alerts/live${token}`;
  },

  // ---- Auth --------------------------------------------------------------
  login: (email: string, password: string) =>
    request<LoginResponse>(`${API_BASE}/auth/login`, {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  logout: () => request<void>(`${API_BASE}/auth/logout`, { method: 'POST' }),

  me: () => request<CurrentUser>(`${API_BASE}/auth/me`),

  changePassword: (currentPassword: string, newPassword: string) =>
    request<void>(`${API_BASE}/auth/password`, {
      method: 'PATCH',
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),

  // ---- Team management (admin only) -----------------------------------
  listUsers: () => request<TeamMember[]>(`${API_BASE}/users`),

  createUser: (email: string, role: UserRole) =>
    request<CreatedTeamMember>(`${API_BASE}/users`, {
      method: 'POST',
      body: JSON.stringify({ email, role }),
    }),

  deleteUser: (userId: string) =>
    request<void>(`${API_BASE}/users/${encodeURIComponent(userId)}`, { method: 'DELETE' }),

  resetUserPassword: (userId: string) =>
    request<{ temporary_password: string }>(
      `${API_BASE}/users/${encodeURIComponent(userId)}/reset-password`,
      { method: 'POST' },
    ),

  // ---- Alerts + HITL -------------------------------------------------------
  listAlerts: (params: { acknowledged?: boolean; action?: EnforcementAction; limit?: number; offset?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.acknowledged !== undefined) query.set('acknowledged', String(params.acknowledged));
    if (params.action) query.set('action', params.action);
    query.set('limit', String(params.limit ?? 25));
    query.set('offset', String(params.offset ?? 0));
    return request<AlertListResponse>(`${API_BASE}/alerts?${query.toString()}`);
  },

  acknowledgeAlert: (alertId: string) =>
    request<AlertItem>(`${API_BASE}/alerts/${encodeURIComponent(alertId)}`, { method: 'PATCH' }),

  listPendingApprovals: () => request<PendingApproval[]>(`${API_BASE}/hitl/pending`),

  resolveApproval: (approvalId: string, approved: boolean) =>
    request<{ approval_id: string; approved: boolean }>(
      `/mcp/hitl/${encodeURIComponent(approvalId)}?approved=${approved}`,
      { method: 'POST' },
    ),

  // ---- Analytics -----------------------------------------------------------
  analyticsSummary: (params: { since?: string; until?: string } = {}) => {
    const query = new URLSearchParams();
    if (params.since) query.set('since', params.since);
    if (params.until) query.set('until', params.until);
    const suffix = query.toString() ? `?${query.toString()}` : '';
    return request<AnalyticsSummary>(`${API_BASE}/analytics/summary${suffix}`);
  },

  // ---- Settings --------------------------------------------------------
  getSettings: () => request<SettingsSummary>(`${API_BASE}/settings`),

  updateThresholds: (thresholds: { warn: number; escalate: number; block: number }) =>
    request<{ warn: number; escalate: number; block: number }>(`${API_BASE}/settings/thresholds`, {
      method: 'PATCH',
      body: JSON.stringify(thresholds),
    }),
};

export const ACTION_COLORS: Record<EnforcementAction, string> = {
  ALLOW: '#3fb950',
  WARN: '#d29922',
  ESCALATE: '#db6d28',
  BLOCK: '#f85149',
};

export const STATUS_COLORS: Record<RunStatus, string> = {
  CLEAN: '#3fb950',
  WARNED: '#d29922',
  ESCALATED: '#db6d28',
  BLOCKED: '#f85149',
};
