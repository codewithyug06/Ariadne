// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState, type ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { formatRelativeTime, riskColor } from './AgentList';
import { useAgentTraceStream } from '../hooks/useAgentTraceStream';
import { useAgent, useAgentRuns } from '../hooks/useRuns';
import {
  ActivityIcon,
  BotIcon,
  CheckIcon,
  CopyIcon,
  ShieldAlertIcon,
  TerminalIcon,
} from './Icons';

const RUNS_PAGE_SIZE = 25;

export function AgentDetail() {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const [runsOffset, setRunsOffset] = useState(0);
  const [showTrace, setShowTrace] = useState(false);
  const [copiedId, setCopiedId] = useState(false);

  const { data: agent, error: agentError, isLoading: agentLoading } = useAgent(agentId ?? null);
  const { data: runsData, error: runsError, isLoading: runsLoading } = useAgentRuns(
    agentId ?? null,
    RUNS_PAGE_SIZE,
    runsOffset,
  );

  const copyIdentity = () => {
    if (!agent) return;
    navigator.clipboard.writeText(agent.agent_identity);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  if (agentError) {
    return (
      <div className="card error">
        <ShieldAlertIcon size={20} />
        <div>Could not load agent details: {String(agentError)}</div>
      </div>
    );
  }
  if (agentLoading && !agent) {
    return (
      <div className="empty" style={{ paddingTop: '20vh' }}>
        <BotIcon size={32} style={{ margin: '0 auto 12px', color: 'var(--accent)' }} />
        <div>Loading agent security telemetry…</div>
      </div>
    );
  }
  if (!agent) {
    return (
      <div className="card empty">
        <ShieldAlertIcon size={32} style={{ margin: '0 auto 12px', color: 'var(--block)' }} />
        <h2>Agent Not Found</h2>
        <p style={{ color: 'var(--text-dim)' }}>No agent registered with identifier {agentId}.</p>
      </div>
    );
  }

  const runs = runsData?.items ?? [];
  const runsTotal = runsData?.total ?? 0;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>
            <Link to="/agents" style={{ color: 'var(--text-dim)' }}>Agents</Link>
            <span style={{ color: 'var(--border-hover)', margin: '0 6px' }}>/</span>
            <span style={{ color: 'var(--text-bright)' }}>{agent.name}</span>
          </h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
            <span className="mono subtitle" style={{ color: 'var(--text-muted)' }}>
              {agent.agent_identity}
            </span>
            <button className="copy-btn" onClick={copyIdentity} title="Copy agent identity">
              {copiedId ? <CheckIcon size={12} style={{ color: 'var(--allow)' }} /> : <CopyIcon size={12} />}
            </button>
          </div>
        </div>

        <div className="actions">
          <button
            className={showTrace ? 'primary' : 'secondary'}
            onClick={() => setShowTrace((v) => !v)}
          >
            <ActivityIcon size={14} />
            <span>{showTrace ? 'Hide Live Trace' : 'Open Live Trace'}</span>
          </button>
        </div>
      </div>

      {/* Agent KPI Metrics */}
      <div className="card">
        <div className="card-header">
          <h2>
            <BotIcon size={16} />
            <span>Security Posture & Cumulative Telemetry</span>
          </h2>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 16 }}>
          <Stat label="Risk Score">
            <RiskBar score={agent.risk_score} />
          </Stat>
          <Stat label="Total Runs" value={agent.total_runs} />
          <Stat label="Total Blocked" value={agent.total_blocked} style={{ color: agent.total_blocked > 0 ? 'var(--block)' : 'inherit' }} />
          <Stat label="Total Escalated" value={agent.total_escalated} style={{ color: agent.total_escalated > 0 ? 'var(--escalate)' : 'inherit' }} />
          <Stat label="Avg Drift Score" value={agent.avg_drift_score.toFixed(1)} />
          <Stat label="Last Active" value={formatRelativeTime(agent.last_seen_at)} />
        </div>
      </div>

      <div className={showTrace ? 'split' : undefined} style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-header">
            <h2>
              <TerminalIcon size={16} />
              <span>Historical Agent Sessions ({runsTotal})</span>
            </h2>
          </div>

          {runsError ? (
            <div className="error">Could not load runs: {String(runsError)}</div>
          ) : runsLoading && runs.length === 0 ? (
            <div className="empty">Loading session records…</div>
          ) : runs.length === 0 ? (
            <div className="empty">No runs recorded for this agent yet.</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Session ID</th>
                    <th>Started</th>
                    <th style={{ textAlign: 'right' }}>Steps</th>
                    <th style={{ textAlign: 'right' }}>Peak Drift</th>
                    <th>Decision</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr
                      key={run.session_id}
                      className="clickable"
                      onClick={() => navigate(`/runs/${run.session_id}`)}
                    >
                      <td className="mono" style={{ fontWeight: 600, color: 'var(--text-bright)' }}>
                        {truncate(run.session_id, 24)}
                      </td>
                      <td className="mono" style={{ color: 'var(--text-dim)', fontSize: 11.5 }}>
                        {new Date(run.started_at).toLocaleString()}
                      </td>
                      <td style={{ textAlign: 'right' }} className="mono">
                        <span style={{ background: 'var(--surface-3)', padding: '2px 6px', borderRadius: 4 }}>
                          {run.total_steps}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right' }} className="mono">
                        {run.max_drift_score.toFixed(1)}
                      </td>
                      <td>
                        <span className={`badge ${run.final_status.toLowerCase()}`}>{run.final_status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {runsTotal > RUNS_PAGE_SIZE && (
            <div className="toolbar" style={{ marginTop: 14, marginBottom: 0 }}>
              <button
                disabled={runsOffset === 0}
                onClick={() => setRunsOffset(Math.max(0, runsOffset - RUNS_PAGE_SIZE))}
              >
                Previous
              </button>
              <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                Page {Math.floor(runsOffset / RUNS_PAGE_SIZE) + 1} of {Math.ceil(runsTotal / RUNS_PAGE_SIZE)} ({runsTotal} total)
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
      <div className="card-header">
        <h2>
          <ActivityIcon size={16} />
          <span>Real-time WebSocket Trace</span>
        </h2>
        <div className="hud-pill" style={{ padding: '2px 8px' }}>
          <span className={`live-dot ${connected ? 'on' : ''}`} />
          <span style={{ fontSize: 11 }}>{connected ? 'Streaming' : 'Connecting…'}</span>
        </div>
      </div>

      {!filteredByAgent && (
        <div
          style={{
            background: 'var(--surface-2)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-sm)',
            padding: '10px 14px',
            fontSize: 12,
            color: 'var(--text-dim)',
            marginBottom: 12,
          }}
        >
          Displaying live global tool execution stream. Events will appear in real time as actions are intercepted.
        </div>
      )}

      {updates.length === 0 ? (
        <div className="empty">Waiting for live tool calls…</div>
      ) : (
        <div className="table-wrap">
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
                  <td className="mono" style={{ fontSize: 11 }}>{truncate(update.session_id, 18)}</td>
                  <td className="mono" style={{ fontWeight: 600 }}>{update.tool_name}</td>
                  <td style={{ textAlign: 'right' }} className="mono">
                    {update.drift_score.toFixed(1)}
                  </td>
                  <td>
                    <span className={`badge ${update.enforcement_action.toLowerCase()}`}>
                      {update.enforcement_action}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  children,
  style,
}: {
  label: string;
  value?: string | number;
  children?: ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <div style={{ background: 'var(--surface-2)', padding: '12px 14px', borderRadius: 8 }}>
      <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
        {label}
      </div>
      <div style={{ fontSize: 19, fontWeight: 700, marginTop: 4, fontFamily: 'var(--mono)', ...style }}>
        {children ?? value}
      </div>
    </div>
  );
}

function RiskBar({ score }: { score: number }) {
  const color = riskColor(score);
  const pct = Math.min(100, Math.max(0, score));
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span className="mono" style={{ color, fontSize: 19, fontWeight: 700 }}>
        {score.toFixed(1)}
      </span>
      <div style={{ width: 60, height: 6, borderRadius: 3, background: 'var(--border)', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color }} />
      </div>
    </div>
  );
}

function truncate(value: string, limit: number): string {
  return value.length <= limit ? value : `${value.slice(0, limit - 1)}…`;
}
