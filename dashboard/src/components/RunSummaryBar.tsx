// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from 'react';
import { STATUS_COLORS, type AuditEvent, type RunStatus } from '../api/client';
import { CrosshairIcon, ShieldAlertIcon, ShieldCheckIcon, SparklesIcon } from './Icons';

interface RunSummaryBarProps {
  events: AuditEvent[];
  finalStatus: string;
  blastRadiusCount: number | null;
}

function StatBox({ label, icon, children }: { label: string; icon: ReactNode; children: ReactNode }) {
  return (
    <div style={{ flex: 1, minWidth: 170, background: 'var(--surface-2)', padding: '12px 16px', borderRadius: 'var(--radius)', border: '1px solid var(--border-subtle)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
        {icon}
        <span>{label}</span>
      </div>
      <div style={{ marginTop: 6, fontSize: 14, fontWeight: 600, color: 'var(--text-bright)' }}>{children}</div>
    </div>
  );
}

export function RunSummaryBar({ events, finalStatus, blastRadiusCount }: RunSummaryBarProps) {
  const firstDivergenceEvent = events.find(
    (event) => event.narrative?.first_divergence_step !== null && event.narrative?.first_divergence_step !== undefined,
  );
  const firstDivergence = firstDivergenceEvent?.narrative?.first_divergence_step ?? null;

  const blockEvents = events.filter((event) => event.enforcement_action === 'BLOCK');
  const terminalBlock = blockEvents.length > 0 ? blockEvents[blockEvents.length - 1] : null;
  const rootCause = terminalBlock?.narrative?.trigger || terminalBlock?.reason || null;

  const statusColor = STATUS_COLORS[finalStatus as RunStatus] ?? 'var(--text-dim)';

  return (
    <div className="card">
      <div className="card-header">
        <h2>
          <ShieldCheckIcon size={16} />
          <span>Security & Provenance Executive Summary</span>
        </h2>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
        <StatBox label="First Divergence" icon={<CrosshairIcon size={14} style={{ color: 'var(--warn)' }} />}>
          {firstDivergence !== null ? (
            <span className="mono" style={{ color: 'var(--warn)' }}>
              Step {firstDivergence}
            </span>
          ) : (
            <span style={{ color: 'var(--allow)', fontWeight: 500 }}>No divergence (clean)</span>
          )}
        </StatBox>
        <StatBox label="Root Cause Analysis" icon={<ShieldAlertIcon size={14} style={{ color: rootCause ? 'var(--block)' : 'var(--allow)' }} />}>
          {rootCause ? (
            <span style={{ color: 'var(--block)', fontSize: 13 }}>{rootCause}</span>
          ) : (
            <span style={{ color: 'var(--allow)', fontWeight: 500 }}>None — on-mission</span>
          )}
        </StatBox>
        <StatBox label="Blast Radius Prevented" icon={<SparklesIcon size={14} style={{ color: 'var(--accent)' }} />}>
          {blastRadiusCount !== null ? (
            <span style={{ color: 'var(--accent)' }}>{blastRadiusCount} actions prevented</span>
          ) : (
            <span style={{ color: 'var(--text-dim)' }}>0 uncontained leaks</span>
          )}
        </StatBox>
        <StatBox label="Session Verdict" icon={<ShieldCheckIcon size={14} style={{ color: statusColor }} />}>
          <span className={`badge ${finalStatus.toLowerCase()}`} style={{ fontSize: 12 }}>
            {finalStatus}
          </span>
        </StatBox>
      </div>
    </div>
  );
}
