// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState } from 'react';
import { api, ApiError } from '../api/client';
import { useAlerts, usePendingApprovals } from '../hooks/useRuns';

export function Alerts() {
  const [showAcknowledged, setShowAcknowledged] = useState(false);
  const {
    data: pending,
    mutate: refreshPending,
    error: pendingError,
  } = usePendingApprovals();
  const {
    data: alerts,
    mutate: refreshAlerts,
    isLoading,
  } = useAlerts({ acknowledged: showAcknowledged ? undefined : false });
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const decide = async (approvalId: string, approved: boolean) => {
    setBusy(approvalId);
    setActionError(null);
    try {
      await api.resolveApproval(approvalId, approved);
      await refreshPending();
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Could not resolve approval.');
    } finally {
      setBusy(null);
    }
  };

  const acknowledge = async (alertId: string) => {
    await api.acknowledgeAlert(alertId);
    await refreshAlerts();
  };

  return (
    <>
      <div className="page-header">
        <h1>Alerts</h1>
        <span className="subtitle">ESCALATE/BLOCK history and pending human decisions</span>
      </div>

      <div className="card">
        <h2>Pending approvals</h2>
        {pendingError && <div className="error">Could not load pending approvals.</div>}
        {actionError && <div className="error">{actionError}</div>}
        {pending && pending.length === 0 && (
          <div className="empty">Nothing is waiting on a human right now.</div>
        )}
        {pending?.map((approval) => (
          <div key={approval.approval_id} className="event ESCALATE">
            <span className="step">step {approval.step_index}</span>
            <span className="tool">{approval.tool_name}</span>
            <span className="reason">{approval.reason}</span>
            {approval.drift_score !== null && (
              <span className="score">{approval.drift_score.toFixed(1)}</span>
            )}
            <button disabled={busy === approval.approval_id} onClick={() => decide(approval.approval_id, true)}>
              Approve
            </button>
            <button disabled={busy === approval.approval_id} onClick={() => decide(approval.approval_id, false)}>
              Deny
            </button>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="toolbar">
          <h2>Alert history</h2>
          <span className="spacer" />
          <label className="checkbox">
            <input
              type="checkbox"
              checked={showAcknowledged}
              onChange={(event) => setShowAcknowledged(event.target.checked)}
            />
            Show acknowledged
          </label>
        </div>
        {isLoading && <div className="empty">Loading…</div>}
        {alerts && alerts.items.length === 0 && <div className="empty">No alerts.</div>}
        {alerts?.items.map((alert) => (
          <div key={alert.alert_id} className={`event ${alert.action}`}>
            <span className={`badge ${alert.action}`}>{alert.action}</span>
            <span className="tool">{alert.tool_name}</span>
            <span className="reason">{alert.reason}</span>
            {alert.drift_score !== null && <span className="score">{alert.drift_score.toFixed(1)}</span>}
            {!alert.acknowledged && <button onClick={() => acknowledge(alert.alert_id)}>Acknowledge</button>}
          </div>
        ))}
      </div>
    </>
  );
}
