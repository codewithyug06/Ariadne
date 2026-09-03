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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  });
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
    return `${protocol}//${window.location.host}/ws/runs/${encodeURIComponent(sessionId)}/live`;
  },

  liveAlertsUrl: () => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}/ws/alerts/live`;
  },
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
