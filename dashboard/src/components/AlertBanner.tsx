// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAlertStream } from '../hooks/useRunStream';
import { AlertOctagonIcon, ChevronRightIcon } from './Icons';

/** Live strip of ESCALATE/BLOCK events across every active session. */
export function AlertBanner() {
  const { updates } = useAlertStream();
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const key = (sessionId: string, step: number) => `${sessionId}:${step}`;
  const visible = updates
    .filter((update) => !dismissed.has(key(update.session_id, update.step_index)))
    .slice(0, 3);

  if (visible.length === 0) return null;

  return (
    <div className="alert-banner">
      {visible.map((update) => (
        <div key={key(update.session_id, update.step_index)} className={`alert ${update.enforcement_action.toLowerCase()}`}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <AlertOctagonIcon size={16} />
            <span className={`badge ${update.enforcement_action.toLowerCase()}`}>{update.enforcement_action}</span>
          </div>

          <span style={{ fontSize: 13, lineHeight: 1.4 }}>
            <strong className="mono" style={{ color: 'var(--text-bright)' }}>{update.tool_name}</strong> at step {update.step_index} —{' '}
            <span style={{ color: 'inherit', opacity: 0.9 }}>
              {update.reason.length > 120 ? `${update.reason.slice(0, 119)}…` : update.reason}
            </span>
          </span>

          <span className="spacer" />

          <Link to={`/runs/${update.session_id}`}>
            <button className="secondary" style={{ padding: '3px 10px', fontSize: 12, background: 'rgba(0,0,0,0.2)' }}>
              <span>Inspect Run</span>
              <ChevronRightIcon size={13} />
            </button>
          </Link>
          <button
            className="secondary"
            style={{ padding: '3px 8px', fontSize: 12, background: 'transparent' }}
            onClick={() =>
              setDismissed((current) =>
                new Set(current).add(key(update.session_id, update.step_index)),
              )
            }
            title="Dismiss notification"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
