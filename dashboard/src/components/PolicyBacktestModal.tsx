// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState } from 'react';
import {
  api,
  type BacktestReport,
  type MinimumInterventionReport,
  type ProposedPolicy,
  type SimulateRunResult,
} from '../api/client';
import { useStatus } from '../hooks/useRuns';
import {
  ActivityIcon,
  PlayIcon,
  SparklesIcon,
} from './Icons';

export interface PolicyBacktestModalProps {
  mode: 'single-run' | 'org-wide';
  sessionId?: string;
  initialPolicy?: Partial<ProposedPolicy>;
  onClose: () => void;
}

type DateRangePreset = '7d' | '30d' | 'all';

function buildProposedPolicy(
  driftBlock: number | null,
  toolPattern: string,
  initialPolicy?: Partial<ProposedPolicy>,
): ProposedPolicy {
  return {
    name: initialPolicy?.name ?? 'draft',
    action: initialPolicy?.action ?? 'BLOCK',
    tool_name_patterns: toolPattern.trim() ? [toolPattern.trim()] : [],
    argument_patterns: initialPolicy?.argument_patterns ?? [],
    drift_warn: initialPolicy?.drift_warn ?? null,
    drift_escalate: initialPolicy?.drift_escalate ?? null,
    drift_block: driftBlock,
  };
}

function dateRangeFor(preset: DateRangePreset): { date_from: string | null; date_to: string | null } {
  if (preset === 'all') return { date_from: null, date_to: null };
  const now = new Date();
  const days = preset === '7d' ? 7 : 30;
  const from = new Date(now.getTime() - days * 24 * 60 * 60 * 1000);
  return { date_from: from.toISOString(), date_to: now.toISOString() };
}

function recommendationClass(recommendation: BacktestReport['recommendation']): string {
  if (recommendation === 'DEPLOY') return 'deploy';
  if (recommendation === 'REVIEW') return 'review';
  return 'reject';
}

export function PolicyBacktestModal({
  mode,
  sessionId,
  initialPolicy,
  onClose,
}: PolicyBacktestModalProps) {
  const { data: status } = useStatus();
  const [driftBlock, setDriftBlock] = useState<number>(
    initialPolicy?.drift_block ?? status?.drift_thresholds?.block ?? 85,
  );
  const [toolPattern, setToolPattern] = useState<string>(
    initialPolicy?.tool_name_patterns?.[0] ?? '',
  );
  const [datePreset, setDatePreset] = useState<DateRangePreset>('30d');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // single-run mode state
  const [simResult, setSimResult] = useState<SimulateRunResult | null>(null);

  // Minimum Intervention Analysis state
  const [interventionReport, setInterventionReport] = useState<MinimumInterventionReport | null>(
    null,
  );
  const [interventionLoading, setInterventionLoading] = useState(false);
  const [interventionError, setInterventionError] = useState<string | null>(null);

  // org-wide mode state
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<'pending' | 'running' | 'complete' | 'failed' | null>(
    null,
  );
  const [report, setReport] = useState<BacktestReport | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (status?.drift_thresholds?.block !== undefined && initialPolicy?.drift_block === undefined) {
      setDriftBlock(status.drift_thresholds.block);
    }
  }, [status?.drift_thresholds?.block]);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const runSingleSimulation = async () => {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    setSimResult(null);
    setInterventionReport(null);
    setInterventionError(null);
    try {
      const policy = buildProposedPolicy(driftBlock, toolPattern, initialPolicy);
      const result = await api.backtest.simulateRun(sessionId, policy);
      setSimResult(result);
    } catch (err) {
      setError(String(err));
      setBusy(false);
      return;
    }
    setBusy(false);

    setInterventionLoading(true);
    try {
      const rep = await api.eval.minimumIntervention({ incident_session_id: sessionId });
      if ('candidates' in rep) {
        setInterventionReport(rep);
      } else {
        setInterventionError('Minimum intervention analysis was dispatched as a background job.');
      }
    } catch (err) {
      setInterventionError(String(err));
    } finally {
      setInterventionLoading(false);
    }
  };

  const runOrgWideBacktest = async () => {
    setBusy(true);
    setError(null);
    setReport(null);
    setJobStatus(null);
    try {
      const policy = buildProposedPolicy(driftBlock, toolPattern, initialPolicy);
      const { date_from, date_to } = dateRangeFor(datePreset);
      const { job_id } = await api.backtest.run(policy, { date_from, date_to });
      setJobId(job_id);
      setJobStatus('pending');

      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const poll = await api.backtest.status(job_id);
          setJobStatus(poll.status);
          if (poll.status === 'complete' || poll.status === 'failed') {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            if (poll.status === 'complete') {
              const fullReport = await api.backtest.report(job_id, 'json');
              setReport(fullReport);
            } else {
              setError(poll.error ?? 'Backtest job failed.');
            }
          }
        } catch (err) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setError(String(err));
        }
      }, 2000);
    } catch (err) {
      setError(String(err));
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <SparklesIcon size={18} style={{ color: 'var(--accent)' }} />
            <h2>
              {mode === 'single-run'
                ? 'Simulate Proposed Policy on This Session'
                : 'Org-Wide Policy Counterfactual Simulation'}
            </h2>
          </div>
          <span className="spacer" />
          <button className="secondary" onClick={onClose} aria-label="Close" style={{ padding: '4px 10px' }}>
            ✕
          </button>
        </div>

        {error && (
          <div className="card error" style={{ marginBottom: 14 }}>
            {error}
          </div>
        )}

        {mode === 'org-wide' && (
          <div className="field">
            <label htmlFor="backtest-date-range">Evaluation Date Range</label>
            <select
              id="backtest-date-range"
              value={datePreset}
              onChange={(event) => setDatePreset(event.target.value as DateRangePreset)}
            >
              <option value="7d">Last 7 days</option>
              <option value="30d">Last 30 days</option>
              <option value="all">All recorded sessions</option>
            </select>
          </div>
        )}

        <div className="row">
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="backtest-drift-block">Simulated BLOCK Threshold</label>
            <input
              id="backtest-drift-block"
              type="number"
              value={driftBlock}
              onChange={(event) => setDriftBlock(Number(event.target.value))}
            />
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="backtest-tool-pattern">Tool Name Pattern (Optional)</label>
            <input
              id="backtest-tool-pattern"
              className="mono"
              value={toolPattern}
              placeholder="e.g. upload_to_s3"
              onChange={(event) => setToolPattern(event.target.value)}
            />
          </div>
        </div>

        {mode === 'single-run' ? (
          <>
            <div className="row" style={{ marginTop: 12 }}>
              <span className="spacer" />
              <button
                className="primary"
                disabled={busy || !sessionId}
                onClick={runSingleSimulation}
              >
                <PlayIcon size={14} />
                <span>{busy ? 'Simulating…' : 'Run Counterfactual Simulation'}</span>
              </button>
            </div>

            {simResult && (
              <div
                className="card"
                style={{
                  marginTop: 16,
                  background: 'var(--surface-2)',
                  borderColor: simResult.would_be_prevented ? 'var(--allow-border)' : 'var(--border)',
                }}
              >
                {!simResult.found ? (
                  <div>Run session not found in audit index.</div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span style={{ fontSize: 13, fontWeight: 600 }}>Would this policy have prevented the incident?</span>
                      <span className={`badge ${simResult.would_be_prevented ? 'allow' : 'block'}`} style={{ fontSize: 12 }}>
                        {simResult.would_be_prevented ? 'YES — PREVENTED' : 'NO — NOT PREVENTED'}
                      </span>
                    </div>

                    {simResult.would_be_prevented && simResult.prevented_at_step !== null && (
                      <div style={{ fontSize: 13, color: 'var(--text-bright)' }}>
                        Intercepted at: <strong className="mono">Step {simResult.prevented_at_step}</strong>
                      </div>
                    )}

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 4 }}>
                      <div style={{ background: 'var(--bg)', padding: '8px 12px', borderRadius: 6 }}>
                        <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase' }}>Actual Outcome</div>
                        <div style={{ marginTop: 4 }}>
                          <span className={`badge ${(simResult.real_max_action ?? 'ALLOW').toLowerCase()}`}>
                            {simResult.real_max_action ?? 'ALLOW'}
                          </span>
                        </div>
                      </div>
                      <div style={{ background: 'var(--bg)', padding: '8px 12px', borderRadius: 6 }}>
                        <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase' }}>Simulated Outcome</div>
                        <div style={{ marginTop: 4 }}>
                          <span className={`badge ${(simResult.proposed_max_action ?? 'ALLOW').toLowerCase()}`}>
                            {simResult.proposed_max_action ?? 'ALLOW'}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {(interventionLoading || interventionReport || interventionError) && (
              <details className="card" style={{ marginTop: 14 }} open>
                <summary style={{ cursor: 'pointer', fontWeight: 600, color: 'var(--accent)' }}>
                  Minimum Intervention Analysis & Recommendations
                </summary>
                {interventionLoading && (
                  <div className="empty">
                    <ActivityIcon size={20} style={{ margin: '0 auto 6px', color: 'var(--accent)' }} />
                    <div>Evaluating candidate intervention sweep…</div>
                  </div>
                )}
                {interventionError && (
                  <div className="error" style={{ marginTop: 8 }}>
                    {interventionError}
                  </div>
                )}
                {interventionReport && (
                  <div style={{ marginTop: 10 }}>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Candidate Policy</th>
                            <th>Intercepts At</th>
                            <th style={{ textAlign: 'right' }}>New False Positives</th>
                          </tr>
                        </thead>
                        <tbody>
                          {interventionReport.candidates.map((candidate) => {
                            const isRecommended =
                              interventionReport.recommended?.policy_name === candidate.policy_name;
                            return (
                              <tr
                                key={candidate.policy_name}
                                style={
                                  isRecommended
                                    ? { background: 'rgba(16, 185, 129, 0.08)', fontWeight: 600 }
                                    : undefined
                                }
                              >
                                <td>
                                  <span className="mono">{candidate.policy_name}</span>
                                  {isRecommended && (
                                    <span className="badge allow" style={{ marginLeft: 8, fontSize: 10 }}>
                                      RECOMMENDED
                                    </span>
                                  )}
                                </td>
                                <td className="mono">
                                  {candidate.prevented && candidate.prevented_at_step !== null
                                    ? `Step ${candidate.prevented_at_step}`
                                    : '—'}
                                </td>
                                <td style={{ textAlign: 'right' }} className="mono">
                                  {candidate.new_false_positives_on_clean_sample}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>

                    {interventionReport.recommended && (
                      <div
                        style={{
                          marginTop: 12,
                          background: 'var(--surface-2)',
                          padding: '12px 14px',
                          borderRadius: 8,
                          border: '1px solid var(--allow-border)',
                        }}
                      >
                        <div style={{ fontWeight: 700, color: 'var(--allow)', fontSize: 13 }}>
                          Recommended Rule: {interventionReport.recommended.policy_name}
                        </div>
                        <div style={{ marginTop: 4, color: 'var(--text-muted)', fontSize: 12.5 }}>
                          {interventionReport.recommendation_reason}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </details>
            )}
          </>
        ) : (
          <>
            <div className="row" style={{ marginTop: 12 }}>
              <span className="spacer" />
              <button
                className="primary"
                disabled={busy && jobStatus !== 'complete' && jobStatus !== 'failed'}
                onClick={runOrgWideBacktest}
              >
                <PlayIcon size={14} />
                <span>{jobStatus === 'pending' || jobStatus === 'running' ? 'Backtesting…' : 'Run Fleet Backtest'}</span>
              </button>
            </div>

            {(jobStatus === 'pending' || jobStatus === 'running') && (
              <div className="empty" style={{ marginTop: 14 }}>
                <ActivityIcon size={24} style={{ margin: '0 auto 8px', color: 'var(--accent)' }} />
                <div>Evaluating policy across historical sessions{jobId ? ` (Job ${jobId})` : ''}…</div>
              </div>
            )}

            {report && (
              <div style={{ marginTop: 14 }}>
                <div className="stat-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))' }}>
                  <div className="stat-tile">
                    <span className="stat-value">{report.runs_analyzed}</span>
                    <span className="stat-label">Analyzed</span>
                  </div>
                  <div className="stat-tile block">
                    <span className="stat-value" style={{ color: 'var(--block)' }}>{report.incidents_prevented_delta}</span>
                    <span className="stat-label">Prevented Δ</span>
                  </div>
                  <div className="stat-tile allow">
                    <span className="stat-value" style={{ color: 'var(--allow)' }}>{report.false_positive_delta}</span>
                    <span className="stat-label">FP Delta</span>
                  </div>
                  <div className="stat-tile">
                    <span className="stat-value">{(report.detection_rate_delta * 100).toFixed(1)}%</span>
                    <span className="stat-label">Detection Δ</span>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10 }}>
                  <span className={`recommendation-badge ${recommendationClass(report.recommendation)}`}>
                    VERDICT: {report.recommendation}
                  </span>
                </div>
                <div style={{ marginTop: 8, color: 'var(--text-muted)', fontSize: 13 }}>
                  {report.recommendation_reason}
                </div>

                <h3 style={{ marginTop: 16, fontSize: 13, textTransform: 'uppercase', color: 'var(--text-dim)' }}>
                  Changed Runs Under Proposed Policy ({report.changed_runs.length})
                </h3>
                <div className="table-wrap" style={{ marginTop: 8, maxHeight: 240, overflowY: 'auto' }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Session ID</th>
                        <th>Actual</th>
                        <th>Proposed</th>
                        <th>Impact</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.changed_runs.length === 0 && (
                        <tr>
                          <td colSpan={4} className="empty">
                            No runs changed decision under this proposed policy.
                          </td>
                        </tr>
                      )}
                      {report.changed_runs.map((diff) => (
                        <tr key={diff.session_id}>
                          <td className="mono">{diff.session_id.slice(0, 20)}…</td>
                          <td><span className={`badge ${diff.real_decision.toLowerCase()}`}>{diff.real_decision}</span></td>
                          <td><span className={`badge ${diff.proposed_decision.toLowerCase()}`}>{diff.proposed_decision}</span></td>
                          <td>
                            <span
                              style={{
                                fontSize: 12,
                                color: diff.impact === 'incident_prevented' ? 'var(--allow)' : 'var(--block)',
                                fontWeight: 600,
                              }}
                            >
                              {diff.impact.replace(/_/g, ' ')}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}

        <div className="modal-footer">
          <button className="secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
