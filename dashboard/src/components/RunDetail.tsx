// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, type EnforcementAction, type GraphNode } from '../api/client';
import { useGraph, useRun, useStatus } from '../hooks/useRuns';
import { useRunStream } from '../hooks/useRunStream';
import { DriftChart, type DriftPoint } from './DriftChart';
import { ErrorBoundary } from './ErrorBoundary';
import { ProvenanceGraph } from './ProvenanceGraph';

const DEFAULT_THRESHOLDS = { warn: 40, escalate: 65, block: 85 };

export function RunDetail() {
  const { sessionId = '' } = useParams();
  const { data: detail, error } = useRun(sessionId);
  const { data: graph } = useGraph(sessionId);
  const { data: status } = useStatus();
  const { updates, connected } = useRunStream(sessionId);
  const [blameChain, setBlameChain] = useState<string[]>([]);

  // The REST events are authoritative; live updates fill in steps that have
  // not yet been flushed to the audit database.
  const points: DriftPoint[] = useMemo(() => {
    const byStep = new Map<number, DriftPoint>();
    for (const event of detail?.events ?? []) {
      byStep.set(event.step_index, {
        step_index: event.step_index,
        tool_name: event.tool_name,
        drift_score: event.drift_score ?? 0,
        slope: event.slope ?? 0,
        raw_distance: event.raw_distance ?? 0,
        enforcement_action: event.enforcement_action,
      });
    }
    for (const update of updates) {
      if (!byStep.has(update.step_index)) {
        byStep.set(update.step_index, {
          step_index: update.step_index,
          tool_name: update.tool_name,
          drift_score: update.drift_score,
          slope: update.slope,
          raw_distance: update.raw_distance,
          enforcement_action: update.enforcement_action,
        });
      }
    }
    return [...byStep.values()].sort((a, b) => a.step_index - b.step_index);
  }, [detail?.events, updates]);

  // Highlight the whole blame chain, not just its endpoint, when a run blocked.
  useEffect(() => {
    const blocked = detail?.events.find(
      (event) => event.enforcement_action === 'BLOCK' && event.node_id,
    );
    if (!blocked?.node_id) {
      setBlameChain([]);
      return;
    }
    let cancelled = false;
    api
      .getRootCause(sessionId, blocked.node_id)
      .then((chain: GraphNode[]) => !cancelled && setBlameChain(chain.map((node) => node.id)))
      .catch(() => !cancelled && setBlameChain([]));
    return () => {
      cancelled = true;
    };
  }, [detail?.events, sessionId]);

  if (error) {
    return <div className="error">Could not load run {sessionId}: {String(error)}</div>;
  }
  if (!detail) {
    return <div className="empty">Loading run…</div>;
  }

  const { run } = detail;
  const thresholds = status?.drift_thresholds ?? DEFAULT_THRESHOLDS;

  return (
    <>
      <div className="page-header">
        <h1>
          <Link to="/">Runs</Link> <span style={{ color: '#8b98a9' }}>/</span>{' '}
          <span className="mono">{run.session_id}</span>
        </h1>
        <span className={`badge ${run.final_status}`}>{run.final_status}</span>
        {detail.active && <span className="subtitle">· active</span>}
      </div>

      <div className="card">
        <h2>Intent anchor</h2>
        <div>{run.intent_summary || <span style={{ color: '#8b98a9' }}>not captured</span>}</div>
        <div className="toolbar" style={{ marginTop: 12, marginBottom: 0 }}>
          <span style={{ fontSize: 12, color: '#8b98a9' }}>
            {run.total_steps} steps · peak drift {run.max_drift_score.toFixed(1)} ·{' '}
            {run.blocked_count} blocked · {run.escalated_count} escalated · {run.warned_count} warned
          </span>
          <span className="spacer" />
          <a href={api.reportUrl(sessionId, 'json')} download>
            <button>Export JSON</button>
          </a>
          <a href={api.reportUrl(sessionId, 'markdown')} download>
            <button>Export Markdown</button>
          </a>
        </div>
      </div>

      <div className="split" style={{ marginTop: 16 }}>
        <div>
          <div className="card">
            <h2>Drift trajectory</h2>
            <ErrorBoundary label="Drift chart">
              <DriftChart points={points} thresholds={thresholds} live={connected} />
            </ErrorBoundary>
          </div>

          <div className="card">
            <h2>Event timeline</h2>
            <div className="timeline">
              {detail.events.length === 0 && <div className="empty">No events recorded.</div>}
              {detail.events.map((event) => (
                <div key={event.event_id} className={`event ${event.enforcement_action}`}>
                  <div className="step">{event.step_index}</div>
                  <div>
                    <div className="tool">
                      {event.tool_name}
                      {event.triggered_rule && (
                        <span style={{ color: '#8b98a9', fontWeight: 400 }}>
                          {' '}
                          · {event.triggered_rule}
                        </span>
                      )}
                    </div>
                    <div className="reason">{event.reason}</div>
                  </div>
                  <div className="score">
                    <span className={`badge ${event.enforcement_action}`}>
                      {event.enforcement_action as EnforcementAction}
                    </span>
                    <div style={{ color: '#8b98a9', marginTop: 4 }}>
                      {event.drift_score !== null ? event.drift_score.toFixed(1) : '—'}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="card">
          <h2>Execution provenance</h2>
          {graph ? (
            <ErrorBoundary label="Provenance graph">
              <ProvenanceGraph graph={graph} blameChainIds={blameChain} />
            </ErrorBoundary>
          ) : (
            <div className="empty">Loading graph…</div>
          )}
        </div>
      </div>
    </>
  );
}
