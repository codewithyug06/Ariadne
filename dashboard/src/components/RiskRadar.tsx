// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from 'recharts';
import type { RiskDimensionReport } from '../api/client';
import { CompassIcon } from './Icons';

interface RiskRadarProps {
  riskDimensions: RiskDimensionReport | null;
}

export function RiskRadar({ riskDimensions }: RiskRadarProps) {
  if (!riskDimensions) {
    return (
      <div className="card">
        <div className="card-header">
          <h2>
            <CompassIcon size={16} />
            <span>5D Multi-Vector Risk Profile</span>
          </h2>
        </div>
        <div className="empty">No multi-dimensional risk scores available for this step.</div>
      </div>
    );
  }

  const data = [
    { dimension: 'Intent Drift', value: riskDimensions.intent.value, fullMark: 100 },
    { dimension: 'Tool Context', value: riskDimensions.tool.value, fullMark: 100 },
    { dimension: 'Privilege', value: riskDimensions.privilege.value, fullMark: 100 },
    { dimension: 'Identity', value: riskDimensions.identity.value, fullMark: 100 },
    { dimension: 'Data Egress', value: riskDimensions.data.value, fullMark: 100 },
  ];

  return (
    <div className="card">
      <div className="card-header">
        <h2>
          <CompassIcon size={16} />
          <span>5D Multi-Vector Risk Profile</span>
        </h2>
        <span className="mono" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          Aggregate Vector Risk: <strong style={{ color: 'var(--accent)' }}>{riskDimensions.aggregate} / 100</strong>
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.2fr) minmax(0, 1fr)', gap: 20, alignItems: 'center' }}>
        <div style={{ width: '100%', height: 260 }}>
          <ResponsiveContainer>
            <RadarChart data={data} outerRadius="72%">
              <PolarGrid stroke="#e2e8f0" />
              <PolarAngleAxis dataKey="dimension" tick={{ fill: '#334155', fontSize: 11, fontWeight: 600, fontFamily: 'var(--font-sans)' }} />
              <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 9 }} />
              <Radar
                name="Risk Vector"
                dataKey="value"
                stroke="#0284c7"
                fill="#0284c7"
                fillOpacity={0.25}
                strokeWidth={2}
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {data.map((item) => {
            const val = item.value;
            const color = val >= 66 ? 'var(--block)' : val >= 33 ? 'var(--warn)' : 'var(--allow)';
            return (
              <div key={item.dimension} style={{ background: 'var(--surface-2)', padding: '8px 12px', borderRadius: 6 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <span style={{ fontSize: 12, fontWeight: 500 }}>{item.dimension}</span>
                  <span className="mono" style={{ fontSize: 12, fontWeight: 700, color }}>
                    {val}
                  </span>
                </div>
                <div style={{ width: '100%', height: 4, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
                  <div style={{ width: `${val}%`, height: '100%', background: color }} />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
