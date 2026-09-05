// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { ACTION_COLORS, type EnforcementAction } from '../api/client';
import { ActivityIcon } from './Icons';

export interface DriftPoint {
  step_index: number;
  tool_name: string;
  drift_score: number;
  slope: number;
  raw_distance: number;
  enforcement_action: EnforcementAction;
}

interface Props {
  points: DriftPoint[];
  thresholds: { warn: number; escalate: number; block: number };
  live?: boolean;
}

interface DotProps {
  cx?: number;
  cy?: number;
  payload?: DriftPoint;
}

/** Points are coloured by the decision they produced, not by score alone —
 *  a hard-layer BLOCK can sit at a low score and must still read as a block. */
function DecisionDot({ cx, cy, payload }: DotProps) {
  if (cx === undefined || cy === undefined || !payload) return null;
  const color = ACTION_COLORS[payload.enforcement_action] ?? '#64748b';
  const emphasized = payload.enforcement_action === 'BLOCK' || payload.enforcement_action === 'ESCALATE';
  return (
    <circle
      cx={cx}
      cy={cy}
      r={emphasized ? 6 : 4.5}
      fill={color}
      stroke="#ffffff"
      strokeWidth={emphasized ? 2.5 : 1.5}
      style={{ filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.2))' }}
    />
  );
}

interface TooltipProps {
  active?: boolean;
  payload?: { payload: DriftPoint }[];
}

function DriftTooltip({ active, payload }: TooltipProps) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  const actionColor = ACTION_COLORS[point.enforcement_action] || '#64748b';
  return (
    <div
      style={{
        background: 'rgba(255, 255, 255, 0.98)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        padding: '10px 14px',
        fontSize: 12,
        boxShadow: 'var(--shadow-lg)',
        backdropFilter: 'blur(8px)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <span style={{ fontFamily: 'var(--mono)', fontWeight: 700, color: 'var(--text-bright)' }}>
          Step {point.step_index} · {point.tool_name}
        </span>
        <span className={`badge ${point.enforcement_action.toLowerCase()}`}>
          {point.enforcement_action}
        </span>
      </div>
      <div style={{ marginTop: 6, display: 'grid', gridTemplateColumns: 'auto auto', gap: '4px 12px', fontSize: 11.5 }}>
        <span style={{ color: 'var(--text-dim)' }}>Drift Score:</span>
        <span className="mono" style={{ fontWeight: 700, color: actionColor }}>
          {point.drift_score.toFixed(1)} / 100
        </span>
        <span style={{ color: 'var(--text-dim)' }}>Slope:</span>
        <span className="mono" style={{ color: 'var(--text)' }}>
          {point.slope >= 0 ? '+' : ''}{point.slope.toFixed(3)}/step
        </span>
        <span style={{ color: 'var(--text-dim)' }}>Raw Distance:</span>
        <span className="mono" style={{ color: 'var(--text)' }}>
          {point.raw_distance.toFixed(3)}
        </span>
      </div>
    </div>
  );
}

export function DriftChart({ points, thresholds, live = false }: Props) {
  if (points.length === 0) {
    return (
      <div className="empty">
        <ActivityIcon size={24} style={{ margin: '0 auto 8px', color: 'var(--text-dim)' }} />
        <div>No scored steps recorded yet.</div>
      </div>
    );
  }

  const peak = Math.max(...points.map((p) => p.drift_score));

  return (
    <div>
      <div className="toolbar" style={{ marginBottom: 10 }}>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          <strong>{points.length}</strong> step{points.length === 1 ? '' : 's'} · Peak Drift{' '}
          <strong style={{ color: peak >= 85 ? 'var(--block)' : peak >= 65 ? 'var(--escalate)' : 'var(--text-bright)' }}>
            {peak.toFixed(1)}
          </strong>
        </span>
        <span className="spacer" />
        <div className="hud-pill" style={{ padding: '2px 8px' }}>
          <span className={`live-dot ${live ? 'on' : ''}`} />
          <span style={{ fontSize: 11 }}>{live ? 'Live Stream' : 'Historical Audit'}</span>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={290}>
        <LineChart data={points} margin={{ top: 12, right: 65, bottom: 8, left: -20 }}>
          <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
          <XAxis
            dataKey="step_index"
            stroke="#94a3b8"
            fontSize={11}
            tickLine={false}
            label={{ value: 'Step #', position: 'insideBottomRight', fill: '#64748b', fontSize: 10, offset: -4 }}
          />
          <YAxis domain={[0, 100]} stroke="#94a3b8" fontSize={11} tickLine={false} />
          <Tooltip content={<DriftTooltip />} />
          <ReferenceLine
            y={thresholds.warn}
            stroke={ACTION_COLORS.WARN}
            strokeDasharray="4 4"
            strokeOpacity={0.8}
            label={{ value: `WARN (${thresholds.warn})`, fill: ACTION_COLORS.WARN, fontSize: 10, position: 'right' }}
          />
          <ReferenceLine
            y={thresholds.escalate}
            stroke={ACTION_COLORS.ESCALATE}
            strokeDasharray="4 4"
            strokeOpacity={0.8}
            label={{
              value: `ESCALATE (${thresholds.escalate})`,
              fill: ACTION_COLORS.ESCALATE,
              fontSize: 10,
              position: 'right',
            }}
          />
          <ReferenceLine
            y={thresholds.block}
            stroke={ACTION_COLORS.BLOCK}
            strokeDasharray="4 4"
            strokeOpacity={0.8}
            label={{ value: `BLOCK (${thresholds.block})`, fill: ACTION_COLORS.BLOCK, fontSize: 10, position: 'right' }}
          />
          <Line
            type="linear"
            dataKey="drift_score"
            stroke="#0284c7"
            strokeWidth={2.5}
            dot={<DecisionDot />}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
