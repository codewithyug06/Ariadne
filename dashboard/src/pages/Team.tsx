// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState, type FormEvent } from 'react';
import useSWR from 'swr';
import { api, ApiError, type TeamMember, type UserRole } from '../api/client';
import {
  CheckIcon,
  CopyIcon,
  RefreshIcon,
  UsersIcon,
} from '../components/Icons';

export function Team() {
  const { data: members, mutate, isLoading, error } = useSWR<TeamMember[]>('users', () => api.listUsers());
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<UserRole>('viewer');
  const [formError, setFormError] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<{ email: string; password: string } | null>(null);
  const [copiedPass, setCopiedPass] = useState(false);
  const [busy, setBusy] = useState(false);

  const addTeammate = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    setBusy(true);
    try {
      const created = await api.createUser(email, role);
      setRevealed({ email: created.user.email, password: created.temporary_password });
      setEmail('');
      setRole('viewer');
      await mutate();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not add teammate.');
    } finally {
      setBusy(false);
    }
  };

  const resetPassword = async (member: TeamMember) => {
    const result = await api.resetUserPassword(member.id);
    setRevealed({ email: member.email, password: result.temporary_password });
  };

  const removeMember = async (member: TeamMember) => {
    if (!window.confirm(`Revoke dashboard access for ${member.email}?`)) return;
    try {
      await api.deleteUser(member.id);
      await mutate();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not remove teammate.');
    }
  };

  const copyPassword = () => {
    if (!revealed) return;
    navigator.clipboard.writeText(revealed.password);
    setCopiedPass(true);
    setTimeout(() => setCopiedPass(false), 2000);
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>
            <UsersIcon size={22} style={{ color: 'var(--accent)' }} />
            <span>Team & Access Control</span>
          </h1>
          <span className="subtitle">
            Manage operator accounts, dashboard permissions, and credential lifecycles
          </span>
        </div>
        <div className="actions">
          <button className="secondary" onClick={() => void mutate()} title="Refresh team">
            <RefreshIcon size={14} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {revealed && (
        <div
          className="card"
          style={{
            borderColor: 'var(--accent)',
            background: 'var(--surface-2)',
            marginBottom: 16,
            padding: '16px 20px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <h2 style={{ margin: 0, color: 'var(--accent)', textTransform: 'none', fontSize: 14 }}>
              Temporary Access Credentials for {revealed.email}
            </h2>
            <button className="secondary" onClick={() => setRevealed(null)} style={{ padding: '2px 8px' }}>
              ✕
            </button>
          </div>
          <p style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 6 }}>
            Share this temporary password securely with the user. They will be prompted to change it upon first login.
          </p>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10 }}>
            <code
              className="mono"
              style={{
                fontSize: 16,
                background: 'var(--bg)',
                padding: '6px 14px',
                borderRadius: 6,
                border: '1px solid var(--border)',
                color: 'var(--text-bright)',
                userSelect: 'all',
              }}
            >
              {revealed.password}
            </code>
            <button className="primary" onClick={copyPassword} style={{ fontSize: 12 }}>
              {copiedPass ? <CheckIcon size={14} /> : <CopyIcon size={14} />}
              <span>{copiedPass ? 'Copied' : 'Copy Password'}</span>
            </button>
          </div>
        </div>
      )}

      {/* Add Teammate Form */}
      <form className="card" onSubmit={addTeammate}>
        <div className="card-header">
          <h2>
            <UsersIcon size={16} />
            <span>Provision New Operator Account</span>
          </h2>
        </div>

        {formError && <div className="card error" style={{ marginBottom: 12 }}>{formError}</div>}

        <div className="row">
          <div className="field" style={{ flex: 1, marginBottom: 0 }}>
            <label htmlFor="teammate-email">Operator Email Address</label>
            <input
              id="teammate-email"
              type="email"
              required
              placeholder="operator@company.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>
          <div className="field" style={{ width: 170, marginBottom: 0 }}>
            <label htmlFor="teammate-role">Role Permissions</label>
            <select
              id="teammate-role"
              value={role}
              onChange={(event) => setRole(event.target.value as UserRole)}
            >
              <option value="viewer">Viewer (Read-Only)</option>
              <option value="admin">Admin (Full Control)</option>
            </select>
          </div>
          <button type="submit" className="primary" disabled={busy} style={{ alignSelf: 'flex-end' }}>
            <span>{busy ? 'Provisioning…' : 'Add Operator'}</span>
          </button>
        </div>
      </form>

      {/* Members List */}
      <div className="card">
        <div className="card-header">
          <h2>
            <UsersIcon size={16} />
            <span>Active Team Members ({members?.length ?? 0})</span>
          </h2>
        </div>

        {error && <div className="error">Could not load team members: {String(error)}</div>}
        {isLoading && <div className="empty">Loading operators…</div>}

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Operator</th>
                <th>Role</th>
                <th>Last Active Session</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {members?.map((member) => (
                <tr key={member.id}>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div className="user-avatar" style={{ width: 28, height: 28, fontSize: 12 }}>
                        {member.email.charAt(0).toUpperCase()}
                      </div>
                      <span style={{ fontWeight: 600, color: 'var(--text-bright)' }}>{member.email}</span>
                    </div>
                  </td>
                  <td>
                    <span className={`badge ${member.role === 'admin' ? 'allow' : 'warn'}`}>
                      {member.role.toUpperCase()}
                    </span>
                  </td>
                  <td className="mono" style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                    {member.last_login_at
                      ? new Date(member.last_login_at).toLocaleString()
                      : 'Never logged in'}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <div style={{ display: 'inline-flex', gap: 6 }}>
                      <button className="secondary" onClick={() => resetPassword(member)} style={{ padding: '3px 8px', fontSize: 11 }}>
                        Reset Password
                      </button>
                      <button className="danger" onClick={() => removeMember(member)} style={{ padding: '3px 8px', fontSize: 11 }}>
                        Revoke
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
