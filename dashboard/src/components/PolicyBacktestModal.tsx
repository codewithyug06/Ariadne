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

  // Feature 11: Minimum Intervention Analysis, fetched automatically
  // alongside the single-run simulation result above.
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
    // Only seed once from the org default; user edits afterward should stick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

    // Feature 11: run the minimum-intervention sweep in parallel with (but
    // independent of) the simulation result above -- a failure here should
    // not blank out the simulation result the user already got.
    setInterventionLoading(true);
    try {
      const report = await api.eval.minimumIntervention({ incident_session_id: sessionId });
      if ('candidates' in report) {
        setInterventionReport(report);
      } else {
        // clean_run_sample_size > 500 dispatches an async job instead; the
        // default (200) used here always takes the synchronous path, but
        // this branch keeps the UI honest if that ever changes.
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
          <h2>{mode === 'single-run' ? 'Simulate policy on this run' : 'Backtest policy org-wide'}</h2>
          <span className="spacer" />
          <button className="linklike" onClick={onClose} aria-label="Close">
            close
          </button>
        </div>

        {error && (
          <div className="card" style={{ borderColor: 'var(--block)', marginBottom: 12 }}>
            {error}
          </div>
        )}

        {mode === 'org-wide' && (
          <div className="field">
            <label htmlFor="backtest-date-range">Date range</label>
            <select
              id="backtest-date-range"
              value={datePreset}
              onChange={(event) => setDatePreset(event.target.value as DateRangePreset)}
            >
              <option value="7d">Last 7 days</option>
              <option value="30d">Last 30 days</option>
              <option value="all">All time</option>
            </select>
          </div>
        )}

        <div className="row">
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="backtest-drift-block">BLOCK threshold</label>
            <input
              id="backtest-drift-block"
              type="number"
              value={driftBlock}
              onChange={(event) => setDriftBlock(Number(event.target.value))}
            />
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="backtest-tool-pattern">Tool name pattern (optional)</label>
            <input
              id="backtest-tool-pattern"
              value={toolPattern}
              placeholder="upload_to_"
              onChange={(event) => setToolPattern(event.target.value)}
            />
          </div>
        </div>

        {mode === 'single-run' ? (
          <>
            <div className="row" style={{ marginTop: 12 }}>
              <span className="spacer" />
              <button className="primary" disabled={busy || !sessionId} onClick={runSingleSimulation}>
                {busy ? 'Running…' : 'Run Simulation'}
              </button>
            </div>

            {simResult && (
              <div className="card" style={{ marginTop: 14 }}>
                {!simResult.found ? (
                  <div>Run not found.</div>
                ) : (
                  <>
                    <div>
                      <strong>Would this incident have been prevented?</strong>{' '}
                      <span className={`badge ${simResult.would_be_prevented ? 'ALLOW' : 'BLOCK'}`}>
                        {simResult.would_be_prevented ? 'YES' : 'NO'}
                      </span>
                    </div>
                    {simResult.would_be_prevented && simResult.prevented_at_step !== null && (
                      <div style={{ marginTop: 6 }}>
                        Prevented at step: <span className="mono">{simResult.prevented_at_step}</span>
                      </div>
                    )}
                    <div style={{ marginTop: 6 }}>
                      Current behavior:{' '}
                      <span className={`badge ${simResult.real_max_action ?? 'ALLOW'}`}>
                        {simResult.real_max_action ?? 'ALLOW'}
                      </span>
                    </div>
                    <div style={{ marginTop: 6 }}>
                      With this policy:{' '}
                      <span className={`badge ${simResult.proposed_max_action ?? 'ALLOW'}`}>
                        {simResult.proposed_max_action ?? 'ALLOW'}
                      </span>
                    </div>
                  </>
                )}
              </div>
            )}

            {(interventionLoading || interventionReport || interventionError) && (
              <details className="card" style={{ marginTop: 14 }} open>
                <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
                  Minimum Intervention Analysis
                </summary>
                {interventionLoading && (
                  <div className="empty" style={{ marginTop: 8 }}>
                    Running minimum intervention sweep…
                  </div>
                )}
                {interventionError && (
                  <div className="error" style={{ marginTop: 8 }}>
                    {interventionError}
                  </div>
                )}
                {interventionReport && (
                  <div style={{ marginTop: 8 }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Policy</th>
                          <th>Prevents at</th>
                          <th>New false pos.</th>
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
                                  ? { background: 'rgba(63, 185, 80, 0.08)', fontWeight: 600 }
                                  : undefined
                              }
                            >
                              <td>
                                {candidate.policy_name}
                                {isRecommended && (
                                  <span style={{ color: 'var(--allow)', marginLeft: 6 }}>
                                    ✓ RECOMMENDED
                                  </span>
                                )}
                              </td>
                              <td className="mono">
                                {candidate.prevented && candidate.prevented_at_step !== null
                                  ? `Step ${candidate.prevented_at_step}`
                                  : '—'}
                              </td>
                              <td className="mono">{candidate.new_false_positives_on_clean_sample}</td>
                            </tr>
                          );
                        })}
                        {interventionReport.candidates.length === 0 && (
                          <tr>
                            <td colSpan={3} className="empty">
                              No candidate policies evaluated.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>

                    {interventionReport.recommended && (
                      <>
                        <div style={{ marginTop: 10 }}>
                          <strong>RECOMMENDED:</strong> {interventionReport.recommended.policy_name}
                        </div>
                        <div style={{ marginTop: 4, color: 'var(--text-dim)', fontSize: 13 }}>
                          {interventionReport.recommendation_reason}
                        </div>
                        <div className="row" style={{ marginTop: 10 }}>
                          <span className="spacer" />
                          {/*
                            No "adopt/deploy policy" action exists anywhere else
                            in this codebase (PolicyBacktestModal's org-wide
                            mode above only ever shows a report; PolicyEditor's
                            "Save rule" flow is a separate, manual, deliberate
                            action). Feature 11's backend scope explicitly ends
                            at recommending a policy, not deploying one, so
                            this is a disabled stub rather than an invented
                            "adopt" endpoint call.
                          */}
                          <button
                            disabled
                            title="Not yet wired to policy deployment"
                          >
                            Adopt {interventionReport.recommended.policy_name}
                          </button>
                        </div>
                      </>
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
              <button className="primary" disabled={busy && jobStatus !== 'complete' && jobStatus !== 'failed'} onClick={runOrgWideBacktest}>
                {jobStatus === 'pending' || jobStatus === 'running' ? 'Running…' : 'Run Backtest'}
              </button>
            </div>

            {(jobStatus === 'pending' || jobStatus === 'running') && (
              <div className="empty" style={{ marginTop: 14 }}>
                Running backtest{jobId ? ` (job ${jobId})` : ''}…
              </div>
            )}

            {report && (
              <div style={{ marginTop: 14 }}>
                <div className="stat-grid">
                  <div className="stat-tile">
                    <div className="stat-value">{report.runs_analyzed}</div>
                    <div className="stat-label">Runs analyzed</div>
                  </div>
                  <div className="stat-tile">
                    <div className="stat-value">{report.incidents_prevented_delta}</div>
                    <div className="stat-label">Incidents prevented Δ</div>
                  </div>
                  <div className="stat-tile">
                    <div className="stat-value">{report.false_positive_delta}</div>
                    <div className="stat-label">False positives Δ</div>
                  </div>
                  <div className="stat-tile">
                    <div className="stat-value">{(report.detection_rate_delta * 100).toFixed(1)}%</div>
                    <div className="stat-label">Detection rate Δ</div>
                  </div>
                  <div className="stat-tile">
                    <div className="stat-value">{(report.fpr_delta * 100).toFixed(1)}%</div>
                    <div className="stat-label">FPR Δ</div>
                  </div>
                </div>

                <div className="row">
                  <span className={`recommendation-badge ${recommendationClass(report.recommendation)}`}>
                    {report.recommendation}
                  </span>
                </div>
                <div style={{ marginTop: 8, color: 'var(--text-dim)', fontSize: 13 }}>
                  {report.recommendation_reason}
                </div>

                <h2 style={{ marginTop: 16 }}>Changed runs ({report.changed_runs.length})</h2>
                <div className="changed-runs-list">
                  {report.changed_runs.length === 0 && (
                    <div className="row" style={{ color: 'var(--text-dim)' }}>
                      No runs changed decision under this policy.
                    </div>
                  )}
                  {report.changed_runs.map((diff) => (
                    <div key={diff.session_id} className="row">
                      <span className="mono" style={{ fontSize: 11 }}>
                        {diff.session_id}
                      </span>
                      <span className="spacer" />
                      <span className={`badge ${diff.real_decision}`}>{diff.real_decision}</span>
                      <span style={{ color: 'var(--text-dim)' }}>→</span>
                      <span className={`badge ${diff.proposed_decision}`}>{diff.proposed_decision}</span>
                      <span
                        style={{
                          fontSize: 11,
                          color:
                            diff.impact === 'incident_prevented' ? 'var(--allow)' : 'var(--block)',
                        }}
                      >
                        {diff.impact.replace(/_/g, ' ')}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        <div className="modal-footer">
          <button onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
