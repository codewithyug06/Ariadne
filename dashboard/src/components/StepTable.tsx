// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { ACTION_COLORS, type AuditEvent } from '../api/client';

const RISK_COLORS: Record<'low' | 'medium' | 'high', string> = {
  low: '#3fb950',
  medium: '#d29922',
  high: '#f85149',
};

function riskBucket(aggregate: number | undefined): 'low' | 'medium' | 'high' {
  if (aggregate === undefined) return 'low';
  if (aggregate >= 66) return 'high';
  if (aggregate >= 33) return 'medium';
  return 'low';
}

function truncate(text: string | undefined | null, length: number): string {
  if (!text) return '—';
  return text.length > length ? `${text.slice(0, length)}…` : text;
}

interface StepTableProps {
  events: AuditEvent[];
  onStepSelect: (stepIndex: number) => void;
}

export function StepTable({ events, onStepSelect }: StepTableProps) {
  return (
    <div className="card">
      <h2>Step table</h2>
      {events.length === 0 ? (
        <div className="empty">No steps recorded.</div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Tool called</th>
                <th>Drift score</th>
                <th>Risk</th>
                <th>Decision</th>
                <th>Trigger</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => {
                const isBlock = event.enforcement_action === 'BLOCK';
                const drift = event.drift_score ?? 0;
                const filled = Math.round(drift / 10);
                const aggregate = event.risk_dimensions?.aggregate;
                const bucket = riskBucket(aggregate);
                return (
                  <tr
                    key={event.event_id}
                    className="clickable"
                    onClick={() => onStepSelect(event.step_index)}
                    style={
                      isBlock
                        ? { borderTop: '2px solid #ef4444', background: '#fef2f2' }
                        : undefined
                    }
                  >
                    <td className="mono">{event.step_index}</td>
                    <td className="mono">{event.tool_name}</td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span className="mono" style={{ fontSize: 12 }}>
                          {event.drift_score !== null ? event.drift_score.toFixed(1) : '—'}
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
                                background: i < filled ? ACTION_COLORS[event.enforcement_action] : 'var(--border)',
                              }}
                            />
                          ))}
                        </span>
                      </div>
                    </td>
                    <td>
                      {event.risk_dimensions ? (
                        <span
                          title={`aggregate ${aggregate}`}
                          style={{
                            display: 'inline-block',
                            width: 10,
                            height: 10,
                            borderRadius: '50%',
                            background: RISK_COLORS[bucket],
                          }}
                        />
                      ) : (
                        <span style={{ color: 'var(--text-dim)' }}>—</span>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${event.enforcement_action}`}>
                        {event.enforcement_action}
                      </span>
                    </td>
                    <td title={event.narrative?.trigger ?? undefined}>
                      {truncate(event.narrative?.trigger, 40)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
