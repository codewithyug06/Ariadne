// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from 'react';
import { STATUS_COLORS, type AuditEvent, type RunStatus } from '../api/client';

interface RunSummaryBarProps {
  events: AuditEvent[];
  finalStatus: string;
  blastRadiusCount: number | null;
}

function StatBox({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ flex: 1, minWidth: 160 }}>
      <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        {label}
      </div>
      <div style={{ marginTop: 4, fontSize: 15 }}>{children}</div>
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
  const rootCause = terminalBlock?.narrative?.trigger ?? null;

  const statusColor = STATUS_COLORS[finalStatus as RunStatus] ?? 'var(--text-dim)';

  return (
    <div className="card">
      <h2>Run summary</h2>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
        <StatBox label="First divergence">
          {firstDivergence !== null ? (
            <span className="mono">step {firstDivergence}</span>
          ) : (
            <span style={{ color: 'var(--text-dim)' }}>None</span>
          )}
        </StatBox>
        <StatBox label="Root cause">
          {rootCause ? rootCause : <span style={{ color: 'var(--text-dim)' }}>None — clean run</span>}
        </StatBox>
        <StatBox label="Blast radius">
          {blastRadiusCount !== null ? (
            `${blastRadiusCount} actions prevented`
          ) : (
            <span style={{ color: 'var(--text-dim)' }}>N/A</span>
          )}
        </StatBox>
        <StatBox label="Decision">
          <span className="badge" style={{ color: statusColor }}>
            {finalStatus}
          </span>
        </StatBox>
      </div>
    </div>
  );
}
