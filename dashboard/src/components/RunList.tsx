// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ActivityIcon,
  CheckIcon,
  CopyIcon,
  RefreshIcon,
  SearchIcon,
  ShieldAlertIcon,
  TerminalIcon,
} from './Icons';
import { useRuns, useSettingsSummary } from '../hooks/useRuns';

const PAGE_SIZE = 25;

export function RunList() {
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const { data, error, isLoading, mutate } = useRuns(PAGE_SIZE, offset);
  const { data: settings } = useSettingsSummary();
  const navigate = useNavigate();

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  // Filter items in real-time by search query and status filter
  const filtered = useMemo(() => {
    return items.filter((run) => {
      const matchesStatus = statusFilter === 'ALL' || run.final_status === statusFilter;
      const query = search.toLowerCase().trim();
      const matchesSearch =
        !query ||
        run.session_id.toLowerCase().includes(query) ||
        (run.intent_summary && run.intent_summary.toLowerCase().includes(query));
      return matchesStatus && matchesSearch;
    });
  }, [items, statusFilter, search]);

  // Aggregate stats from the current set
  const stats = useMemo(() => {
    let clean = 0;
    let warned = 0;
    let escalated = 0;
    let blocked = 0;
    for (const r of items) {
      if (r.final_status === 'CLEAN') clean++;
      else if (r.final_status === 'WARNED') warned++;
      else if (r.final_status === 'ESCALATED') escalated++;
      else if (r.final_status === 'BLOCKED') blocked++;
    }
    return { clean, warned, escalated, blocked };
  }, [items]);

  const copySessionId = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    navigator.clipboard.writeText(id);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  if (error) {
    return (
      <div className="card error">
        <ShieldAlertIcon size={20} />
        <div>Could not load agent runs: {String(error)}</div>
      </div>
    );
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>
            <TerminalIcon size={22} style={{ color: 'var(--accent)' }} />
            <span>Agent Sessions</span>
          </h1>
          <span className="subtitle">
            Causal provenance & trajectory enforcement audit logs
          </span>
        </div>
        <div className="actions">
          <button className="secondary" onClick={() => void mutate()} title="Refresh run list">
            <RefreshIcon size={14} className={isLoading ? 'skeleton' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* KPI Summary Tiles */}
      <div className="stat-grid">
        <div className="stat-tile">
          <span className="stat-label">Total Recorded Runs</span>
          <span className="stat-value">{total}</span>
          <span className="stat-meta">Active session telemetry</span>
        </div>
        <div className="stat-tile block">
          <span className="stat-label">Blocked Threats</span>
          <span className="stat-value" style={{ color: 'var(--block)' }}>{stats.blocked}</span>
          <span className="stat-meta">Zero-compromise intercept</span>
        </div>
        <div className="stat-tile escalate">
          <span className="stat-label">Escalated Approvals</span>
          <span className="stat-value" style={{ color: 'var(--escalate)' }}>{stats.escalated}</span>
          <span className="stat-meta">Human-in-the-loop triggers</span>
        </div>
        <div className="stat-tile allow">
          <span className="stat-label">Clean Executions</span>
          <span className="stat-value" style={{ color: 'var(--allow)' }}>{stats.clean}</span>
          <span className="stat-meta">On-mission trajectories</span>
        </div>
      </div>

      <div className="card">
        {/* Search & Filter Toolbar */}
        <div className="toolbar" style={{ marginBottom: 16 }}>
          <div className="search-input-wrap">
            <SearchIcon size={15} />
            <input
              type="text"
              placeholder="Search session ID or intent…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <div className="filter-tabs">
            {['ALL', 'CLEAN', 'WARNED', 'ESCALATED', 'BLOCKED'].map((st) => (
              <button
                key={st}
                className={`filter-tab ${statusFilter === st ? 'active' : ''}`}
                onClick={() => setStatusFilter(st)}
              >
                {st}
              </button>
            ))}
          </div>

          <span className="spacer" />
          <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            Showing {filtered.length} of {total}
          </span>
        </div>

        {isLoading && items.length === 0 ? (
          <div className="empty">
            <ActivityIcon size={24} style={{ margin: '0 auto 12px', color: 'var(--accent)' }} />
            <div>Loading sessions…</div>
          </div>
        ) : items.length === 0 ? (
          <div className="empty" style={{ padding: '48px 24px' }}>
            <TerminalIcon size={40} style={{ margin: '0 auto 16px', color: 'var(--text-dim)' }} />
            <h3 style={{ fontSize: 16, marginBottom: 8, color: 'var(--text-bright)' }}>No sessions recorded yet</h3>
            <p style={{ maxWidth: 480, margin: '0 auto 20px', color: 'var(--text-muted)', fontSize: 13 }}>
              {settings?.mcp_url ? (
                <>
                  Connect your MCP agent client to <code className="mono">{settings.mcp_url}</code> to start scoring tool trajectories.
                </>
              ) : (
                <>Point your agent orchestrator at Ariadne's MCP proxy to monitor real-time tool calls.</>
              )}
            </p>
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)',
                padding: '8px 14px',
                fontFamily: 'var(--mono)',
                fontSize: 12,
                color: 'var(--accent)',
              }}
            >
              <span>python scripts/demo_agent.py</span>
            </div>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 220 }}>Session ID</th>
                  <th style={{ width: 170 }}>Started At</th>
                  <th>Intent Anchor / Mission</th>
                  <th style={{ textAlign: 'right', width: 90 }}>Steps</th>
                  <th style={{ textAlign: 'right', width: 130 }}>Peak Drift</th>
                  <th style={{ width: 120 }}>Decision</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((run) => (
                  <tr
                    key={run.session_id}
                    className="clickable"
                    onClick={() => navigate(`/runs/${run.session_id}`)}
                  >
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span className="mono" style={{ fontWeight: 600, color: 'var(--text-bright)' }}>
                          {truncate(run.session_id, 22)}
                        </span>
                        <button
                          className="copy-btn"
                          onClick={(e) => copySessionId(e, run.session_id)}
                          title="Copy session ID"
                        >
                          {copiedId === run.session_id ? (
                            <CheckIcon size={12} style={{ color: 'var(--allow)' }} />
                          ) : (
                            <CopyIcon size={12} />
                          )}
                        </button>
                      </div>
                    </td>
                    <td className="mono" style={{ color: 'var(--text-muted)', fontSize: 11.5 }}>
                      {new Date(run.started_at).toLocaleString(undefined, {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                      })}
                    </td>
                    <td style={{ color: run.intent_summary ? 'var(--text)' : 'var(--text-dim)' }}>
                      {truncate(run.intent_summary || 'No intent anchor specified', 54)}
                    </td>
                    <td style={{ textAlign: 'right' }} className="mono">
                      <span
                        style={{
                          background: 'var(--surface-3)',
                          padding: '2px 7px',
                          borderRadius: 4,
                          fontSize: 11.5,
                        }}
                      >
                        {run.total_steps}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <DriftScoreGauge score={run.max_drift_score} />
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

        {total > PAGE_SIZE && (
          <div className="toolbar" style={{ marginTop: 16, marginBottom: 0 }}>
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
              Previous
            </button>
            <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
              Page {Math.floor(offset / PAGE_SIZE) + 1} of {Math.ceil(total / PAGE_SIZE)} ({total} total)
            </span>
            <button
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next
            </button>
          </div>
        )}
      </div>
    </>
  );
}

function DriftScoreGauge({ score }: { score: number }) {
  const pct = Math.min(100, Math.max(0, score));
  const color =
    score >= 85 ? 'var(--block)' : score >= 65 ? 'var(--escalate)' : score >= 40 ? 'var(--warn)' : 'var(--allow)';

  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, justifyContent: 'flex-end' }}>
      <span className="mono" style={{ fontSize: 12, fontWeight: 600, color }}>
        {score.toFixed(1)}
      </span>
      <div
        style={{
          width: 50,
          height: 6,
          background: 'var(--border)',
          borderRadius: 3,
          overflow: 'hidden',
          display: 'inline-block',
        }}
      >
        <div style={{ width: `${pct}%`, height: '100%', background: color }} />
      </div>
    </div>
  );
}

function truncate(value: string, limit: number): string {
  return value.length <= limit ? value : `${value.slice(0, limit - 1)}…`;
}
