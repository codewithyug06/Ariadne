// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ACTION_COLORS } from '../api/client';
import { formatRelativeTime, riskColor } from './AgentList';
import { useAgentTraceStream } from '../hooks/useAgentTraceStream';
import { useAgent, useAgentRuns } from '../hooks/useRuns';

const RUNS_PAGE_SIZE = 25;

export function AgentDetail() {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const [runsOffset, setRunsOffset] = useState(0);
  const [showTrace, setShowTrace] = useState(false);

  const { data: agent, error: agentError, isLoading: agentLoading } = useAgent(agentId ?? null);
  const { data: runsData, error: runsError, isLoading: runsLoading } = useAgentRuns(
    agentId ?? null,
    RUNS_PAGE_SIZE,
    runsOffset,
  );

  if (agentError) {
    return <div className="error">Could not load agent: {String(agentError)}</div>;
  }
  if (agentLoading && !agent) {
    return <div className="empty">Loading…</div>;
  }
  if (!agent) {
    return <div className="empty">Agent not found.</div>;
  }

  const runs = runsData?.items ?? [];
  const runsTotal = runsData?.total ?? 0;

  return (
    <>
      <div className="page-header">
        <h1>{agent.name}</h1>
        <span className="subtitle mono">{agent.agent_identity}</span>
      </div>

      <div className="card">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24, alignItems: 'center' }}>
          <Stat label="Risk score">
            <RiskBar score={agent.risk_score} />
          </Stat>
          <Stat label="Total runs" value={agent.total_runs} />
          <Stat label="Blocked" value={agent.total_blocked} />
          <Stat label="Escalated" value={agent.total_escalated} />
          <Stat label="Avg drift" value={agent.avg_drift_score.toFixed(1)} />
          <Stat label="Last seen" value={formatRelativeTime(agent.last_seen_at)} />
          <button onClick={() => setShowTrace((v) => !v)} style={{ marginLeft: 'auto' }}>
            {showTrace ? 'Hide live trace' : 'Live Trace'}
          </button>
        </div>
      </div>

      {/*
        TODO(agent-risk-trend): needs a time-series endpoint. The Agent model
        only stores a current aggregate (risk_score / avg_drift_score), not a
        history of values over time. A Recharts LineChart with one real data
        point (or invented history) would be actively misleading in a
        security product, so we render the current aggregate above instead
        and skip the trend chart until a backend endpoint exists.
      */}

      <div className={showTrace ? 'split' : undefined}>
        <div className="card">
          <h2>Recent runs</h2>
          {runsError ? (
            <div className="error">Could not load runs: {String(runsError)}</div>
          ) : runsLoading && runs.length === 0 ? (
            <div className="empty">Loading…</div>
          ) : runs.length === 0 ? (
            <div className="empty">No runs recorded for this agent yet.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Session</th>
                  <th>Started</th>
                  <th style={{ textAlign: 'right' }}>Steps</th>
                  <th style={{ textAlign: 'right' }}>Peak drift</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr
                    key={run.session_id}
                    className="clickable"
                    onClick={() => navigate(`/runs/${encodeURIComponent(run.session_id)}`)}
                  >
                    <td className="mono">{truncate(run.session_id, 24)}</td>
                    <td className="mono">{new Date(run.started_at).toLocaleString()}</td>
                    <td style={{ textAlign: 'right' }} className="mono">
                      {run.total_steps}
                    </td>
                    <td style={{ textAlign: 'right' }} className="mono">
                      {run.max_drift_score.toFixed(1)}
                    </td>
                    <td>
                      <span className={`badge ${run.final_status}`}>{run.final_status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {runsTotal > RUNS_PAGE_SIZE && (
            <div className="toolbar" style={{ marginTop: 12, marginBottom: 0 }}>
              <button
                disabled={runsOffset === 0}
                onClick={() => setRunsOffset(Math.max(0, runsOffset - RUNS_PAGE_SIZE))}
              >
                Previous
              </button>
              <span style={{ fontSize: 12, color: '#8b98a9' }}>
                {runsOffset + 1}–{Math.min(runsOffset + RUNS_PAGE_SIZE, runsTotal)} of {runsTotal}
              </span>
              <button
                disabled={runsOffset + RUNS_PAGE_SIZE >= runsTotal}
                onClick={() => setRunsOffset(runsOffset + RUNS_PAGE_SIZE)}
              >
                Next
              </button>
            </div>
          )}
        </div>

        {showTrace && <LiveTracePanel agentIdentity={agent.agent_identity} />}
      </div>
    </>
  );
}

function LiveTracePanel({ agentIdentity }: { agentIdentity: string }) {
  const { updates, connected, filteredByAgent } = useAgentTraceStream(agentIdentity);

  return (
    <div className="card">
      <h2>Live trace {connected ? '· connected' : '· connecting…'}</h2>
      {!filteredByAgent && (
        <div className="empty" style={{ marginBottom: 12 }}>
          Live trace requires backend support for per-agent filtering — showing unfiltered
          global stream below. The current WebSocket payload (
          <code className="mono">DriftUpdate</code>) does not carry an agent identifier, so
          events from every session appear here, not just this agent&apos;s.
        </div>
      )}
      {updates.length === 0 ? (
        <div className="empty">No events yet.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Session</th>
              <th>Tool</th>
              <th style={{ textAlign: 'right' }}>Drift</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {updates.map((update) => (
              <tr key={`${update.session_id}-${update.step_index}`}>
                <td className="mono">{truncate(update.session_id, 20)}</td>
                <td className="mono">{update.tool_name}</td>
                <td style={{ textAlign: 'right' }} className="mono">
                  {update.drift_score.toFixed(1)}
                </td>
                <td>
                  <span
                    className={`badge ${update.enforcement_action}`}
                    style={{ color: ACTION_COLORS[update.enforcement_action] }}
                  >
                    {update.enforcement_action}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Stat({ label, value, children }: { label: string; value?: string | number; children?: ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 600 }}>{children ?? value}</div>
    </div>
  );
}

function RiskBar({ score }: { score: number }) {
  const color = riskColor(score);
  const pct = Math.min(100, Math.max(0, score));
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span className="mono" style={{ color, fontSize: 18, fontWeight: 600 }}>
        {score.toFixed(1)}
      </span>
      <div style={{ width: 80, height: 8, borderRadius: 4, background: 'var(--border)', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color }} />
      </div>
    </div>
  );
}

function truncate(value: string, limit: number): string {
  return value.length <= limit ? value : `${value.slice(0, limit - 1)}…`;
}
