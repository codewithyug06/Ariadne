// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import type { AuditEvent } from '../api/client';

interface StepDrawerProps {
  event: AuditEvent | null;
  onClose: () => void;
}

const DIMENSION_LABELS: { key: 'intent' | 'tool' | 'privilege' | 'identity' | 'data'; label: string }[] = [
  { key: 'intent', label: 'Intent' },
  { key: 'tool', label: 'Tool' },
  { key: 'privilege', label: 'Privilege' },
  { key: 'identity', label: 'Identity' },
  { key: 'data', label: 'Data' },
];

export function StepDrawer({ event, onClose }: StepDrawerProps) {
  const open = event !== null;
  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        right: 0,
        height: '100vh',
        width: 380,
        maxWidth: '90vw',
        background: 'var(--surface)',
        borderLeft: '1px solid var(--border)',
        boxShadow: '-8px 0 24px rgba(0,0,0,0.35)',
        transform: open ? 'translateX(0)' : 'translateX(100%)',
        transition: 'transform 200ms ease',
        zIndex: 50,
        overflowY: 'auto',
        padding: 16,
      }}
    >
      {event && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <h2 style={{ margin: 0 }}>Step {event.step_index}</h2>
            <button className="linklike" onClick={onClose} aria-label="Close" style={{ fontSize: 20 }}>
              ×
            </button>
          </div>

          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase' }}>Tool</div>
            <div className="mono" style={{ marginTop: 4 }}>
              {event.tool_name}
            </div>
          </div>

          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase' }}>Arguments</div>
            <pre
              style={{
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                padding: 8,
                overflowX: 'auto',
                fontSize: 11,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                marginTop: 4,
              }}
            >
              {JSON.stringify(event.payload, null, 2)}
            </pre>
          </div>

          {event.narrative && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase' }}>Narrative</div>
              <div style={{ marginTop: 4, fontWeight: 600 }}>{event.narrative.summary}</div>
              <div style={{ marginTop: 4, color: 'var(--text-dim)', fontSize: 13 }}>{event.narrative.detail}</div>
            </div>
          )}

          {event.risk_dimensions && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase' }}>
                Risk dimensions
              </div>
              <table style={{ marginTop: 4 }}>
                <thead>
                  <tr>
                    <th>Dimension</th>
                    <th>Value</th>
                    <th>Label</th>
                  </tr>
                </thead>
                <tbody>
                  {DIMENSION_LABELS.map(({ key, label }) => {
                    const dim = event.risk_dimensions![key];
                    return (
                      <tr key={key}>
                        <td>{label}</td>
                        <td className="mono">{dim.value}</td>
                        <td>{dim.label}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
