// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from 'react';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { useActiveCalibrationProfile, useCalibrationProfiles, useSettingsSummary } from '../hooks/useRuns';
import {
  CompassIcon,
  CpuIcon,
  RefreshIcon,
  SettingsIcon,
  ShieldAlertIcon,
  ShieldCheckIcon,
  SparklesIcon,
} from '../components/Icons';

export function Settings() {
  const { user } = useAuth();
  const { data, mutate, isLoading, error } = useSettingsSummary();
  const [warn, setWarn] = useState('');
  const [escalate, setEscalate] = useState('');
  const [block, setBlock] = useState('');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedSuccess, setSavedSuccess] = useState(false);

  // Feature 9: calibration profiles (admin only).
  const isAdmin = user?.role === 'admin';
  const {
    data: profiles,
    error: profilesError,
    mutate: mutateProfiles,
  } = useCalibrationProfiles();
  const { mutate: mutateActive } = useActiveCalibrationProfile();
  const [calibrationBusy, setCalibrationBusy] = useState(false);
  const [calibrationMessage, setCalibrationMessage] = useState<string | null>(null);

  const activate = async (version: string) => {
    setCalibrationBusy(true);
    setCalibrationMessage(null);
    try {
      await api.calibration.activate(version);
      await Promise.all([mutateProfiles(), mutateActive()]);
      setCalibrationMessage(`Calibration profile "${version}" activated successfully.`);
    } catch (err) {
      setCalibrationMessage(`Could not activate: ${String(err)}`);
    } finally {
      setCalibrationBusy(false);
    }
  };

  const recalibrate = async () => {
    setCalibrationBusy(true);
    setCalibrationMessage(null);
    try {
      const version = `cal-${Date.now()}`;
      await api.calibration.recalibrate({ version });
      await mutateProfiles();
      setCalibrationMessage(
        `Recalibrated as "${version}" (ready to activate).`,
      );
    } catch (err) {
      setCalibrationMessage(`Could not recalibrate: ${String(err)}`);
    } finally {
      setCalibrationBusy(false);
    }
  };

  useEffect(() => {
    if (!data) return;
    setWarn(String(data.drift_thresholds.warn));
    setEscalate(String(data.drift_thresholds.escalate));
    setBlock(String(data.drift_thresholds.block));
  }, [data]);

  const save = async () => {
    setSaveError(null);
    setSaving(true);
    setSavedSuccess(false);
    try {
      await api.updateThresholds({
        warn: Number(warn),
        escalate: Number(escalate),
        block: Number(block),
      });
      await mutate();
      setSavedSuccess(true);
      setTimeout(() => setSavedSuccess(false), 3000);
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Could not save thresholds.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>
            <SettingsIcon size={22} style={{ color: 'var(--accent)' }} />
            <span>System Configuration & Thresholds</span>
          </h1>
          <span className="subtitle">
            Pipeline parameters, drift scoring thresholds, and empirical calibration profiles
          </span>
        </div>
      </div>

      {error && (
        <div className="card error">
          <ShieldAlertIcon size={20} />
          <div>Could not load system configuration: {String(error)}</div>
        </div>
      )}
      {isLoading && <div className="empty">Loading system telemetry…</div>}

      {data && (
        <>
          {/* System Hardware & Architecture Overview */}
          <div className="card">
            <div className="card-header">
              <h2>
                <CpuIcon size={16} />
                <span>Firewall Telemetry & Core Topology</span>
              </h2>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
              <div style={{ background: 'var(--surface-2)', padding: '12px 14px', borderRadius: 8 }}>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase' }}>Environment</div>
                <div style={{ marginTop: 4, fontWeight: 700, color: 'var(--text-bright)' }}>{data.environment}</div>
              </div>
              <div style={{ background: 'var(--surface-2)', padding: '12px 14px', borderRadius: 8 }}>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase' }}>Embedding Model</div>
                <div className="mono" style={{ marginTop: 4, fontWeight: 700, color: 'var(--accent)' }}>{data.embedding_model}</div>
              </div>
              <div style={{ background: 'var(--surface-2)', padding: '12px 14px', borderRadius: 8 }}>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase' }}>Compute Device</div>
                <div style={{ marginTop: 4, fontWeight: 700, color: 'var(--text-bright)' }}>{data.embedding_device.toUpperCase()}</div>
              </div>
              <div style={{ background: 'var(--surface-2)', padding: '12px 14px', borderRadius: 8 }}>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase' }}>Provenance Graph Store</div>
                <div style={{ marginTop: 4, fontWeight: 700, color: 'var(--text-bright)' }}>{data.graph_backend}</div>
              </div>
              <div style={{ background: 'var(--surface-2)', padding: '12px 14px', borderRadius: 8 }}>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase' }}>Fail Mode Policy</div>
                <div style={{ marginTop: 4, fontWeight: 700, color: 'var(--allow)' }}>{data.fail_mode}</div>
              </div>
              <div style={{ background: 'var(--surface-2)', padding: '12px 14px', borderRadius: 8 }}>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase' }}>Upstream MCP URL</div>
                <div className="mono" style={{ marginTop: 4, fontSize: 12, color: 'var(--text-muted)' }}>{data.upstream_mcp_url}</div>
              </div>
            </div>
          </div>

          {/* Drift Scoring Thresholds */}
          <div className="card">
            <div className="card-header">
              <h2>
                <CompassIcon size={16} />
                <span>Drift Trajectory Action Thresholds</span>
              </h2>
              <span className="subtitle" style={{ fontSize: 11.5 }}>
                Scores 0–100 calculated via slope-amplified trajectory divergence
              </span>
            </div>

            {saveError && <div className="card error" style={{ marginBottom: 12 }}>{saveError}</div>}
            {savedSuccess && (
              <div className="card" style={{ borderColor: 'var(--allow)', background: 'var(--allow-bg)', color: 'var(--allow)', marginBottom: 12 }}>
                ✓ Thresholds updated and applied immediately to running proxy.
              </div>
            )}

            <div className="row">
              <div className="field" style={{ flex: 1 }}>
                <label htmlFor="threshold-warn" style={{ color: 'var(--warn)' }}>WARN Threshold (0–100)</label>
                <input
                  id="threshold-warn"
                  type="number"
                  value={warn}
                  disabled={!isAdmin}
                  onChange={(event) => setWarn(event.target.value)}
                />
              </div>
              <div className="field" style={{ flex: 1 }}>
                <label htmlFor="threshold-escalate" style={{ color: 'var(--escalate)' }}>ESCALATE Threshold (0–100)</label>
                <input
                  id="threshold-escalate"
                  type="number"
                  value={escalate}
                  disabled={!isAdmin}
                  onChange={(event) => setEscalate(event.target.value)}
                />
              </div>
              <div className="field" style={{ flex: 1 }}>
                <label htmlFor="threshold-block" style={{ color: 'var(--block)' }}>BLOCK Threshold (0–100)</label>
                <input
                  id="threshold-block"
                  type="number"
                  value={block}
                  disabled={!isAdmin}
                  onChange={(event) => setBlock(event.target.value)}
                />
              </div>
            </div>

            <div className="row" style={{ marginTop: 10 }}>
              {isAdmin ? (
                <button className="primary" disabled={saving} onClick={save}>
                  <ShieldCheckIcon size={14} />
                  <span>{saving ? 'Saving…' : 'Save Active Thresholds'}</span>
                </button>
              ) : (
                <span className="subtitle">Administrator privileges required to modify active thresholds.</span>
              )}
            </div>
          </div>
        </>
      )}

      {/* Calibration Profiles */}
      {isAdmin && (
        <div className="card">
          <div className="card-header">
            <h2>
              <SparklesIcon size={16} />
              <span>Empirical Calibration Profiles</span>
            </h2>
            <button className="secondary" disabled={calibrationBusy} onClick={recalibrate}>
              <RefreshIcon size={14} />
              <span>{calibrationBusy ? 'Recalibrating…' : 'Run Fleet Recalibration'}</span>
            </button>
          </div>

          {profilesError && (
            <div className="error" style={{ marginBottom: 12 }}>
              Could not load calibration profiles: {String(profilesError)}
            </div>
          )}
          {calibrationMessage && (
            <div className="card" style={{ borderColor: 'var(--accent)', background: 'var(--accent-bg)', marginBottom: 12 }}>
              {calibrationMessage}
            </div>
          )}

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Profile Version</th>
                  <th>Dataset Benchmark</th>
                  <th>Sample Size</th>
                  <th style={{ textAlign: 'right' }}>Detection Rate</th>
                  <th style={{ textAlign: 'right' }}>False Positive Rate</th>
                  <th style={{ width: 120 }}>Status</th>
                  <th style={{ width: 100 }} />
                </tr>
              </thead>
              <tbody>
                {(profiles ?? []).map((profile) => (
                  <tr key={profile.id}>
                    <td className="mono" style={{ fontWeight: 600, color: 'var(--text-bright)' }}>{profile.version}</td>
                    <td>{profile.dataset}</td>
                    <td className="mono">{profile.sample_size}</td>
                    <td style={{ textAlign: 'right', color: 'var(--allow)', fontWeight: 600 }} className="mono">
                      {(profile.measured_detection_rate * 100).toFixed(1)}%
                    </td>
                    <td style={{ textAlign: 'right', color: profile.measured_fpr > 0.05 ? 'var(--warn)' : 'var(--allow)' }} className="mono">
                      {(profile.measured_fpr * 100).toFixed(1)}%
                    </td>
                    <td>{profile.is_active ? <span className="badge allow">Active</span> : <span style={{ color: 'var(--text-dim)' }}>Archived</span>}</td>
                    <td style={{ textAlign: 'right' }}>
                      {!profile.is_active && (
                        <button
                          className="secondary"
                          disabled={calibrationBusy}
                          onClick={() => activate(profile.version)}
                          style={{ padding: '3px 8px', fontSize: 11 }}
                        >
                          Activate
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {(profiles ?? []).length === 0 && (
                  <tr>
                    <td colSpan={7} className="empty">
                      No calibration profiles recorded yet. Click "Run Fleet Recalibration" to compute initial baseline.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
