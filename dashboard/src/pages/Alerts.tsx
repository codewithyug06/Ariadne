// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import { useAlerts, usePendingApprovals } from '../hooks/useRuns';
import {
  BellIcon,
  CheckIcon,
  RefreshIcon,
  ShieldAlertIcon,
  ShieldCheckIcon,
} from '../components/Icons';

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
      await refreshAlerts();
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

  const pendingList = pending ?? [];
  const alertList = alerts?.items ?? [];

  return (
    <>
      <div className="page-header">
        <div>
          <h1>
            <BellIcon size={22} style={{ color: 'var(--accent)' }} />
            <span>Security Alerts & HITL Approvals</span>
          </h1>
          <span className="subtitle">
            Real-time human intervention queue and ESCALATE/BLOCK incident history
          </span>
        </div>
        <div className="actions">
          <button
            className="secondary"
            onClick={() => {
              void refreshPending();
              void refreshAlerts();
            }}
            title="Refresh alerts"
          >
            <RefreshIcon size={14} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* KPI Stats */}
      <div className="stat-grid">
        <div className="stat-tile escalate">
          <span className="stat-label">Pending HITL Approvals</span>
          <span className="stat-value" style={{ color: pendingList.length > 0 ? 'var(--escalate)' : 'inherit' }}>
            {pendingList.length}
          </span>
          <span className="stat-meta">Awaiting operator decision</span>
        </div>
        <div className="stat-tile block">
          <span className="stat-label">Total Security Alerts</span>
          <span className="stat-value">{alerts?.total ?? 0}</span>
          <span className="stat-meta">Recorded incidents</span>
        </div>
      </div>

      {/* Pending Approvals (HITL Queue) */}
      <div className="card">
        <div className="card-header">
          <h2>
            <ShieldAlertIcon size={16} style={{ color: 'var(--escalate)' }} />
            <span>Pending Human-in-the-Loop Decisions ({pendingList.length})</span>
          </h2>
          <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            Actions held at ESCALATE threshold awaiting human authorization
          </span>
        </div>

        {pendingError && <div className="error">Could not load pending approvals: {String(pendingError)}</div>}
        {actionError && <div className="error" style={{ marginBottom: 12 }}>{actionError}</div>}

        {pendingList.length === 0 ? (
          <div className="empty" style={{ padding: '32px 16px' }}>
            <ShieldCheckIcon size={32} style={{ margin: '0 auto 8px', color: 'var(--allow)' }} />
            <div style={{ color: 'var(--text-bright)', fontWeight: 600 }}>Queue Clear</div>
            <div style={{ color: 'var(--text-dim)', fontSize: 12.5, marginTop: 4 }}>
              No agent actions are waiting on human approval right now.
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {pendingList.map((approval) => (
              <div
                key={approval.approval_id}
                className="card"
                style={{
                  background: 'var(--surface-2)',
                  borderColor: 'var(--escalate-border)',
                  borderLeft: '4px solid var(--escalate)',
                  padding: '14px 18px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span className="badge escalate">ESCALATE</span>
                    <span className="mono" style={{ fontWeight: 700, fontSize: 14, color: 'var(--text-bright)' }}>
                      {approval.tool_name}
                    </span>
                    <span className="mono" style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                      Step {approval.step_index}
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Link to={`/runs/${encodeURIComponent(approval.session_id)}`}>
                      <button className="secondary" style={{ fontSize: 12, padding: '4px 10px' }}>
                        Inspect Run
                      </button>
                    </Link>
                    <button
                      className="success"
                      disabled={busy === approval.approval_id}
                      onClick={() => decide(approval.approval_id, true)}
                    >
                      <CheckIcon size={13} />
                      <span>{busy === approval.approval_id ? 'Authorizing…' : 'Approve Action'}</span>
                    </button>
                    <button
                      className="danger"
                      disabled={busy === approval.approval_id}
                      onClick={() => decide(approval.approval_id, false)}
                    >
                      <span>{busy === approval.approval_id ? 'Denying…' : 'Deny & Block'}</span>
                    </button>
                  </div>
                </div>

                <div style={{ marginTop: 8, fontSize: 13, color: 'var(--text-muted)' }}>
                  <strong>Trigger Reason:</strong> {approval.reason}
                </div>

                {approval.drift_score !== null && (
                  <div className="mono" style={{ marginTop: 4, fontSize: 12, color: 'var(--escalate)' }}>
                    Drift Score: {approval.drift_score.toFixed(1)} / 100
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Alert History */}
      <div className="card">
        <div className="card-header">
          <h2>
            <BellIcon size={16} />
            <span>Incident Audit History</span>
          </h2>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={showAcknowledged}
              onChange={(event) => setShowAcknowledged(event.target.checked)}
            />
            <span>Show acknowledged incidents</span>
          </label>
        </div>

        {isLoading && <div className="empty">Loading alert audit trail…</div>}
        {alertList.length === 0 && !isLoading && (
          <div className="empty">No security alerts recorded.</div>
        )}

        {alertList.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 110 }}>Action</th>
                  <th>Tool Called</th>
                  <th>Incident Summary</th>
                  <th style={{ textAlign: 'right', width: 100 }}>Drift Score</th>
                  <th style={{ width: 150 }}>Session</th>
                  <th style={{ width: 120 }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {alertList.map((alert) => (
                  <tr key={alert.alert_id}>
                    <td>
                      <span className={`badge ${alert.action.toLowerCase()}`}>{alert.action}</span>
                    </td>
                    <td>
                      <span className="mono" style={{ fontWeight: 600, color: 'var(--text-bright)' }}>
                        {alert.tool_name}
                      </span>
                    </td>
                    <td style={{ color: 'var(--text-muted)' }}>{alert.reason}</td>
                    <td style={{ textAlign: 'right' }} className="mono">
                      {alert.drift_score !== null ? alert.drift_score.toFixed(1) : '—'}
                    </td>
                    <td>
                      <Link
                        to={`/runs/${encodeURIComponent(alert.session_id)}`}
                        className="mono"
                        style={{ fontSize: 11.5 }}
                      >
                        {alert.session_id.slice(0, 16)}…
                      </Link>
                    </td>
                    <td>
                      {alert.acknowledged ? (
                        <span style={{ fontSize: 11.5, color: 'var(--text-dim)' }}>Acknowledged</span>
                      ) : (
                        <button
                          className="secondary"
                          onClick={() => acknowledge(alert.alert_id)}
                          style={{ padding: '3px 8px', fontSize: 11 }}
                        >
                          Acknowledge
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
