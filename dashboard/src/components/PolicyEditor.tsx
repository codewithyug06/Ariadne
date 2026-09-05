// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState } from 'react';
import { api, type EnforcementAction, type Policy, type ProposedPolicy } from '../api/client';
import { usePolicies } from '../hooks/useRuns';
import { PolicyBacktestModal } from './PolicyBacktestModal';

const EMPTY: Policy = {
  name: '',
  description: '',
  action: 'BLOCK',
  enabled: true,
  tool_name_patterns: [],
  argument_patterns: [],
  requires_hitl_token: false,
};

export function PolicyEditor() {
  const { data, error, mutate } = usePolicies();
  const [draft, setDraft] = useState<Policy>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [backtestModalOpen, setBacktestModalOpen] = useState(false);

  const save = async () => {
    if (!draft.name.trim()) {
      setMessage('A rule needs a name.');
      return;
    }
    setBusy(true);
    try {
      await api.upsertPolicy(draft);
      setDraft(EMPTY);
      setMessage(`Saved rule "${draft.name}". It applies to the next tool call.`);
      await mutate();
    } catch (err) {
      setMessage(`Could not save: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (name: string) => {
    setBusy(true);
    try {
      await api.deletePolicy(name);
      setMessage(`Deleted rule "${name}".`);
      await mutate();
    } catch (err) {
      setMessage(`Could not delete: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return <div className="error">Could not load policies: {String(error)}</div>;
  }

  return (
    <>
      <div className="page-header">
        <h1>Hard policy rules</h1>
        <span className="subtitle">
          evaluated before drift scoring · backend: {data?.backend ?? '…'}
        </span>
      </div>

      {message && (
        <div className="card" style={{ borderColor: '#1f6feb' }}>
          {message}
        </div>
      )}

      <div className="card">
        <h2>Add or replace a rule</h2>
        <div className="field">
          <label htmlFor="policy-name">Name</label>
          <input
            id="policy-name"
            value={draft.name}
            placeholder="no_external_uploads"
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor="policy-description">Description (shown in the block reason)</label>
          <input
            id="policy-description"
            value={draft.description}
            placeholder="This deployment never uploads to third-party storage."
            onChange={(event) => setDraft({ ...draft, description: event.target.value })}
          />
        </div>
        <div className="row">
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="policy-tools">Tool name patterns (comma-separated)</label>
            <input
              id="policy-tools"
              value={draft.tool_name_patterns.join(', ')}
              placeholder="upload_to_, publish_"
              onChange={(event) =>
                setDraft({ ...draft, tool_name_patterns: splitList(event.target.value) })
              }
            />
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="policy-args">Argument patterns (comma-separated)</label>
            <input
              id="policy-args"
              value={draft.argument_patterns.join(', ')}
              placeholder="drop table, rm -rf"
              onChange={(event) =>
                setDraft({ ...draft, argument_patterns: splitList(event.target.value) })
              }
            />
          </div>
        </div>
        <div className="row">
          <div className="field" style={{ width: 160 }}>
            <label htmlFor="policy-action">Action</label>
            <select
              id="policy-action"
              value={draft.action}
              onChange={(event) =>
                setDraft({ ...draft, action: event.target.value as EnforcementAction })
              }
            >
              <option value="BLOCK">BLOCK</option>
              <option value="ESCALATE">ESCALATE</option>
              <option value="WARN">WARN</option>
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
            Requires human approval token
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })}
            />
            Enabled
          </label>
          <span className="spacer" />
          <button disabled={busy} onClick={() => setBacktestModalOpen(true)}>
            Backtest
          </button>
          <button className="primary" disabled={busy} onClick={save}>
            Save rule
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

      <div className="card">
        <h2>Active rules ({data?.items.length ?? 0})</h2>
        <div className="policy-grid">
          {(data?.items ?? []).map((policy) => (
            <div
              key={policy.name}
              style={{
                border: '1px solid #243044',
                borderRadius: 8,
                padding: 12,
                background: '#1a2331',
                opacity: policy.enabled ? 1 : 0.55,
              }}
            >
              <div className="row">
                <strong className="mono">{policy.name}</strong>
                <span className="spacer" />
                <span className={`badge ${policy.action}`}>{policy.action}</span>
              </div>
              <div style={{ color: '#8b98a9', fontSize: 12, margin: '6px 0' }}>
                {policy.description}
              </div>
              {policy.tool_name_patterns.length > 0 && (
                <div className="mono" style={{ fontSize: 11 }}>
                  tool ~ {policy.tool_name_patterns.join(', ')}
                </div>
              )}
              {policy.argument_patterns.length > 0 && (
                <div className="mono" style={{ fontSize: 11 }}>
                  args ~ {policy.argument_patterns.join(', ')}
                </div>
              )}
              <div className="row" style={{ marginTop: 8 }}>
                {policy.requires_hitl_token && (
                  <span style={{ fontSize: 11, color: '#8b98a9' }}>needs approval token</span>
                )}
                <span className="spacer" />
                <button onClick={() => setDraft(policy)}>Edit</button>
                <button className="danger" disabled={busy} onClick={() => remove(policy.name)}>
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
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
