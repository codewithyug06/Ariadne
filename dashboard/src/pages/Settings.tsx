// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from 'react';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { useSettingsSummary } from '../hooks/useRuns';

export function Settings() {
  const { user } = useAuth();
  const { data, mutate, isLoading, error } = useSettingsSummary();
  const [warn, setWarn] = useState('');
  const [escalate, setEscalate] = useState('');
  const [block, setBlock] = useState('');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

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
    </>
  );
}
