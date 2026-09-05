// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState } from 'react';
import { api, type EnforcementAction, type Policy, type ProposedPolicy } from '../api/client';
import { usePolicies, useToolOverrides } from '../hooks/useRuns';
import { PolicyBacktestModal } from './PolicyBacktestModal';
import {
  CompassIcon,
  LockIcon,
  PlayIcon,
  RefreshIcon,
  ShieldAlertIcon,
  ShieldCheckIcon,
  SparklesIcon,
} from './Icons';

const EMPTY: Policy = {
  name: '',
  description: '',
  action: 'BLOCK',
  enabled: true,
  tool_name_patterns: [],
  argument_patterns: [],
  requires_hitl_token: false,
};

const PRESETS: { label: string; policy: Policy }[] = [
  {
    label: 'Block Database Deletes',
    policy: {
      name: 'no_database_delete',
      description: 'Prohibits drop table, delete from, and truncate commands without confirmation.',
      action: 'BLOCK',
      enabled: true,
      tool_name_patterns: ['execute_sql', 'db_query'],
      argument_patterns: ['drop table', 'delete from', 'truncate'],
      requires_hitl_token: false,
    },
  },
  {
    label: 'HITL for Financial Transfers',
    policy: {
      name: 'payment_requires_hitl',
      description: 'Requires human approval token for wire transfers and refund execution.',
      action: 'ESCALATE',
      enabled: true,
      tool_name_patterns: ['wire_transfer', 'send_payment', 'issue_refund'],
      argument_patterns: [],
      requires_hitl_token: true,
    },
  },
  {
    label: 'Block External Data Egress',
    policy: {
      name: 'no_external_egress',
      description: 'Prevents uploading files to third-party public storage buckets.',
      action: 'BLOCK',
      enabled: true,
      tool_name_patterns: ['upload_to_s3', 'publish_dataset', 'post_webhook'],
      argument_patterns: [],
      requires_hitl_token: false,
    },
  },
];

export function PolicyEditor() {
  const { data, error, mutate } = usePolicies();
  const [draft, setDraft] = useState<Policy>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [backtestModalOpen, setBacktestModalOpen] = useState(false);

  // Feature 10: org tool-risk overrides.
  const { data: overrides, error: overridesError, mutate: mutateOverrides } = useToolOverrides();
  const [overrideToolName, setOverrideToolName] = useState('');
  const [overrideRisk, setOverrideRisk] = useState('50');
  const [overrideBusy, setOverrideBusy] = useState(false);
  const [overrideMessage, setOverrideMessage] = useState<string | null>(null);

  const addOverride = async () => {
    if (!overrideToolName.trim()) {
      setOverrideMessage('A tool name is required.');
      return;
    }
    setOverrideBusy(true);
    try {
      await api.toolOverrides.create({
        tool_name: overrideToolName.trim(),
        risk_override: Number(overrideRisk),
      });
      setOverrideToolName('');
      setOverrideRisk('50');
      setOverrideMessage(null);
      await mutateOverrides();
    } catch (err) {
      setOverrideMessage(`Could not save override: ${String(err)}`);
    } finally {
      setOverrideBusy(false);
    }
  };

  const removeOverride = async (id: string) => {
    setOverrideBusy(true);
    try {
      await api.toolOverrides.delete(id);
      await mutateOverrides();
    } catch (err) {
      setOverrideMessage(`Could not delete override: ${String(err)}`);
    } finally {
      setOverrideBusy(false);
    }
  };

  const save = async () => {
    if (!draft.name.trim()) {
      setMessage('A rule needs a unique identifier name.');
      return;
    }
    setBusy(true);
    try {
      await api.upsertPolicy(draft);
      setDraft(EMPTY);
      setMessage(`Rule "${draft.name}" saved. It takes effect on the next intercepted tool call.`);
      await mutate();
    } catch (err) {
      setMessage(`Could not save rule: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (name: string) => {
    if (!window.confirm(`Delete rule "${name}"?`)) return;
    setBusy(true);
    try {
      await api.deletePolicy(name);
      setMessage(`Deleted rule "${name}".`);
      await mutate();
    } catch (err) {
      setMessage(`Could not delete rule: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return (
      <div className="card error">
        <ShieldAlertIcon size={20} />
        <div>Could not load policy engine: {String(error)}</div>
      </div>
    );
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>
            <LockIcon size={22} style={{ color: 'var(--accent)' }} />
            <span>Hard Policy Firewall Engine</span>
          </h1>
          <span className="subtitle">
            Deterministic zero-drift policy evaluation · Backend: <strong>{data?.backend ?? 'Built-in Layer'}</strong>
          </span>
        </div>
        <div className="actions">
          <button className="secondary" onClick={() => void mutate()} title="Refresh policies">
            <RefreshIcon size={14} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {message && (
        <div
          className="card"
          style={{
            borderColor: 'var(--accent)',
            background: 'var(--accent-bg)',
            color: 'var(--text-bright)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span>{message}</span>
          <button className="secondary" onClick={() => setMessage(null)} style={{ padding: '2px 8px' }}>
            ✕
          </button>
        </div>
      )}

      {/* Add / Edit Policy Form */}
      <div className="card">
        <div className="card-header">
          <h2>
            <SparklesIcon size={16} />
            <span>{draft.name ? `Edit Policy Rule: ${draft.name}` : 'Create or Update Policy Rule'}</span>
          </h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>Templates:</span>
            {PRESETS.map((p) => (
              <button
                key={p.label}
                className="secondary"
                style={{ fontSize: 11, padding: '3px 8px' }}
                onClick={() => setDraft(p.policy)}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <label htmlFor="policy-name">Rule Unique Identifier</label>
          <input
            id="policy-name"
            className="mono"
            value={draft.name}
            placeholder="e.g. no_external_uploads"
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
          />
        </div>

        <div className="field">
          <label htmlFor="policy-description">Rule Description / Violation Reason</label>
          <input
            id="policy-description"
            value={draft.description}
            placeholder="Explain why this action is restricted (returned to agent in error payload)"
            onChange={(event) => setDraft({ ...draft, description: event.target.value })}
          />
        </div>

        <div className="row">
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="policy-tools">Tool Name Patterns (comma-separated substrings or regex)</label>
            <input
              id="policy-tools"
              className="mono"
              value={draft.tool_name_patterns.join(', ')}
              placeholder="e.g. upload_to_, publish_, delete_file"
              onChange={(event) =>
                setDraft({ ...draft, tool_name_patterns: splitList(event.target.value) })
              }
            />
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="policy-args">Argument Patterns (comma-separated forbidden substrings)</label>
            <input
              id="policy-args"
              className="mono"
              value={draft.argument_patterns.join(', ')}
              placeholder="e.g. drop table, rm -rf, export_key"
              onChange={(event) =>
                setDraft({ ...draft, argument_patterns: splitList(event.target.value) })
              }
            />
          </div>
        </div>

        <div className="row" style={{ marginTop: 8 }}>
          <div className="field" style={{ width: 150 }}>
            <label htmlFor="policy-action">Enforcement Action</label>
            <select
              id="policy-action"
              value={draft.action}
              onChange={(event) =>
                setDraft({ ...draft, action: event.target.value as EnforcementAction })
              }
            >
              <option value="BLOCK">BLOCK (Hard Stop)</option>
              <option value="ESCALATE">ESCALATE (HITL)</option>
              <option value="WARN">WARN (Log Header)</option>
            </select>
          </div>

          <label className="checkbox">
            <input
              type="checkbox"
              checked={draft.requires_hitl_token}
              onChange={(event) =>
                setDraft({ ...draft, requires_hitl_token: event.target.checked })
              }
            />
            <span>Requires human approval token</span>
          </label>

          <label className="checkbox">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })}
            />
            <span>Rule Enabled</span>
          </label>

          <span className="spacer" />

          {draft.name && (
            <button className="secondary" onClick={() => setDraft(EMPTY)}>
              Cancel
            </button>
          )}

          <button className="secondary" disabled={busy} onClick={() => setBacktestModalOpen(true)}>
            <PlayIcon size={13} />
            <span>Backtest Simulation</span>
          </button>
          <button className="primary" disabled={busy} onClick={save}>
            <ShieldCheckIcon size={14} />
            <span>Save Policy Rule</span>
          </button>
        </div>
      </div>

      {backtestModalOpen && (
        <PolicyBacktestModal
          mode="org-wide"
          initialPolicy={draftToProposedPolicy(draft)}
          onClose={() => setBacktestModalOpen(false)}
        />
      )}

      {/* Active Rules Grid */}
      <div className="card">
        <div className="card-header">
          <h2>
            <ShieldCheckIcon size={16} />
            <span>Active Firewall Policies ({data?.items.length ?? 0})</span>
          </h2>
        </div>

        <div className="policy-grid">
          {(data?.items ?? []).map((policy) => (
            <div
              key={policy.name}
              className="policy-card"
              style={{ opacity: policy.enabled ? 1 : 0.55 }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <strong className="mono" style={{ fontSize: 13, color: 'var(--text-bright)' }}>
                  {policy.name}
                </strong>
                <span className={`badge ${policy.action.toLowerCase()}`}>{policy.action}</span>
              </div>

              <div style={{ color: 'var(--text-muted)', fontSize: 12.5, minHeight: 36 }}>
                {policy.description || 'No description provided.'}
              </div>

              {policy.tool_name_patterns.length > 0 && (
                <div style={{ background: 'var(--bg)', padding: '6px 8px', borderRadius: 4, fontSize: 11.5 }}>
                  <span style={{ color: 'var(--text-dim)' }}>Tools: </span>
                  <span className="mono" style={{ color: 'var(--accent)' }}>
                    {policy.tool_name_patterns.join(', ')}
                  </span>
                </div>
              )}

              {policy.argument_patterns.length > 0 && (
                <div style={{ background: 'var(--bg)', padding: '6px 8px', borderRadius: 4, fontSize: 11.5 }}>
                  <span style={{ color: 'var(--text-dim)' }}>Args: </span>
                  <span className="mono" style={{ color: 'var(--warn)' }}>
                    {policy.argument_patterns.join(', ')}
                  </span>
                </div>
              )}

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 4, paddingTop: 8, borderTop: '1px solid var(--border-subtle)' }}>
                <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                  {policy.requires_hitl_token ? '⚡ Needs HITL Token' : policy.enabled ? '● Active' : '○ Disabled'}
                </span>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button className="secondary" onClick={() => setDraft(policy)} style={{ padding: '3px 8px', fontSize: 11 }}>
                    Edit
                  </button>
                  <button className="danger" disabled={busy} onClick={() => remove(policy.name)} style={{ padding: '3px 8px', fontSize: 11 }}>
                    Delete
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Org Tool-Risk Overrides */}
      <div className="card">
        <div className="card-header">
          <h2>
            <CompassIcon size={16} />
            <span>Organization Contextual Tool-Risk Overrides ({overrides?.items.length ?? 0})</span>
          </h2>
          <span className="subtitle" style={{ fontSize: 11.5 }}>
            Pin baseline contextual risk scores for specific tools
          </span>
        </div>

        {overridesError && (
          <div className="error">Could not load tool overrides: {String(overridesError)}</div>
        )}
        {overrideMessage && (
          <div className="error" style={{ marginBottom: 12 }}>
            {overrideMessage}
          </div>
        )}

        <div className="row">
          <div className="field" style={{ flex: 1, marginBottom: 0 }}>
            <label htmlFor="override-tool-name">Tool Name</label>
            <input
              id="override-tool-name"
              className="mono"
              value={overrideToolName}
              placeholder="e.g. upload_to_s3"
              onChange={(event) => setOverrideToolName(event.target.value)}
            />
          </div>
          <div className="field" style={{ width: 180, marginBottom: 0 }}>
            <label htmlFor="override-risk">Risk Score Override (0–100)</label>
            <input
              id="override-risk"
              type="number"
              min={0}
              max={100}
              value={overrideRisk}
              onChange={(event) => setOverrideRisk(event.target.value)}
            />
          </div>
          <button className="primary" disabled={overrideBusy} onClick={addOverride} style={{ alignSelf: 'flex-end' }}>
            <span>Add Override</span>
          </button>
        </div>

        {(overrides?.items.length ?? 0) > 0 && (
          <div className="table-wrap" style={{ marginTop: 14 }}>
            <table>
              <thead>
                <tr>
                  <th>Tool Name</th>
                  <th style={{ textAlign: 'right', width: 140 }}>Pinned Risk Score</th>
                  <th style={{ width: 80 }} />
                </tr>
              </thead>
              <tbody>
                {overrides!.items.map((override) => (
                  <tr key={override.id}>
                    <td className="mono" style={{ fontWeight: 600, color: 'var(--text-bright)' }}>
                      {override.tool_name}
                    </td>
                    <td style={{ textAlign: 'right' }} className="mono">
                      <span
                        className="badge"
                        style={{
                          background: 'var(--surface-3)',
                          color: override.risk_override >= 60 ? 'var(--block)' : override.risk_override >= 30 ? 'var(--warn)' : 'var(--allow)',
                        }}
                      >
                        {override.risk_override} / 100
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        className="danger"
                        disabled={overrideBusy}
                        onClick={() => removeOverride(override.id)}
                        style={{ padding: '2px 8px', fontSize: 11 }}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

function draftToProposedPolicy(policy: Policy): Partial<ProposedPolicy> {
  return {
    name: policy.name || 'draft',
    action: policy.action,
    tool_name_patterns: policy.tool_name_patterns,
    argument_patterns: policy.argument_patterns,
  };
}

function splitList(value: string): string[] {
  return value
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean);
}
