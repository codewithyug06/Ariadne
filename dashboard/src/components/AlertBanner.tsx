// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAlertStream } from '../hooks/useRunStream';

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
        <div key={key(update.session_id, update.step_index)} className={`alert ${update.enforcement_action}`}>
          <span className={`badge ${update.enforcement_action}`}>{update.enforcement_action}</span>
          <span>
            <span className="mono">{update.tool_name}</span> at step {update.step_index} —{' '}
            {update.reason.length > 120 ? `${update.reason.slice(0, 119)}…` : update.reason}
          </span>
          <span className="spacer" />
          <Link to={`/runs/${encodeURIComponent(update.session_id)}`}>View run</Link>
          <button
            onClick={() =>
              setDismissed((current) =>
                new Set(current).add(key(update.session_id, update.step_index)),
              )
            }
          >
            Dismiss
          </button>
        </div>
      ))}
    </div>
  );
}
