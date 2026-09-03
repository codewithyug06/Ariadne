// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRuns } from '../hooks/useRuns';

const PAGE_SIZE = 25;

export function RunList() {
  const [offset, setOffset] = useState(0);
  const { data, error, isLoading } = useRuns(PAGE_SIZE, offset);
  const navigate = useNavigate();

  if (error) {
    return <div className="error">Could not load runs: {String(error)}</div>;
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <>
      <div className="page-header">
        <h1>Agent runs</h1>
        <span className="subtitle">
          {total} recorded {total === 1 ? 'run' : 'runs'}
        </span>
      </div>

      <div className="card">
        {isLoading && items.length === 0 ? (
          <div className="empty">Loading…</div>
        ) : items.length === 0 ? (
          <div className="empty">
            No runs yet. Point an agent at <code className="mono">http://localhost:8000/mcp</code>{' '}
            to record one.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Session</th>
                <th>Started</th>
                <th>Intent</th>
                <th style={{ textAlign: 'right' }}>Steps</th>
                <th style={{ textAlign: 'right' }}>Peak drift</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((run) => (
                <tr
                  key={run.session_id}
                  className="clickable"
                  onClick={() => navigate(`/runs/${encodeURIComponent(run.session_id)}`)}
                >
                  <td className="mono">{truncate(run.session_id, 24)}</td>
                  <td className="mono">{new Date(run.started_at).toLocaleString()}</td>
                  <td style={{ color: '#8b98a9' }}>{truncate(run.intent_summary || '—', 48)}</td>
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

function truncate(value: string, limit: number): string {
  return value.length <= limit ? value : `${value.slice(0, limit - 1)}…`;
}
