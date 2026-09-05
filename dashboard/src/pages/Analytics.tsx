// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useMemo } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useAnalytics } from '../hooks/useRuns';
import {
  ActivityIcon,
  BarChartIcon,
  CompassIcon,
  LockIcon,
  ShieldAlertIcon,
  ShieldCheckIcon,
} from '../components/Icons';

export function Analytics() {
  const { data, isLoading, error } = useAnalytics();

  const summary = useMemo(() => {
    if (!data) return null;
    let totalRuns = 0;
    let totalAllowed = 0;
    let totalWarned = 0;
    let totalEscalated = 0;
    let totalBlocked = 0;

    for (const d of data.daily_volume) {
      totalRuns += d.allowed + d.warned + d.escalated + d.blocked;
      totalAllowed += d.allowed;
      totalWarned += d.warned;
      totalEscalated += d.escalated;
      totalBlocked += d.blocked;
    }

    const blockRate = totalRuns > 0 ? ((totalBlocked / totalRuns) * 100).toFixed(1) : '0.0';
    const escalateRate = totalRuns > 0 ? ((totalEscalated / totalRuns) * 100).toFixed(1) : '0.0';

    return { totalRuns, totalAllowed, totalWarned, totalEscalated, totalBlocked, blockRate, escalateRate };
  }, [data]);

  return (
    <>
      <div className="page-header">
        <div>
          <h1>
            <BarChartIcon size={22} style={{ color: 'var(--accent)' }} />
            <span>Telemetry & Threat Analytics</span>
          </h1>
          <span className="subtitle">
            Cumulative enforcement patterns, volume distribution, and drift telemetry over the last 30 days
          </span>
        </div>
      </div>

      {error && (
        <div className="card error">
          <ShieldAlertIcon size={20} />
          <div>Could not load analytics: {String(error)}</div>
        </div>
      )}
      {isLoading && (
        <div className="empty">
          <ActivityIcon size={32} style={{ margin: '0 auto 12px', color: 'var(--accent)' }} />
          <div>Aggregating security telemetry…</div>
        </div>
      )}

      {data && summary && (
        <>
          {/* Executive KPI Summary Tiles */}
          <div className="stat-grid">
            <div className="stat-tile">
              <span className="stat-label">30-Day Session Volume</span>
              <span className="stat-value">{summary.totalRuns}</span>
              <span className="stat-meta">Total intercepted runs</span>
            </div>
            <div className="stat-tile block">
              <span className="stat-label">Threat Intercept Rate</span>
              <span className="stat-value" style={{ color: 'var(--block)' }}>{summary.blockRate}%</span>
              <span className="stat-meta">{summary.totalBlocked} blocked runs</span>
            </div>
            <div className="stat-tile escalate">
              <span className="stat-label">HITL Escalation Rate</span>
              <span className="stat-value" style={{ color: 'var(--escalate)' }}>{summary.escalateRate}%</span>
              <span className="stat-meta">{summary.totalEscalated} held for review</span>
            </div>
            <div className="stat-tile allow">
              <span className="stat-label">Clean Pass-Through</span>
              <span className="stat-value" style={{ color: 'var(--allow)' }}>{summary.totalAllowed}</span>
              <span className="stat-meta">Zero-drift execution</span>
            </div>
          </div>

          {/* Daily Run Volume Stacked Bar Chart */}
          <div className="card">
            <div className="card-header">
              <h2>
                <BarChartIcon size={16} />
                <span>Daily Run Volume & Security Verdicts</span>
              </h2>
            </div>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={data.daily_volume} margin={{ top: 12, right: 20, bottom: 8, left: -16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" stroke="#94a3b8" fontSize={11} tickLine={false} />
                <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} />
                <Tooltip
                  contentStyle={{
                    background: '#ffffff',
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    boxShadow: 'var(--shadow-lg)',
                    color: 'var(--text-bright)',
                    fontSize: 12,
                  }}
                />
                <Legend
                  wrapperStyle={{ fontSize: 12, paddingTop: 10 }}
                  iconType="circle"
                />
                <Bar dataKey="allowed" stackId="a" fill="#10b981" name="Clean / Allowed" radius={[0, 0, 0, 0]} />
                <Bar dataKey="warned" stackId="a" fill="#f59e0b" name="Warned" radius={[0, 0, 0, 0]} />
                <Bar dataKey="escalated" stackId="a" fill="#f97316" name="Escalated" radius={[0, 0, 0, 0]} />
                <Bar dataKey="blocked" stackId="a" fill="#ef4444" name="Blocked Threat" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="split" style={{ marginTop: 16 }}>
            {/* Decisions by Action */}
            <div className="card">
              <div className="card-header">
                <h2>
                  <ShieldCheckIcon size={16} />
                  <span>Decisions by Action Breakdown</span>
                </h2>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {Object.entries(data.decisions_by_action).map(([action, count]) => {
                  const totalDecisions = Object.values(data.decisions_by_action).reduce((a, b) => a + b, 0);
                  const pct = totalDecisions > 0 ? Math.round((count / totalDecisions) * 100) : 0;
                  const color =
                    action === 'ALLOW' ? 'var(--allow)' : action === 'WARN' ? 'var(--warn)' : action === 'ESCALATE' ? 'var(--escalate)' : 'var(--block)';
                  return (
                    <div key={action} style={{ background: 'var(--surface-2)', padding: '10px 14px', borderRadius: 8 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                        <span className={`badge ${action.toLowerCase()}`}>{action}</span>
                        <span className="mono" style={{ fontSize: 13, fontWeight: 700 }}>
                          {count} ({pct}%)
                        </span>
                      </div>
                      <div style={{ width: '100%', height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
                        <div style={{ width: `${pct}%`, height: '100%', background: color }} />
                      </div>
                    </div>
                  );
                })}
                {Object.keys(data.decisions_by_action).length === 0 && (
                  <div className="empty">No tool actions recorded in this window.</div>
                )}
              </div>
            </div>

            {/* Top Triggered Hard Policy Rules */}
            <div className="card">
              <div className="card-header">
                <h2>
                  <LockIcon size={16} />
                  <span>Top Triggered Policy Rules</span>
                </h2>
              </div>
              {data.top_triggered_rules.length === 0 && (
                <div className="empty">No hard rules triggered in this window.</div>
              )}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {data.top_triggered_rules.map((rule, idx) => (
                  <div
                    key={rule.rule}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      background: 'var(--surface-2)',
                      padding: '10px 14px',
                      borderRadius: 8,
                      border: '1px solid var(--border-subtle)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span className="mono" style={{ color: 'var(--text-dim)', fontSize: 12, fontWeight: 700 }}>
                        #{idx + 1}
                      </span>
                      <span className="mono" style={{ fontWeight: 600, color: 'var(--text-bright)' }}>
                        {rule.rule}
                      </span>
                    </div>
                    <span
                      className="mono"
                      style={{
                        background: 'var(--surface-3)',
                        padding: '3px 8px',
                        borderRadius: 4,
                        fontSize: 12,
                        fontWeight: 700,
                        color: 'var(--accent)',
                      }}
                    >
                      {rule.count} trigger{rule.count === 1 ? '' : 's'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Drift Score Distribution */}
          <div className="card" style={{ marginTop: 16 }}>
            <div className="card-header">
              <h2>
                <CompassIcon size={16} />
                <span>Drift Score Distribution Curve</span>
              </h2>
            </div>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart
                data={Object.entries(data.drift_score_buckets).map(([bucket, count]) => ({
                  bucket,
                  count,
                }))}
                margin={{ top: 12, right: 20, bottom: 8, left: -16 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="bucket" stroke="#94a3b8" fontSize={11} tickLine={false} />
                <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} />
                <Tooltip
                  contentStyle={{
                    background: '#ffffff',
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    boxShadow: 'var(--shadow-lg)',
                    color: 'var(--text-bright)',
                    fontSize: 12,
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="count"
                  name="Event Count"
                  stroke="#0284c7"
                  strokeWidth={2.5}
                  dot={{ r: 4, fill: '#0284c7' }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </>
  );
}
