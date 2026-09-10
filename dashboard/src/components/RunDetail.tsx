// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, type EnforcementAction, type GraphNode } from '../api/client';
import { useGraph, useRun, useStatus } from '../hooks/useRuns';
import { useRunStream } from '../hooks/useRunStream';
import { DriftChart, type DriftPoint } from './DriftChart';
import { ErrorBoundary } from './ErrorBoundary';
import { PolicyBacktestModal } from './PolicyBacktestModal';
import { ProvenanceGraph } from './ProvenanceGraph';
import { RiskRadar } from './RiskRadar';
import { RunSummaryBar } from './RunSummaryBar';
import { StepDrawer } from './StepDrawer';
import { StepTable } from './StepTable';
import {
  ActivityIcon,
  AlertTriangleIcon,
  CheckIcon,
  CompassIcon,
  CopyIcon,
  DownloadIcon,
  ShieldAlertIcon,
  SparklesIcon,
} from './Icons';

const DEFAULT_THRESHOLDS = { warn: 40, escalate: 65, block: 85 };

export function RunDetail() {
  const { sessionId = '' } = useParams();
  const { data: detail, error, mutate } = useRun(sessionId);
  const { data: graph } = useGraph(sessionId);
  const { data: status } = useStatus();
  const { updates, connected } = useRunStream(sessionId);
  const [blameChain, setBlameChain] = useState<string[]>([]);
  const [selectedStep, setSelectedStep] = useState<number | null>(null);
  const [backtestModalOpen, setBacktestModalOpen] = useState(false);
  const [copiedId, setCopiedId] = useState(false);

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

  // When the WebSocket delivers a new step not yet in the REST snapshot,
  // immediately re-fetch so the StepTable rows appear without waiting 4 s.
  const knownStepsRef = useRef<Set<number>>(new Set());
  useEffect(() => {
    for (const u of updates) {
      if (!knownStepsRef.current.has(u.step_index)) {
        knownStepsRef.current.add(u.step_index);
        void mutate();
        break; // one mutate per batch is enough
      }
    }
  }, [updates, mutate]);

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

  const copySessionId = () => {
    navigator.clipboard.writeText(sessionId);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  if (error) {
    return (
      <div className="card error">
        <ShieldAlertIcon size={20} />
        <div>Could not load run {sessionId}: {String(error)}</div>
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="empty" style={{ paddingTop: '20vh' }}>
        <ActivityIcon size={32} style={{ margin: '0 auto 12px', color: 'var(--accent)' }} />
        <div>Loading session provenance…</div>
      </div>
    );
  }

  const { run } = detail;
  const thresholds = status?.drift_thresholds ?? DEFAULT_THRESHOLDS;

  const notableEvents = detail.events.filter((event) =>
    (['WARN', 'ESCALATE', 'BLOCK'] as EnforcementAction[]).includes(event.enforcement_action),
  );
  const severityRank: Record<EnforcementAction, number> = { ALLOW: 0, WARN: 1, ESCALATE: 2, BLOCK: 3 };
  const worstEvent = notableEvents.reduce<typeof notableEvents[number] | null>((worst, event) => {
    if (!worst) return event;
    return severityRank[event.enforcement_action] > severityRank[worst.enforcement_action] ? event : worst;
  }, null);
  const calloutIsBlock = worstEvent?.enforcement_action === 'BLOCK';

  const lastScoredEvent = [...detail.events].reverse().find((event) => event.risk_dimensions !== null);

  const lastProjectedEvent = [...detail.events].reverse().find((event) => event.projection !== null);
  const lastLiveProjectionUpdate = [...updates].reverse().find((update) => update.projection);
  const projection =
    lastLiveProjectionUpdate &&
    lastLiveProjectionUpdate.step_index >= (lastProjectedEvent?.step_index ?? -1)
      ? (lastLiveProjectionUpdate.projection ?? null)
      : (lastProjectedEvent?.projection ?? null);

  const selectedEvent = detail.events.find((event) => event.step_index === selectedStep) ?? null;
  const blastRadiusCount: number | null = null;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>
            <Link to="/" style={{ color: 'var(--text-dim)' }}>Runs</Link>
            <span style={{ color: 'var(--border-hover)', margin: '0 6px' }}>/</span>
            <span className="mono" style={{ color: 'var(--text-bright)' }}>{run.session_id}</span>
            <button className="copy-btn" onClick={copySessionId} title="Copy session ID" style={{ marginLeft: 4 }}>
              {copiedId ? <CheckIcon size={13} style={{ color: 'var(--allow)' }} /> : <CopyIcon size={13} />}
            </button>
          </h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
            <span className={`badge ${run.final_status.toLowerCase()}`}>{run.final_status}</span>
            {detail.active && (
              <span className="hud-pill active">
                <span className="live-dot on" />
                <span>Active Session</span>
              </span>
            )}
            <span className="subtitle">
              Started {new Date(run.started_at).toLocaleString()}
            </span>
          </div>
        </div>

        <div className="actions">
          <button className="secondary" onClick={() => void mutate()} title="Refresh run data">
            <ActivityIcon size={14} />
            <span>Refresh</span>
          </button>
          <a href={api.reportUrl(sessionId, 'json')} download>
            <button className="secondary">
              <DownloadIcon size={14} />
              <span>JSON</span>
            </button>
          </a>
          <a href={api.reportUrl(sessionId, 'markdown')} download>
            <button className="secondary">
              <DownloadIcon size={14} />
              <span>Markdown</span>
            </button>
          </a>
          <button className="primary" onClick={() => setBacktestModalOpen(true)}>
            <SparklesIcon size={14} />
            <span>Simulate Policy</span>
          </button>
        </div>
      </div>

      {backtestModalOpen && (
        <PolicyBacktestModal
          mode="single-run"
          sessionId={sessionId}
          onClose={() => setBacktestModalOpen(false)}
        />
      )}

      {/* Intent Anchor Card */}
      <div className="card">
        <div className="card-header">
          <h2>
            <CompassIcon size={16} />
            <span>Intent Anchor & Mission Statement</span>
          </h2>
          <span className="subtitle" style={{ fontSize: 11.5 }}>
            Immutable reference vector for trajectory drift measurement
          </span>
        </div>
        <div
          style={{
            background: 'var(--surface-2)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-sm)',
            padding: '12px 16px',
            fontSize: 13.5,
            color: 'var(--text-bright)',
            lineHeight: 1.5,
          }}
        >
          {run.intent_summary ? (
            run.intent_summary
          ) : (
            <span style={{ color: 'var(--text-dim)', fontStyle: 'italic' }}>
              No intent anchor captured during handshake. Hard policy rules remained active.
            </span>
          )}
        </div>

        <div className="toolbar" style={{ marginTop: 14, marginBottom: 0 }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            <strong>{run.total_steps}</strong> steps · Peak Drift <strong>{run.max_drift_score.toFixed(1)}</strong> ·{' '}
            <span style={{ color: run.blocked_count > 0 ? 'var(--block)' : 'inherit' }}>{run.blocked_count} blocked</span> ·{' '}
            <span style={{ color: run.escalated_count > 0 ? 'var(--escalate)' : 'inherit' }}>{run.escalated_count} escalated</span> ·{' '}
            <span style={{ color: run.warned_count > 0 ? 'var(--warn)' : 'inherit' }}>{run.warned_count} warned</span>
          </span>
        </div>
      </div>

      {/* Threat Narrative Briefing Callout */}
      {worstEvent?.narrative && (
        <div className={`threat-callout ${calloutIsBlock ? 'block' : 'warn'}`}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <AlertTriangleIcon
              size={18}
              style={{ color: calloutIsBlock ? 'var(--block)' : 'var(--warn)' }}
            />
            <span style={{ fontWeight: 700, fontSize: 13, color: calloutIsBlock ? 'var(--block)' : 'var(--warn)' }}>
              Security Threat Intelligence · Step {worstEvent.step_index} ({worstEvent.enforcement_action})
            </span>
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-bright)', lineHeight: 1.45 }}>
            <strong>{worstEvent.narrative.summary}</strong> {worstEvent.narrative.detail}
          </div>
          {worstEvent.narrative.trigger && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              <strong>Trigger Pattern:</strong> <code className="mono">{worstEvent.narrative.trigger}</code>
            </div>
          )}
        </div>
      )}

      {/* Projected Risk Card */}
      {projection && (
        <div className="card projection-card" style={{ marginTop: 16 }}>
          <div className="card-header">
            <h2 style={{ color: 'var(--accent)', margin: 0 }}>
              <SparklesIcon size={16} />
              <span>Projected Trajectory Vector (Linear Extrapolation)</span>
            </h2>
            <span className="mono" style={{ fontSize: 11.5, color: 'var(--text-dim)' }}>
              Confidence: {projection.confidence} ({projection.basis})
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12, marginTop: 10 }}>
            <div style={{ background: 'var(--surface-2)', padding: '10px 14px', borderRadius: 8 }}>
              <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase' }}>Next Step Projected Drift</div>
              <div className="mono" style={{ fontSize: 18, fontWeight: 700, marginTop: 4 }}>
                ~{Math.round(projection.projections[1] ?? 0)}
                {projection.will_cross_warn && (
                  <span className="badge WARN" style={{ marginLeft: 8, fontSize: 10 }}>
                    Approaching WARN
                  </span>
                )}
              </div>
            </div>
            <div style={{ background: 'var(--surface-2)', padding: '10px 14px', borderRadius: 8 }}>
              <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase' }}>In 3 Steps Projected Drift</div>
              <div className="mono" style={{ fontSize: 18, fontWeight: 700, marginTop: 4 }}>
                ~{Math.round(projection.projections[3] ?? 0)}
                {projection.will_cross_block && (
                  <span className="badge BLOCK" style={{ marginLeft: 8, fontSize: 10 }}>
                    Impending BLOCK
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Step Table */}
      <div style={{ marginTop: 16 }}>
        <StepTable
          events={detail.events}
          selectedStepIndex={selectedStep}
          onStepSelect={(step) => setSelectedStep(step)}
        />
      </div>

      {/* Executive Summary Bar */}
      <div style={{ marginTop: 16 }}>
        <RunSummaryBar
          events={detail.events}
          finalStatus={run.final_status}
          blastRadiusCount={blastRadiusCount}
        />
      </div>

      {/* Trajectory Chart & Provenance Graph Split */}
      <div className="split" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-header">
            <h2>
              <ActivityIcon size={16} />
              <span>Drift Trajectory Slope</span>
            </h2>
          </div>
          <ErrorBoundary label="Drift chart">
            <DriftChart points={points} thresholds={thresholds} live={connected} />
          </ErrorBoundary>
        </div>

        <div className="card">
          <div className="card-header">
            <h2>
              <CompassIcon size={16} />
              <span>Execution Provenance DAG</span>
            </h2>
          </div>
          {graph ? (
            <ErrorBoundary label="Provenance graph">
              <ProvenanceGraph graph={graph} blameChainIds={blameChain} />
            </ErrorBoundary>
          ) : (
            <div className="empty">Loading provenance graph…</div>
          )}
        </div>
      </div>

      {/* 5D Risk Radar Profile */}
      <div style={{ marginTop: 16 }}>
        <RiskRadar riskDimensions={lastScoredEvent?.risk_dimensions ?? null} />
      </div>

      {/* Step Inspector Slide-over Drawer */}
      <StepDrawer event={selectedEvent} onClose={() => setSelectedStep(null)} />
    </>
  );
}
