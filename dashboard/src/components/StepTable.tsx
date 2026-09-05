// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { ACTION_COLORS, type AuditEvent } from '../api/client';
import { TerminalIcon } from './Icons';

const RISK_COLORS: Record<'low' | 'medium' | 'high', string> = {
  low: '#10b981',
  medium: '#f59e0b',
  high: '#ef4444',
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
  selectedStepIndex?: number | null;
  onStepSelect: (stepIndex: number) => void;
}

export function StepTable({ events, selectedStepIndex, onStepSelect }: StepTableProps) {
  return (
    <div className="card">
      <div className="card-header">
        <h2>
          <TerminalIcon size={16} />
          <span>Execution Step Trace ({events.length})</span>
        </h2>
        <span style={{ fontSize: 11.5, color: 'var(--text-dim)' }}>
          Click any row to inspect arguments, causal lineage, and 5D risk radar
        </span>
      </div>

      {events.length === 0 ? (
        <div className="empty">No execution steps recorded in this session.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th style={{ width: 60 }}>#</th>
                <th style={{ width: 220 }}>Intercepted Tool</th>
                <th style={{ width: 180 }}>Drift Trajectory</th>
                <th style={{ width: 110 }}>5D Risk</th>
                <th style={{ width: 120 }}>Decision</th>
                <th>Causal Trigger / Policy Reason</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => {
                const isBlock = event.enforcement_action === 'BLOCK';
                const isWarn = event.enforcement_action === 'WARN';
                const isEscalate = event.enforcement_action === 'ESCALATE';
                const isSelected = selectedStepIndex === event.step_index;
                const drift = event.drift_score ?? 0;
                const filled = Math.round(drift / 10);
                const aggregate = event.risk_dimensions?.aggregate;
                const bucket = riskBucket(aggregate);

                let rowClass = 'clickable';
                if (isSelected) rowClass += ' selected';
                if (isBlock) rowClass += ' highlight-block';
                else if (isEscalate || isWarn) rowClass += ' highlight-warn';

                return (
                  <tr
                    key={event.event_id}
                    className={rowClass}
                    onClick={() => onStepSelect(event.step_index)}
                    style={
                      isSelected
                        ? { background: 'var(--surface-3)', outline: '1px solid var(--accent)' }
                        : undefined
                    }
                  >
                    <td>
                      <span
                        className="mono"
                        style={{
                          display: 'inline-block',
                          padding: '2px 6px',
                          background: 'var(--bg)',
                          borderRadius: 4,
                          fontWeight: 600,
                          color: 'var(--text-dim)',
                        }}
                      >
                        {event.step_index}
                      </span>
                    </td>
                    <td>
                      <span className="mono" style={{ fontWeight: 600, color: 'var(--text-bright)' }}>
                        {event.tool_name}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span
                          className="mono"
                          style={{
                            fontSize: 12,
                            fontWeight: 600,
                            minWidth: 32,
                            color: ACTION_COLORS[event.enforcement_action],
                          }}
                          title={event.calibration_note ?? undefined}
                        >
                          {event.drift_score !== null ? event.drift_score.toFixed(1) : '—'}
                        </span>
                        <span style={{ display: 'flex', gap: 2 }}>
                          {Array.from({ length: 10 }, (_, i) => (
                            <span
                              key={i}
                              style={{
                                display: 'inline-block',
                                width: 5,
                                height: 10,
                                borderRadius: 1.5,
                                background:
                                  i < filled
                                    ? ACTION_COLORS[event.enforcement_action]
                                    : 'var(--border)',
                              }}
                            />
                          ))}
                        </span>
                      </div>
                    </td>
                    <td>
                      {event.risk_dimensions ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span
                            title={`Aggregate risk: ${aggregate}`}
                            style={{
                              display: 'inline-block',
                              width: 8,
                              height: 8,
                              borderRadius: '50%',
                              background: RISK_COLORS[bucket],
                              boxShadow: `0 0 6px ${RISK_COLORS[bucket]}`,
                            }}
                          />
                          <span className="mono" style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
                            {aggregate ?? '—'}
                          </span>
                        </div>
                      ) : (
                        <span style={{ color: 'var(--text-dim)' }}>—</span>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${event.enforcement_action}`}>
                        {event.enforcement_action}
                      </span>
                    </td>
                    <td title={event.narrative?.trigger || event.reason || undefined}>
                      <span style={{ color: 'var(--text-muted)' }}>
                        {truncate(event.narrative?.trigger || event.reason, 60)}
                      </span>
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
