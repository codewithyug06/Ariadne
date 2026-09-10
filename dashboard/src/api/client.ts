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

export interface DriftNarrative {
  summary: string;
  detail: string;
  trigger: string;
  consecutive_escalation_steps: number;
  first_divergence_step: number | null;
}

export interface RiskDimension {
  value: number;
  label: string;
  contributing_factor: string;
}

export interface RiskDimensionReport {
  intent: RiskDimension;
  tool: RiskDimension;
  privilege: RiskDimension;
  identity: RiskDimension;
  data: RiskDimension;
  aggregate: number;
  timestamp: string;
}

// ---- Feature 8: drift extrapolation ------------------------------------
// Mirrors ariadne/drift/extrapolator.py's DriftProjection exactly.

export interface DriftProjection {
  current_score: number;
  projections: Record<number, number>;
  confidence: 'high' | 'moderate';
  basis: string;
  label: string;
  will_cross_warn: boolean;
  will_cross_block: boolean;
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
  narrative: DriftNarrative | null;
  risk_dimensions: RiskDimensionReport | null;
  // Feature 8: linear drift extrapolation, null when the fit isn't trustworthy.
  projection: DriftProjection | null;
  // Feature 9: the ScoringVersionStamp in effect when this event was scored.
  scoring_version: Record<string, unknown> | null;
  // Feature 9: human-readable calibration context for this event's drift score.
  calibration_note: string | null;
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
  // Feature 8: streamed alongside the drift score on the live WebSocket.
  // Optional because older buffered/replayed messages may not carry it.
  projection?: DriftProjection | null;
  // The originating ToolCall's calling_agent_id ("unknown" if unset).
  // Optional/defaulted for the same reason as `projection` above.
  agent_identity?: string;
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

// ---- Backtest (Feature 5A/5B) -------------------------------------------
// Mirrors ariadne/eval/backtester.py's Pydantic models exactly.

export interface ProposedPolicy {
  name: string;
  action: EnforcementAction;
  tool_name_patterns: string[];
  argument_patterns: string[];
  drift_warn: number | null;
  drift_escalate: number | null;
  drift_block: number | null;
}

export interface BacktestRunFilter {
  date_from: string | null;
  date_to: string | null;
  agent_id: string | null;
  final_status: string[] | null;
  limit: number;
}

export interface BacktestRunDiff {
  session_id: string;
  agent_name: string | null;
  real_decision: string;
  proposed_decision: string;
  changed_at_step: number;
  impact: 'incident_prevented' | 'false_positive_added' | 'false_negative_added';
}

export interface BacktestReport {
  job_id: string;
  organization_id: string;
  runs_analyzed: number;
  date_range: [string, string] | null;
  baseline_detection_rate: number;
  baseline_fpr: number;
  baseline_blocks: number;
  baseline_escalations: number;
  proposed_detection_rate: number;
  proposed_fpr: number;
  proposed_blocks: number;
  proposed_escalations: number;
  incidents_prevented_delta: number;
  false_positive_delta: number;
  detection_rate_delta: number;
  fpr_delta: number;
  changed_runs: BacktestRunDiff[];
  recommendation: 'DEPLOY' | 'REVIEW' | 'DO NOT DEPLOY';
  recommendation_reason: string;
  completed_at: string;
}

export interface BacktestJobStatus {
  status: 'pending' | 'running' | 'complete' | 'failed';
  result: unknown;
  error: string | null;
}

export interface SimulateRunResult {
  session_id: string;
  found: boolean;
  would_be_prevented: boolean;
  prevented_at_step: number | null;
  real_max_action: EnforcementAction | null;
  proposed_max_action: EnforcementAction | null;
}

// ---- Agents (Feature 6) -------------------------------------------------
// Mirrors ariadne/api/agents.py's Pydantic models exactly.

export interface Agent {
  id: string;
  name: string;
  agent_identity: string;
  total_runs: number;
  total_blocked: number;
  total_escalated: number;
  avg_drift_score: number;
  risk_score: number;
  created_at: string;
  last_seen_at: string;
}

export interface AgentListResponse {
  items: Agent[];
  total: number;
  limit: number;
  offset: number;
}

export interface AgentRunListItem {
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

export interface AgentRunsResponse {
  items: AgentRunListItem[];
  total: number;
  limit: number;
  offset: number;
}

// ---- Calibration (Feature 9) --------------------------------------------
// Mirrors ariadne/api/admin.py's CalibrationProfileResponse exactly.

export interface CalibrationProfile {
  id: string;
  version: string;
  is_active: boolean;
  calibrated_at: string;
  dataset: string;
  sample_size: number;
  highest_benign_score: number;
  measured_fpr: number;
  measured_detection_rate: number;
  score_to_precision: Record<string, number>;
  recommended_warn: number;
  recommended_escalate: number;
  recommended_block: number;
  notes: string;
  created_at: string;
}

// ---- Org tool-risk overrides (Feature 10) -------------------------------
// Mirrors ariadne/api/policies.py's ToolOverrideResponse exactly.

export interface ToolOverride {
  id: string;
  tool_name: string;
  risk_override: number;
  created_by: string;
}

export interface ToolOverrideListResponse {
  items: ToolOverride[];
}

// ---- Minimum Intervention Analysis (Feature 11) -------------------------
// Mirrors ariadne/eval/intervention.py's Pydantic models exactly.

export interface InterventionCandidateResult {
  policy_name: string;
  prevented: boolean;
  prevented_at_step: number | null;
  new_false_positives_on_clean_sample: number;
  disruption_score: number;
}

export interface MinimumInterventionReport {
  incident_session_id: string;
  candidates: InterventionCandidateResult[];
  recommended: InterventionCandidateResult | null;
  recommendation_reason: string;
}

export interface MinimumInterventionJobResponse {
  job_id: string;
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

// Exported so AuthContext's mount-time "trade the refresh cookie for an
// access token" effect goes through the same dedup gate as every other
// caller. The refresh cookie is single-use/rotated server-side — two
// independent, un-deduped refresh calls racing on page load would mean
// whichever one loses gets a legitimate 401 on an already-rotated cookie,
// which used to incorrectly log out an otherwise-valid session.
export async function silentRefresh(): Promise<boolean> {
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

  // A WebSocket handshake can't set an Authorization header, so each
  // connection trades the in-memory access token for a short-lived,
  // single-use ticket (POST /api/v1/auth/ws-ticket) instead of putting the
  // access token itself in the URL. See ariadne/auth/ws_tickets.py.
  liveRunUrl: async (sessionId: string) => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ticket = accessToken ? await api.wsTicket() : '';
    const query = ticket ? `?ticket=${encodeURIComponent(ticket)}` : '';
    return `${protocol}//${window.location.host}/ws/runs/${encodeURIComponent(sessionId)}/live${query}`;
  },

  liveAlertsUrl: async () => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ticket = accessToken ? await api.wsTicket() : '';
    const query = ticket ? `?ticket=${encodeURIComponent(ticket)}` : '';
    return `${protocol}//${window.location.host}/ws/alerts/live${query}`;
  },

  // ---- Auth --------------------------------------------------------------
  login: (email: string, password: string) =>
    request<LoginResponse>(`${API_BASE}/auth/login`, {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  googleLogin: (payload: { credential?: string; access_token?: string }) =>
    request<LoginResponse>(`${API_BASE}/auth/google`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  logout: () => request<void>(`${API_BASE}/auth/logout`, { method: 'POST' }),

  me: () => request<CurrentUser>(`${API_BASE}/auth/me`),

  wsTicket: () =>
    request<{ ticket: string }>(`${API_BASE}/auth/ws-ticket`, { method: 'POST' }).then(
      (body) => body.ticket,
    ),

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

  // ---- Billing -----------------------------------------------------------
  billing: {
    getUpgradeInfo: () =>
      request<{ plan: string; payment_link: string }>(`${API_BASE}/billing/upgrade`),
  },

  // ---- Settings --------------------------------------------------------
  getSettings: () => request<SettingsSummary>(`${API_BASE}/settings`),

  updateThresholds: (thresholds: { warn: number; escalate: number; block: number }) =>
    request<{ warn: number; escalate: number; block: number }>(`${API_BASE}/settings/thresholds`, {
      method: 'PATCH',
      body: JSON.stringify(thresholds),
    }),

  // ---- Backtest (Feature 5A/5B) ----------------------------------------
  backtest: {
    run: (proposedPolicy: ProposedPolicy, runFilter: Partial<BacktestRunFilter> = {}) =>
      request<{ job_id: string }>(`${API_BASE}/eval/backtest`, {
        method: 'POST',
        body: JSON.stringify({ proposed_policy: proposedPolicy, run_filter: runFilter }),
      }),

    status: (jobId: string) =>
      request<BacktestJobStatus>(`${API_BASE}/eval/backtest/${encodeURIComponent(jobId)}`),

    report: (jobId: string, format: 'json' | 'markdown' = 'json') =>
      request<BacktestReport>(
        `${API_BASE}/eval/backtest/${encodeURIComponent(jobId)}/report?format=${format}`,
      ),

    simulateRun: (sessionId: string, proposedPolicy: ProposedPolicy) =>
      request<SimulateRunResult>(
        `${API_BASE}/eval/simulate-run/${encodeURIComponent(sessionId)}`,
        { method: 'POST', body: JSON.stringify(proposedPolicy) },
      ),
  },

  // ---- Agents (Feature 6) -----------------------------------------------
  agents: {
    list: (params: { limit?: number; offset?: number } = {}) => {
      const query = new URLSearchParams();
      query.set('limit', String(params.limit ?? 25));
      query.set('offset', String(params.offset ?? 0));
      return request<AgentListResponse>(`${API_BASE}/agents?${query.toString()}`);
    },

    get: (id: string) => request<Agent>(`${API_BASE}/agents/${encodeURIComponent(id)}`),

    getRuns: (id: string, params: { limit?: number; offset?: number } = {}) => {
      const query = new URLSearchParams();
      query.set('limit', String(params.limit ?? 25));
      query.set('offset', String(params.offset ?? 0));
      return request<AgentRunsResponse>(
        `${API_BASE}/agents/${encodeURIComponent(id)}/runs?${query.toString()}`,
      );
    },

    create: (payload: { name: string; agent_identity: string }) =>
      request<Agent>(`${API_BASE}/agents`, {
        method: 'POST',
        body: JSON.stringify(payload),
      }),

    update: (id: string, payload: { name: string }) =>
      request<Agent>(`${API_BASE}/agents/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      }),
  },

  // ---- Calibration (Feature 9, admin only) ------------------------------
  calibration: {
    list: () => request<CalibrationProfile[]>(`${API_BASE}/admin/calibration`),

    active: () => request<CalibrationProfile>(`${API_BASE}/admin/calibration/active`),

    recalibrate: (
      body: { version: string; limit?: number; max_fpr?: number; dataset?: string; notes?: string },
    ) =>
      request<CalibrationProfile>(`${API_BASE}/admin/calibration/recalibrate`, {
        method: 'POST',
        body: JSON.stringify(body),
      }),

    activate: (version: string) =>
      request<CalibrationProfile>(
        `${API_BASE}/admin/calibration/${encodeURIComponent(version)}/activate`,
        { method: 'POST' },
      ),
  },

  // ---- Org tool-risk overrides (Feature 10) -----------------------------
  toolOverrides: {
    list: () => request<ToolOverrideListResponse>(`${API_BASE}/policies/tool-overrides`),

    create: (payload: { tool_name: string; risk_override: number }) =>
      request<ToolOverride>(`${API_BASE}/policies/tool-overrides`, {
        method: 'POST',
        body: JSON.stringify(payload),
      }),

    delete: (id: string) =>
      request<void>(`${API_BASE}/policies/tool-overrides/${encodeURIComponent(id)}`, {
        method: 'DELETE',
      }),
  },

  // ---- Minimum Intervention Analysis (Feature 11) -----------------------
  eval: {
    minimumIntervention: (body: {
      incident_session_id: string;
      candidate_policies?: ProposedPolicy[];
      clean_run_sample_size?: number;
    }) =>
      request<MinimumInterventionReport | MinimumInterventionJobResponse>(
        `${API_BASE}/eval/minimum-intervention`,
        { method: 'POST', body: JSON.stringify(body) },
      ),
  },
};

export const ACTION_COLORS: Record<EnforcementAction, string> = {
  ALLOW: '#059669',
  WARN: '#d97706',
  ESCALATE: '#ea580c',
  BLOCK: '#dc2626',
};

export const STATUS_COLORS: Record<RunStatus, string> = {
  CLEAN: '#059669',
  WARNED: '#d97706',
  ESCALATED: '#ea580c',
  BLOCKED: '#dc2626',
};
