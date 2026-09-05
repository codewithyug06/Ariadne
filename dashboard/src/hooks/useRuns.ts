// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import useSWR from 'swr';
import {
  api,
  type Agent,
  type AgentListResponse,
  type AgentRunsResponse,
  type AlertListResponse,
  type AnalyticsSummary,
  type CalibrationProfile,
  type ComponentStatus,
  type PendingApproval,
  type PolicyListResponse,
  type RunDetail,
  type RunListResponse,
  type SessionGraph,
  type SettingsSummary,
  type ToolOverrideListResponse,
} from '../api/client';

/** Active runs change constantly; finished ones do not. */
const LIVE_REFRESH_MS = 4000;

export function useRuns(limit = 25, offset = 0) {
  return useSWR<RunListResponse>(
    ['runs', limit, offset],
    () => api.listRuns(limit, offset),
    { refreshInterval: LIVE_REFRESH_MS, keepPreviousData: true },
  );
}

export function useRun(sessionId: string | null) {
  return useSWR<RunDetail>(
    sessionId ? ['run', sessionId] : null,
    () => api.getRun(sessionId as string),
    { refreshInterval: LIVE_REFRESH_MS },
  );
}

export function useGraph(sessionId: string | null) {
  return useSWR<SessionGraph>(
    sessionId ? ['graph', sessionId] : null,
    () => api.getGraph(sessionId as string),
    { refreshInterval: LIVE_REFRESH_MS },
  );
}

export function usePolicies() {
  return useSWR<PolicyListResponse>('policies', () => api.listPolicies());
}

export function useStatus() {
  return useSWR<ComponentStatus>('status', () => api.getStatus(), {
    refreshInterval: 10000,
  });
}

export function useAlerts(params: { acknowledged?: boolean; limit?: number; offset?: number } = {}) {
  return useSWR<AlertListResponse>(
    ['alerts', params.acknowledged, params.limit, params.offset],
    () => api.listAlerts(params),
    { refreshInterval: LIVE_REFRESH_MS },
  );
}

export function usePendingApprovals() {
  return useSWR<PendingApproval[]>('hitl-pending', () => api.listPendingApprovals(), {
    refreshInterval: LIVE_REFRESH_MS,
  });
}

export function useAnalytics(since?: string, until?: string) {
  return useSWR<AnalyticsSummary>(['analytics', since, until], () =>
    api.analyticsSummary({ since, until }),
  );
}

export function useSettingsSummary() {
  return useSWR<SettingsSummary>('settings', () => api.getSettings(), {
    refreshInterval: 10000,
  });
}

// ---- Agents (Feature 6) -------------------------------------------------

export function useAgents(limit = 25, offset = 0) {
  return useSWR<AgentListResponse>(
    ['agents', limit, offset],
    () => api.agents.list({ limit, offset }),
    { refreshInterval: LIVE_REFRESH_MS, keepPreviousData: true },
  );
}

export function useAgent(agentId: string | null) {
  return useSWR<Agent>(
    agentId ? ['agent', agentId] : null,
    () => api.agents.get(agentId as string),
    { refreshInterval: LIVE_REFRESH_MS },
  );
}

export function useAgentRuns(agentId: string | null, limit = 25, offset = 0) {
  return useSWR<AgentRunsResponse>(
    agentId ? ['agent-runs', agentId, limit, offset] : null,
    () => api.agents.getRuns(agentId as string, { limit, offset }),
    { refreshInterval: LIVE_REFRESH_MS, keepPreviousData: true },
  );
}

// ---- Org tool-risk overrides (Feature 10) -------------------------------

export function useToolOverrides() {
  return useSWR<ToolOverrideListResponse>('tool-overrides', () => api.toolOverrides.list());
}

// ---- Calibration (Feature 9) --------------------------------------------

export function useCalibrationProfiles() {
  return useSWR<CalibrationProfile[]>('calibration-profiles', () => api.calibration.list());
}

export function useActiveCalibrationProfile() {
  return useSWR<CalibrationProfile>('calibration-active', () => api.calibration.active());
}
