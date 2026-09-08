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

const FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: 'ALL', label: 'All' },
  { value: 'CLEAN', label: 'Completed Safely' },
  { value: 'WARNED', label: 'Had a Warning' },
  { value: 'ESCALATED', label: 'Needed Approval' },
  { value: 'BLOCKED', label: 'Stopped' },
];

const OUTCOME_LABEL: Record<string, string> = {
  CLEAN: 'Completed Safely',
  WARNED: 'Had a Warning',
  ESCALATED: 'Needed Approval',
  BLOCKED: 'Stopped',
};

const OUTCOME_EXPLAINER: Record<string, string> = {
  CLEAN: 'The agent finished its task without doing anything concerning.',
  WARNED: 'The agent drifted a little from its task, but nothing was blocked.',
  ESCALATED: 'The agent tried something that needed a person to approve first.',
  BLOCKED: 'Ariadne stopped the agent before it could do something harmful.',
};

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

  // Ariadne's real MCP endpoint. Only resolves once the deployment sets
  // ARIADNE_PUBLIC_URL -- deliberately not guessed from window.location or a
  // hardcoded port, since the actual host/port Ariadne is reachable at in a
  // real deployment (behind a proxy, a different port, HTTPS, etc.) cannot
  // be inferred from the browser tab. When unset, the UI prompts the admin
  // to configure it rather than showing a possibly-wrong address.
  const mcpConnectUrl = settings?.mcp_url ?? null;

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
            <span>Agent Activity</span>
          </h1>
          <span className="subtitle">
            Every task your AI agents have run, and what Ariadne did to keep them safe
          </span>
        </div>
        <div className="actions">
          <button className="secondary" onClick={() => void mutate()} title="Check for new activity">
            <RefreshIcon size={14} className={isLoading ? 'skeleton' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      <div
        className="card"
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: 10,
          padding: '14px 16px',
          marginBottom: 16,
          background: 'var(--surface-2)',
          fontSize: 13,
          color: 'var(--text-muted)',
        }}
      >
        <ShieldAlertIcon size={16} style={{ color: 'var(--accent)', flexShrink: 0, marginTop: 1 }} />
        <span>
          <strong style={{ color: 'var(--text)' }}>How this works:</strong> each row below is one
          task an AI agent carried out. Ariadne watches every step the agent takes and steps in if
          it starts drifting away from what it was asked to do — warning, pausing for a human, or
          blocking it outright before anything happens for real.
        </span>
      </div>

      {/* KPI Summary Tiles */}
      <div className="stat-grid">
        <div className="stat-tile" title="Every agent task Ariadne has watched so far">
          <span className="stat-label">Total Tasks Watched</span>
          <span className="stat-value">{total}</span>
          <span className="stat-meta">All agent activity recorded</span>
        </div>
        <div
          className="stat-tile block"
          title="Ariadne stopped these actions before the agent could carry them out"
        >
          <span className="stat-label">Stopped Automatically</span>
          <span className="stat-value" style={{ color: 'var(--block)' }}>{stats.blocked}</span>
          <span className="stat-meta">Prevented before any harm was done</span>
        </div>
        <div
          className="stat-tile escalate"
          title="These tasks were paused so a person could approve or deny them"
        >
          <span className="stat-label">Sent for Human Approval</span>
          <span className="stat-value" style={{ color: 'var(--escalate)' }}>{stats.escalated}</span>
          <span className="stat-meta">Needed a person to say yes or no</span>
        </div>
        <div className="stat-tile allow" title="These tasks finished normally, with no concerns raised">
          <span className="stat-label">Completed Safely</span>
          <span className="stat-value" style={{ color: 'var(--allow)' }}>{stats.clean}</span>
          <span className="stat-meta">Stayed on task the whole time</span>
        </div>
      </div>

      <div className="card">
        {/* Search & Filter Toolbar */}
        <div className="toolbar" style={{ marginBottom: 16 }}>
          <div className="search-input-wrap">
            <SearchIcon size={15} />
            <input
              type="text"
              placeholder="Search by ID or what the agent was asked to do…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <div className="filter-tabs">
            {FILTER_OPTIONS.map(({ value, label }) => (
              <button
                key={value}
                className={`filter-tab ${statusFilter === value ? 'active' : ''}`}
                onClick={() => setStatusFilter(value)}
              >
                {label}
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
            <h3 style={{ fontSize: 16, marginBottom: 8, color: 'var(--text-bright)' }}>
              Nothing to show yet
            </h3>
            <p style={{ maxWidth: 520, margin: '0 auto 16px', color: 'var(--text-muted)', fontSize: 13 }}>
              As soon as an AI agent starts using Ariadne, its activity will show up here
              automatically. To connect one, point its MCP client — running from your own AI
              automation project's folder — at the address below.
            </p>
            <McpConnectionBox url={mcpConnectUrl} />
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 220 }}>Task ID</th>
                  <th style={{ width: 170 }}>Started</th>
                  <th>What the Agent Was Asked to Do</th>
                  <th style={{ textAlign: 'right', width: 90 }}>Steps Taken</th>
                  <th style={{ textAlign: 'right', width: 150 }} title="How far the agent strayed from its task — higher means more suspicious">
                    How Risky It Got
                  </th>
                  <th style={{ width: 150 }}>Outcome</th>
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
                      {truncate(run.intent_summary || 'Not recorded for this task', 54)}
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
                      <span
                        className={`badge ${run.final_status.toLowerCase()}`}
                        title={OUTCOME_EXPLAINER[run.final_status] ?? run.final_status}
                      >
                        {OUTCOME_LABEL[run.final_status] ?? run.final_status}
                      </span>
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
    <div
      style={{ display: 'inline-flex', alignItems: 'center', gap: 8, justifyContent: 'flex-end' }}
      title="How far this agent drifted from its original task, on a scale of 0–100"
    >
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

function McpConnectionBox({ url }: { url: string | null }) {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    if (!url) return;
    navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      style={{
        display: 'inline-flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        gap: 4,
        background: 'var(--bg)',
        border: `1px solid ${url ? 'var(--border)' : 'var(--warn)'}`,
        borderRadius: 'var(--radius-sm)',
        padding: '12px 16px',
        maxWidth: '100%',
      }}
    >
      <span style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.4 }}>
        Ariadne MCP connection address
      </span>
      {url ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <code
            className="mono"
            style={{ fontSize: 13, color: 'var(--accent)', wordBreak: 'break-all', textAlign: 'left' }}
          >
            {url}
          </code>
          <button className="copy-btn" onClick={copy} title="Copy connection address">
            {copied ? (
              <CheckIcon size={13} style={{ color: 'var(--allow)' }} />
            ) : (
              <CopyIcon size={13} />
            )}
          </button>
        </div>
      ) : (
        <span style={{ fontSize: 13, color: 'var(--warn)' }}>
          Not configured yet — set <code className="mono">ARIADNE_PUBLIC_URL</code> in this
          deployment's environment so the correct address can be shown here.
        </span>
      )}
      <span style={{ fontSize: 11.5, color: 'var(--text-dim)', marginTop: 4, textAlign: 'left' }}>
        In your AI automation's own project folder, set this as the MCP server address it
        connects to (for example, an n8n <em>MCP Client Tool</em> node's endpoint URL, or the
        MCP client config of a script you run yourself) — and send your Ariadne API key as the{' '}
        <code className="mono">X-Api-Key</code> header on that connection.
      </span>
    </div>
  );
}
