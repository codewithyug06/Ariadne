// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from 'react';
import type { AuditEvent } from '../api/client';
import { ACTION_COLORS } from '../api/client';
import { CheckIcon, CompassIcon, CopyIcon } from './Icons';

interface StepDrawerProps {
  event: AuditEvent | null;
  onClose: () => void;
}

const DIMENSION_LABELS: { key: 'intent' | 'tool' | 'privilege' | 'identity' | 'data'; label: string; desc: string }[] = [
  { key: 'intent', label: 'Intent Drift', desc: 'Semantic divergence from initial user anchor' },
  { key: 'tool', label: 'Tool Risk', desc: 'Contextual risk of invoked capability' },
  { key: 'privilege', label: 'Privilege Escalation', desc: 'Authority elevation attempt score' },
  { key: 'identity', label: 'Identity Deviation', desc: 'Agent persona consistency metric' },
  { key: 'data', label: 'Data Egress', desc: 'Sensitive data access & egress pattern' },
];

export function StepDrawer({ event, onClose }: StepDrawerProps) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  if (!event) return null;

  const copyPayload = () => {
    navigator.clipboard.writeText(JSON.stringify(event.payload, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const actionColor = ACTION_COLORS[event.enforcement_action] || '#8b98a9';

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <div className="drawer-card">
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span
              className="mono"
              style={{
                fontSize: 14,
                fontWeight: 700,
                background: 'var(--surface-2)',
                padding: '4px 10px',
                borderRadius: 6,
                border: '1px solid var(--border)',
              }}
            >
              Step {event.step_index}
            </span>
            <span className={`badge ${event.enforcement_action.toLowerCase()}`}>
              {event.enforcement_action}
            </span>
          </div>
          <button className="secondary" onClick={onClose} aria-label="Close" style={{ padding: '4px 10px' }}>
            ✕
          </button>
        </div>

        {/* Tool Info */}
        <div className="card" style={{ background: 'var(--surface-2)', padding: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Intercepted Tool
            </div>
            <div className="mono" style={{ fontSize: 11, color: 'var(--text-dim)' }}>
              {event.latency_ms ? `${event.latency_ms.toFixed(1)}ms` : ''}
            </div>
          </div>
          <div className="mono" style={{ marginTop: 4, fontSize: 15, fontWeight: 700, color: 'var(--accent)' }}>
            {event.tool_name}
          </div>
          {event.triggered_rule && (
            <div style={{ marginTop: 6, fontSize: 12, color: 'var(--warn)' }}>
              Triggered Rule: <strong>{event.triggered_rule}</strong>
            </div>
          )}
        </div>

        {/* Drift Metrics */}
        <div className="stat-grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 10, margin: 0 }}>
          <div className="stat-tile" style={{ padding: '10px 12px' }}>
            <span className="stat-label">Drift Score</span>
            <span className="stat-value" style={{ color: actionColor }}>
              {event.drift_score !== null ? event.drift_score.toFixed(1) : '—'}
            </span>
          </div>
          <div className="stat-tile" style={{ padding: '10px 12px' }}>
            <span className="stat-label">Slope Rate</span>
            <span className="stat-value" style={{ fontSize: 16 }}>
              {event.slope !== null ? `${event.slope >= 0 ? '+' : ''}${event.slope.toFixed(2)}/step` : '—'}
            </span>
          </div>
        </div>

        {/* Narrative & Trigger */}
        {event.narrative && (
          <div
            className="card"
            style={{
              borderColor: event.enforcement_action === 'BLOCK' ? 'var(--block-border)' : 'var(--border)',
              background: event.enforcement_action === 'BLOCK' ? 'rgba(239, 68, 68, 0.08)' : 'var(--surface-2)',
            }}
          >
            <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Causal Explanation
            </div>
            <div style={{ marginTop: 6, fontWeight: 600, color: 'var(--text-bright)' }}>
              {event.narrative.summary}
            </div>
            <div style={{ marginTop: 4, color: 'var(--text-muted)', fontSize: 12.5, lineHeight: 1.4 }}>
              {event.narrative.detail}
            </div>
            {event.narrative.trigger && (
              <div style={{ marginTop: 8, fontSize: 12, color: 'var(--accent)' }}>
                <strong>Trigger:</strong> {event.narrative.trigger}
              </div>
            )}
          </div>
        )}

        {/* 5-Dimensional Risk Breakdown */}
        {event.risk_dimensions && (
          <div className="card">
            <div className="card-header" style={{ marginBottom: 10 }}>
              <h2 style={{ margin: 0 }}>
                <CompassIcon size={15} />
                <span>5D Risk Dimensions (Agg: {event.risk_dimensions.aggregate})</span>
              </h2>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {DIMENSION_LABELS.map(({ key, label }) => {
                const dim = event.risk_dimensions![key];
                const val = dim.value;
                const barColor =
                  val >= 66 ? 'var(--block)' : val >= 33 ? 'var(--warn)' : 'var(--allow)';
                return (
                  <div key={key} style={{ background: 'var(--surface-2)', padding: '8px 10px', borderRadius: 6 }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontSize: 12, fontWeight: 600 }}>{label}</span>
                      <span className="mono" style={{ fontSize: 11.5, fontWeight: 700, color: barColor }}>
                        {dim.value} ({dim.label})
                      </span>
                    </div>
                    <div style={{ width: '100%', height: 5, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
                      <div style={{ width: `${Math.min(100, Math.max(0, val))}%`, height: '100%', background: barColor }} />
                    </div>
                    {dim.contributing_factor && (
                      <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
                        {dim.contributing_factor}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Payload Arguments */}
        <div className="card">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Tool Invocation Arguments
            </div>
            <button className="secondary" onClick={copyPayload} style={{ padding: '2px 8px', fontSize: 11 }}>
              {copied ? <CheckIcon size={12} style={{ color: 'var(--allow)' }} /> : <CopyIcon size={12} />}
              <span>{copied ? 'Copied' : 'Copy JSON'}</span>
            </button>
          </div>
          <pre>{JSON.stringify(event.payload, null, 2)}</pre>
        </div>

        {/* Calibration context */}
        {event.calibration_note && (
          <div style={{ fontSize: 11.5, color: 'var(--text-dim)', background: 'var(--surface-2)', padding: '8px 12px', borderRadius: 6 }}>
            <strong>Calibration:</strong> {event.calibration_note}
          </div>
        )}
      </div>
    </>
  );
}
