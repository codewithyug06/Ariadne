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

interface RiskRadarProps {
  riskDimensions: RiskDimensionReport | null;
}

export function RiskRadar({ riskDimensions }: RiskRadarProps) {
  if (!riskDimensions) {
    return (
      <div className="card">
        <h2>Risk profile</h2>
        <div className="empty">No risk data for this step.</div>
      </div>
    );
  }

  const data = [
    { dimension: 'Intent', value: riskDimensions.intent.value },
    { dimension: 'Tool', value: riskDimensions.tool.value },
    { dimension: 'Privilege', value: riskDimensions.privilege.value },
    { dimension: 'Identity', value: riskDimensions.identity.value },
    { dimension: 'Data', value: riskDimensions.data.value },
  ];

  return (
    <div className="card">
      <h2>Risk profile</h2>
      <div style={{ width: '100%', height: 260 }}>
        <ResponsiveContainer>
          <RadarChart data={data} outerRadius="75%">
            <PolarGrid stroke="#243044" />
            <PolarAngleAxis dataKey="dimension" tick={{ fill: '#8b98a9', fontSize: 12 }} />
            <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fill: '#8b98a9', fontSize: 10 }} />
            <Radar dataKey="value" stroke="#58a6ff" fill="#58a6ff" fillOpacity={0.35} />
          </RadarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
