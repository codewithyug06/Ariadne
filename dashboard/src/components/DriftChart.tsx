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
  const color = ACTION_COLORS[payload.enforcement_action] ?? '#8b98a9';
  const emphasized = payload.enforcement_action === 'BLOCK';
  return (
    <circle
      cx={cx}
      cy={cy}
      r={emphasized ? 6 : 4}
      fill={color}
      stroke="#0b0f17"
      strokeWidth={emphasized ? 2 : 1}
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
  return (
    <div
      style={{
        background: '#131a26',
        border: '1px solid #243044',
        borderRadius: 6,
        padding: '8px 10px',
        fontSize: 12,
      }}
    >
      <div style={{ fontFamily: 'ui-monospace, monospace', fontWeight: 600 }}>
        step {point.step_index} · {point.tool_name}
      </div>
      <div style={{ color: ACTION_COLORS[point.enforcement_action], fontWeight: 600 }}>
        {point.enforcement_action}
      </div>
      <div style={{ color: '#8b98a9', marginTop: 4 }}>
        drift {point.drift_score.toFixed(1)} · slope {point.slope >= 0 ? '+' : ''}
        {point.slope.toFixed(3)}/step · distance {point.raw_distance.toFixed(3)}
      </div>
    </div>
  );
}

export function DriftChart({ points, thresholds, live = false }: Props) {
  if (points.length === 0) {
    return <div className="empty">No scored steps yet.</div>;
  }

  return (
    <div>
      <div className="toolbar">
        <span style={{ fontSize: 12, color: '#8b98a9' }}>
          {points.length} step{points.length === 1 ? '' : 's'} · peak{' '}
          {Math.max(...points.map((p) => p.drift_score)).toFixed(1)}
        </span>
        <span className="spacer" />
        <span style={{ fontSize: 12, color: '#8b98a9' }}>
          <span className={`live-dot ${live ? 'on' : 'off'}`} />
          {live ? 'live' : 'not connected'}
        </span>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={points} margin={{ top: 8, right: 76, bottom: 8, left: -16 }}>
          <CartesianGrid stroke="#243044" strokeDasharray="3 3" />
          <XAxis
            dataKey="step_index"
            stroke="#8b98a9"
            fontSize={11}
            label={{ value: 'step', position: 'insideBottomRight', fill: '#8b98a9', fontSize: 11 }}
          />
          <YAxis domain={[0, 100]} stroke="#8b98a9" fontSize={11} />
          <Tooltip content={<DriftTooltip />} />
          <ReferenceLine
            y={thresholds.warn}
            stroke={ACTION_COLORS.WARN}
            strokeDasharray="4 4"
            label={{ value: 'WARN', fill: ACTION_COLORS.WARN, fontSize: 10, position: 'right' }}
          />
          <ReferenceLine
            y={thresholds.escalate}
            stroke={ACTION_COLORS.ESCALATE}
            strokeDasharray="4 4"
            label={{
              value: 'ESCALATE',
              fill: ACTION_COLORS.ESCALATE,
              fontSize: 10,
              position: 'right',
            }}
          />
          <ReferenceLine
            y={thresholds.block}
            stroke={ACTION_COLORS.BLOCK}
            strokeDasharray="4 4"
            label={{ value: 'BLOCK', fill: ACTION_COLORS.BLOCK, fontSize: 10, position: 'right' }}
          />
          {/* Linear, not monotone: a spline between two scored steps bulges
              above the value of both, which would draw the curve over the BLOCK
              line on a run that never crossed it. */}
          <Line
            type="linear"
            dataKey="drift_score"
            stroke="#58a6ff"
            strokeWidth={2}
            dot={<DecisionDot />}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
