// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState, type FormEvent } from 'react';
import useSWR from 'swr';
import { api, ApiError, type TeamMember, type UserRole } from '../api/client';

export function Team() {
  const { data: members, mutate, isLoading, error } = useSWR<TeamMember[]>('users', () => api.listUsers());
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<UserRole>('viewer');
  const [formError, setFormError] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<{ email: string; password: string } | null>(null);
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
    if (!window.confirm(`Remove ${member.email} from the team?`)) return;
    try {
      await api.deleteUser(member.id);
      await mutate();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not remove teammate.');
    }
  };

  return (
    <>
      <div className="page-header">
        <h1>Team</h1>
        <span className="subtitle">Who has access to this dashboard</span>
      </div>

      {revealed && (
        <div className="card" style={{ borderColor: '#1f6feb' }}>
          <h2>Temporary password for {revealed.email}</h2>
          <p>
            Share this with them directly — there is no email invite yet, so this is shown only
            once. They should change it from their own Account page after signing in.
          </p>
          <code className="mono" style={{ fontSize: 16, userSelect: 'all' }}>
            {revealed.password}
          </code>
          <div className="toolbar" style={{ marginTop: 12 }}>
            <button onClick={() => setRevealed(null)}>Dismiss</button>
          </div>
        </div>
      )}

      <form className="card" onSubmit={addTeammate}>
        <h2>Add a teammate</h2>
        {formError && <div className="error">{formError}</div>}
        <div className="row">
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="teammate-email">Email</label>
            <input
              id="teammate-email"
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>
          <div className="field" style={{ width: 160 }}>
            <label htmlFor="teammate-role">Role</label>
            <select
              id="teammate-role"
              value={role}
              onChange={(event) => setRole(event.target.value as UserRole)}
            >
              <option value="viewer">Viewer</option>
              <option value="admin">Admin</option>
            </select>
          </div>
        </div>
        <button type="submit" disabled={busy}>
          {busy ? 'Adding…' : 'Add teammate'}
        </button>
      </form>

      <div className="card">
        <h2>Members</h2>
        {error && <div className="error">Could not load the team.</div>}
        {isLoading && <div className="empty">Loading…</div>}
        {members?.map((member) => (
          <div key={member.id} className="event">
            <span>{member.email}</span>
            <span className="badge">{member.role}</span>
            <span className="reason">
              {member.last_login_at
                ? `last seen ${new Date(member.last_login_at).toLocaleString()}`
                : 'never signed in'}
            </span>
            <button onClick={() => resetPassword(member)}>Reset password</button>
            <button className="danger" onClick={() => removeMember(member)}>
              Remove
            </button>
          </div>
        ))}
      </div>
    </>
  );
}
