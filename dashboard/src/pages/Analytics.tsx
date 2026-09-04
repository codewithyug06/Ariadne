// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

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
import { STATUS_COLORS } from '../api/client';
import { useAnalytics } from '../hooks/useRuns';

export function Analytics() {
  const { data, isLoading, error } = useAnalytics();

  return (
    <>
      <div className="page-header">
        <h1>Analytics</h1>
        <span className="subtitle">Trends over the last 30 days</span>
      </div>

      {error && <div className="error">Could not load analytics.</div>}
      {isLoading && <div className="empty">Loading…</div>}

      {data && (
        <>
          <div className="card">
            <h2>Run volume</h2>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={data.daily_volume} margin={{ top: 8, right: 16, bottom: 8, left: -16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
                <XAxis dataKey="date" stroke="#8b949e" fontSize={12} />
                <YAxis stroke="#8b949e" fontSize={12} />
                <Tooltip contentStyle={{ background: '#161b22', border: '1px solid #30363d' }} />
                <Legend />
                <Bar dataKey="allowed" stackId="a" fill={STATUS_COLORS.CLEAN} name="clean" />
                <Bar dataKey="warned" stackId="a" fill={STATUS_COLORS.WARNED} name="warned" />
                <Bar dataKey="escalated" stackId="a" fill={STATUS_COLORS.ESCALATED} name="escalated" />
                <Bar dataKey="blocked" stackId="a" fill={STATUS_COLORS.BLOCKED} name="blocked" />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="split">
            <div className="card">
              <h2>Decisions by action</h2>
              <dl className="node-panel">
                {Object.entries(data.decisions_by_action).map(([action, count]) => (
                  <div key={action}>
                    <dt>{action}</dt>
                    <dd>{count}</dd>
                  </div>
                ))}
                {Object.keys(data.decisions_by_action).length === 0 && (
                  <div className="empty">No events in this window.</div>
                )}
              </dl>
            </div>

            <div className="card">
              <h2>Top triggered rules</h2>
              {data.top_triggered_rules.length === 0 && <div className="empty">None triggered.</div>}
              {data.top_triggered_rules.map((rule) => (
                <div key={rule.rule} className="event">
                  <span className="tool">{rule.rule}</span>
                  <span className="score">{rule.count}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <h2>Drift score distribution</h2>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart
                data={Object.entries(data.drift_score_buckets).map(([bucket, count]) => ({
                  bucket,
                  count,
                }))}
                margin={{ top: 8, right: 16, bottom: 8, left: -16 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
                <XAxis dataKey="bucket" stroke="#8b949e" fontSize={12} />
                <YAxis stroke="#8b949e" fontSize={12} />
                <Tooltip contentStyle={{ background: '#161b22', border: '1px solid #30363d' }} />
                <Line type="monotone" dataKey="count" stroke="#58a6ff" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </>
  );
}
