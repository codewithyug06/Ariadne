// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
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
  { key: 'name', label: 'Agent name' },
  { key: 'risk_score', label: 'Risk score', align: 'right' },
  { key: 'total_runs', label: 'Total runs', align: 'right' },
  { key: 'total_blocked', label: 'Blocked', align: 'right' },
  { key: 'total_escalated', label: 'Escalated', align: 'right' },
  { key: 'avg_drift_score', label: 'Avg drift', align: 'right' },
  { key: 'last_seen_at', label: 'Last seen' },
];

export function AgentList() {
  const [offset, setOffset] = useState(0);
  const [sortKey, setSortKey] = useState<SortKey>('risk_score');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const { data, error, isLoading } = useAgents(PAGE_SIZE, offset);
  const navigate = useNavigate();

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  const sorted = useMemo(() => {
    const copy = [...items];
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
  }, [items, sortKey, sortDirection]);

  if (error) {
    return <div className="error">Could not load agents: {String(error)}</div>;
  }

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDirection((current) => (current === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDirection('desc');
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>Agents</h1>
        <span className="subtitle">
          {total} registered {total === 1 ? 'agent' : 'agents'}
        </span>
      </div>

      <div className="card">
        {isLoading && items.length === 0 ? (
          <div className="empty">Loading…</div>
        ) : items.length === 0 ? (
          <div className="empty">No agents registered yet.</div>
        ) : (
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
                    {col.label}
                    {sortKey === col.key ? (sortDirection === 'asc' ? ' ↑' : ' ↓') : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((agent) => (
                <tr key={agent.id}>
                  <td>
                    <span
                      className="linklike-nav"
                      style={{ cursor: 'pointer' }}
                      onClick={() => navigate(`/agents/${encodeURIComponent(agent.id)}`)}
                    >
                      {agent.name}
                    </span>
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <RiskBadge score={agent.risk_score} />
                  </td>
                  <td style={{ textAlign: 'right' }} className="mono">
                    {agent.total_runs}
                  </td>
                  <td style={{ textAlign: 'right' }} className="mono">
                    {agent.total_blocked}
                  </td>
                  <td style={{ textAlign: 'right' }} className="mono">
                    {agent.total_escalated}
                  </td>
                  <td style={{ textAlign: 'right' }} className="mono">
                    {agent.avg_drift_score.toFixed(1)}
                  </td>
                  <td className="mono">{formatRelativeTime(agent.last_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {total > PAGE_SIZE && (
          <div className="toolbar" style={{ marginTop: 12, marginBottom: 0 }}>
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
              Previous
            </button>
            <span style={{ fontSize: 12, color: '#8b98a9' }}>
              {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
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

/** green <30, yellow 30-60, orange 60-80, red >80 */
export function riskColor(score: number): string {
  if (score < 30) return '#3fb950';
  if (score < 60) return '#d29922';
  if (score < 80) return '#db6d28';
  return '#f85149';
}

export function RiskBadge({ score }: { score: number }) {
  const color = riskColor(score);
  const filled = Math.round(Math.min(100, Math.max(0, score)) / 10);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'flex-end' }}>
      <span className="mono" style={{ fontSize: 12, color }}>
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

/** Small local relative-time formatter — no date library dependency. */
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
