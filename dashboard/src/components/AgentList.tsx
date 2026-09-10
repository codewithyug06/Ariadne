// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BotIcon,
  RefreshIcon,
  SearchIcon,
  ShieldAlertIcon,
} from './Icons';
import { api } from '../api/client';
import { useAgents } from '../hooks/useRuns';

const PAGE_SIZE = 25;

type SortKey =
  | 'name'
  | 'risk_score'
  | 'total_runs'
  | 'total_blocked'
  | 'total_escalated'
  | 'avg_drift_score'
  | 'last_seen_at';

type SortDirection = 'asc' | 'desc';

interface ColumnDef {
  key: SortKey;
  label: string;
  align?: 'right';
}

const COLUMNS: ColumnDef[] = [
  { key: 'name', label: 'Agent Persona / Name' },
  { key: 'risk_score', label: 'Risk Score', align: 'right' },
  { key: 'total_runs', label: 'Total Runs', align: 'right' },
  { key: 'total_blocked', label: 'Blocked', align: 'right' },
  { key: 'total_escalated', label: 'Escalated', align: 'right' },
  { key: 'avg_drift_score', label: 'Avg Drift', align: 'right' },
  { key: 'last_seen_at', label: 'Last Active' },
];

export function AgentList() {
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState('');
  const [riskFilter, setRiskFilter] = useState<'ALL' | 'HIGH' | 'ELEVATED' | 'LOW'>('ALL');
  const [sortKey, setSortKey] = useState<SortKey>('risk_score');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const { data, error, isLoading, mutate } = useAgents(PAGE_SIZE, offset);
  const navigate = useNavigate();

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  const filtered = useMemo(() => {
    return items.filter((agent) => {
      const matchesSearch =
        !search ||
        agent.name.toLowerCase().includes(search.toLowerCase()) ||
        agent.agent_identity.toLowerCase().includes(search.toLowerCase());
      const matchesRisk =
        riskFilter === 'ALL' ||
        (riskFilter === 'HIGH' && agent.risk_score >= 60) ||
        (riskFilter === 'ELEVATED' && agent.risk_score >= 30 && agent.risk_score < 60) ||
        (riskFilter === 'LOW' && agent.risk_score < 30);
      return matchesSearch && matchesRisk;
    });
  }, [items, search, riskFilter]);

  const sorted = useMemo(() => {
    const copy = [...filtered];
    copy.sort((a, b) => {
      const dir = sortDirection === 'asc' ? 1 : -1;
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === 'string' && typeof bv === 'string') {
        return av.localeCompare(bv) * dir;
      }
      return ((av as number) - (bv as number)) * dir;
    });
    return copy;
  }, [filtered, sortKey, sortDirection]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDirection((current) => (current === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDirection('desc');
    }
  }

  async function handleDelete(e: React.MouseEvent, agentId: string) {
    e.stopPropagation();
    if (!window.confirm('Delete this agent and all its run history?')) return;
    setDeletingId(agentId);
    try {
      await api.agents.delete(agentId);
      await mutate();
    } finally {
      setDeletingId(null);
    }
  }

  if (error) {
    return (
      <div className="card error">
        <ShieldAlertIcon size={20} />
        <div>Could not load agent fleet: {String(error)}</div>
      </div>
    );
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>
            <BotIcon size={22} style={{ color: 'var(--accent)' }} />
            <span>Agent Fleet Registry</span>
          </h1>
          <span className="subtitle">
            Autonomous agent identity profiles, behavioral drift scores, and security postures
          </span>
        </div>
        <div className="actions">
          <button className="secondary" onClick={() => void mutate()} title="Refresh agent registry">
            <RefreshIcon size={14} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* KPI Tiles */}
      <div className="stat-grid">
        <div className="stat-tile">
          <span className="stat-label">Total Agents</span>
          <span className="stat-value">{total}</span>
          <span className="stat-meta">Registered personas</span>
        </div>
        <div className="stat-tile block">
          <span className="stat-label">High Risk Agents</span>
          <span className="stat-value" style={{ color: 'var(--block)' }}>
            {items.filter((a) => a.risk_score >= 60).length}
          </span>
          <span className="stat-meta">Risk score &ge; 60</span>
        </div>
        <div className="stat-tile warn">
          <span className="stat-label">Elevated Drift</span>
          <span className="stat-value" style={{ color: 'var(--warn)' }}>
            {items.filter((a) => a.risk_score >= 30 && a.risk_score < 60).length}
          </span>
          <span className="stat-meta">Moderate variance</span>
        </div>
        <div className="stat-tile allow">
          <span className="stat-label">Trusted Baseline</span>
          <span className="stat-value" style={{ color: 'var(--allow)' }}>
            {items.filter((a) => a.risk_score < 30).length}
          </span>
          <span className="stat-meta">Nominal telemetry</span>
        </div>
      </div>

      <div className="card">
        {/* Search & Filter Toolbar */}
        <div className="toolbar" style={{ marginBottom: 16 }}>
          <div className="search-input-wrap">
            <SearchIcon size={15} />
            <input
              type="text"
              placeholder="Search agent name or identity…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <div className="filter-tabs">
            {(['ALL', 'HIGH', 'ELEVATED', 'LOW'] as const).map((lvl) => (
              <button
                key={lvl}
                className={`filter-tab ${riskFilter === lvl ? 'active' : ''}`}
                onClick={() => setRiskFilter(lvl)}
              >
                {lvl === 'ALL' ? 'All Agents' : lvl === 'HIGH' ? 'High Risk' : lvl === 'ELEVATED' ? 'Elevated' : 'Low Risk'}
              </button>
            ))}
          </div>

          <span className="spacer" />
          <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            Showing {sorted.length} of {total}
          </span>
        </div>

        {isLoading && items.length === 0 ? (
          <div className="empty">Loading registered agents…</div>
        ) : items.length === 0 ? (
          <div className="empty" style={{ padding: '48px 24px' }}>
            <BotIcon size={40} style={{ margin: '0 auto 16px', color: 'var(--text-dim)' }} />
            <h3 style={{ fontSize: 16, marginBottom: 8, color: 'var(--text-bright)' }}>No agents recorded yet</h3>
            <p style={{ maxWidth: 460, margin: '0 auto', color: 'var(--text-muted)', fontSize: 13 }}>
              When agents make tool calls through the Ariadne proxy, their identities and behavioral fingerprints are automatically cataloged here.
            </p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {COLUMNS.map((col) => (
                    <th
                      key={col.key}
                      className="clickable"
                      style={{ textAlign: col.align, cursor: 'pointer' }}
                      onClick={() => toggleSort(col.key)}
                    >
                      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                        <span>{col.label}</span>
                        {sortKey === col.key && (
                          <span style={{ color: 'var(--accent)', fontWeight: 700 }}>
                            {sortDirection === 'asc' ? '↑' : '↓'}
                          </span>
                        )}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((agent) => (
                  <tr
                    key={agent.id}
                    className="clickable"
                    onClick={() => navigate(`/agents/${agent.id}`)}
                  >
                    <td>
                      <div>
                        <div style={{ fontWeight: 600, color: 'var(--text-bright)' }}>{agent.name}</div>
                        <div className="mono" style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>
                          {agent.agent_identity}
                        </div>
                      </div>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <RiskBadge score={agent.risk_score} />
                    </td>
                    <td style={{ textAlign: 'right' }} className="mono">
                      <span style={{ background: 'var(--surface-3)', padding: '2px 7px', borderRadius: 4 }}>
                        {agent.total_runs}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }} className="mono">
                      <span style={{ color: agent.total_blocked > 0 ? 'var(--block)' : 'var(--text-dim)' }}>
                        {agent.total_blocked}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }} className="mono">
                      <span style={{ color: agent.total_escalated > 0 ? 'var(--escalate)' : 'var(--text-dim)' }}>
                        {agent.total_escalated}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }} className="mono">
                      {agent.avg_drift_score.toFixed(1)}
                    </td>
                    <td className="mono" style={{ color: 'var(--text-muted)', fontSize: 11.5 }}>
                      {formatRelativeTime(agent.last_seen_at)}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        className="secondary"
                        disabled={deletingId === agent.id}
                        onClick={(e) => void handleDelete(e, agent.id)}
                        style={{ padding: '2px 8px', fontSize: 11, color: 'var(--block)' }}
                        title="Delete agent"
                      >
                        {deletingId === agent.id ? '…' : 'Delete'}
                      </button>
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

export function riskColor(score: number): string {
  if (score < 30) return '#10b981';
  if (score < 60) return '#f59e0b';
  if (score < 80) return '#f97316';
  return '#ef4444';
}

export function RiskBadge({ score }: { score: number }) {
  const color = riskColor(score);
  const filled = Math.round(Math.min(100, Math.max(0, score)) / 10);
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, justifyContent: 'flex-end' }}>
      <span className="mono" style={{ fontSize: 12, fontWeight: 700, color }}>
        {score.toFixed(1)}
      </span>
      <span style={{ display: 'flex', gap: 2 }}>
        {Array.from({ length: 10 }, (_, i) => (
          <span
            key={i}
            style={{
              display: 'inline-block',
              width: 4,
              height: 10,
              borderRadius: 1,
              background: i < filled ? color : 'var(--border)',
            }}
          />
        ))}
      </span>
    </div>
  );
}

export function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const diffMs = Date.now() - then;
  if (diffMs < 0) return 'just now';

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  const years = Math.floor(months / 12);
  return `${years}y ago`;
}
