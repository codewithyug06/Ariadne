// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from 'react';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { useActiveCalibrationProfile, useCalibrationProfiles, useSettingsSummary } from '../hooks/useRuns';

export function Settings() {
  const { user } = useAuth();
  const { data, mutate, isLoading, error } = useSettingsSummary();
  const [warn, setWarn] = useState('');
  const [escalate, setEscalate] = useState('');
  const [block, setBlock] = useState('');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Feature 9: calibration profiles (admin only).
  const isAdmin = user?.role === 'admin';
  const {
    data: profiles,
    error: profilesError,
    mutate: mutateProfiles,
  } = useCalibrationProfiles();
  const { data: activeProfile, mutate: mutateActive } = useActiveCalibrationProfile();
  const [calibrationBusy, setCalibrationBusy] = useState(false);
  const [calibrationMessage, setCalibrationMessage] = useState<string | null>(null);

  const activate = async (version: string) => {
    setCalibrationBusy(true);
    setCalibrationMessage(null);
    try {
      await api.calibration.activate(version);
      await Promise.all([mutateProfiles(), mutateActive()]);
      setCalibrationMessage(`Activated calibration ${version}.`);
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
      const version = `v${new Date().toISOString()}`;
      const created = await api.calibration.recalibrate({ version });
      await mutateProfiles();
      setCalibrationMessage(
        `Recalibrated as ${created.version} (not yet active — use Activate to switch to it).`,
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
    try {
      await api.updateThresholds({
        warn: Number(warn),
        escalate: Number(escalate),
        block: Number(block),
      });
      await mutate();
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Could not save thresholds.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <h1>Settings</h1>
        <span className="subtitle">System configuration and drift thresholds</span>
      </div>

      {error && <div className="error">Could not load settings.</div>}
      {isLoading && <div className="empty">Loading…</div>}

      {data && (
        <>
          <div className="card">
            <h2>System</h2>
            <dl className="node-panel">
              <div>
                <dt>Environment</dt>
                <dd>{data.environment}</dd>
              </div>
              <div>
                <dt>Embedding model</dt>
                <dd className="mono">{data.embedding_model}</dd>
              </div>
              <div>
                <dt>Embedding device</dt>
                <dd>{data.embedding_device}</dd>
              </div>
              <div>
                <dt>Graph backend</dt>
                <dd>{data.graph_backend}</dd>
              </div>
              <div>
                <dt>Policy backend</dt>
                <dd>{data.hard_layer_backend}</dd>
              </div>
              <div>
                <dt>Fail mode</dt>
                <dd>{data.fail_mode}</dd>
              </div>
              <div>
                <dt>Upstream MCP URL</dt>
                <dd className="mono">{data.upstream_mcp_url}</dd>
              </div>
              <div>
                <dt>Rate limit</dt>
                <dd>{data.rate_limit_per_minute}/min per key</dd>
              </div>
            </dl>
          </div>

          <div className="card">
            <h2>Drift thresholds</h2>
            {saveError && <div className="error">{saveError}</div>}
            <div className="row">
              <div className="field" style={{ flex: 1 }}>
                <label htmlFor="threshold-warn">Warn</label>
                <input
                  id="threshold-warn"
                  type="number"
                  value={warn}
                  disabled={user?.role !== 'admin'}
                  onChange={(event) => setWarn(event.target.value)}
                />
              </div>
              <div className="field" style={{ flex: 1 }}>
                <label htmlFor="threshold-escalate">Escalate</label>
                <input
                  id="threshold-escalate"
                  type="number"
                  value={escalate}
                  disabled={user?.role !== 'admin'}
                  onChange={(event) => setEscalate(event.target.value)}
                />
              </div>
              <div className="field" style={{ flex: 1 }}>
                <label htmlFor="threshold-block">Block</label>
                <input
                  id="threshold-block"
                  type="number"
                  value={block}
                  disabled={user?.role !== 'admin'}
                  onChange={(event) => setBlock(event.target.value)}
                />
              </div>
            </div>
            {user?.role === 'admin' ? (
              <button disabled={saving} onClick={save}>
                {saving ? 'Saving…' : 'Save thresholds'}
              </button>
            ) : (
              <span className="subtitle">Only admins can change thresholds.</span>
            )}
          </div>
        </>
      )}

      {isAdmin && (
        <div className="card">
          <h2>Calibration (Feature 9)</h2>
          {profilesError && (
            <div className="error">Could not load calibration profiles: {String(profilesError)}</div>
          )}
          {calibrationMessage && (
            <div className="card" style={{ borderColor: '#1f6feb' }}>
              {calibrationMessage}
            </div>
          )}
          <div className="row" style={{ marginBottom: 8 }}>
            <span className="subtitle">
              Active: {activeProfile ? <span className="mono">{activeProfile.version}</span> : '—'}
            </span>
            <span className="spacer" />
            <button disabled={calibrationBusy} onClick={recalibrate}>
              {calibrationBusy ? 'Working…' : 'Recalibrate'}
            </button>
          </div>
          <table>
            <thead>
              <tr>
                <th>Version</th>
                <th>Dataset</th>
                <th>Sample size</th>
                <th>Detection rate</th>
                <th>FPR</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(profiles ?? []).map((profile) => (
                <tr key={profile.id}>
                  <td className="mono">{profile.version}</td>
                  <td>{profile.dataset}</td>
                  <td>{profile.sample_size}</td>
                  <td>{(profile.measured_detection_rate * 100).toFixed(1)}%</td>
                  <td>{(profile.measured_fpr * 100).toFixed(1)}%</td>
                  <td>{profile.is_active ? <span className="badge ALLOW">active</span> : '—'}</td>
                  <td>
                    {!profile.is_active && (
                      <button disabled={calibrationBusy} onClick={() => activate(profile.version)}>
                        Activate
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {(profiles ?? []).length === 0 && (
                <tr>
                  <td colSpan={7} className="empty">
                    No calibration profiles yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
