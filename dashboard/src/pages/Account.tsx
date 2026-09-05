// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState, type FormEvent } from 'react';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import {
  CheckIcon,
  LockIcon,
  UserIcon,
} from '../components/Icons';

export function Account() {
  const { user } = useAuth();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [saving, setSaving] = useState(false);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSuccess(false);
    if (newPassword !== confirmPassword) {
      setError('New password and confirmation do not match.');
      return;
    }
    setSaving(true);
    try {
      await api.changePassword(currentPassword, newPassword);
      setSuccess(true);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not change password.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>
            <UserIcon size={22} style={{ color: 'var(--accent)' }} />
            <span>Operator Account & Security Profile</span>
          </h1>
          <span className="subtitle">Manage authentication credentials and active security sessions</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 360px) minmax(0, 480px)', gap: 20, alignItems: 'start' }}>
        {/* Profile Card */}
        <div className="card">
          <div className="card-header">
            <h2>
              <UserIcon size={16} />
              <span>Operator Identity</span>
            </h2>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 16 }}>
            <div className="user-avatar" style={{ width: 44, height: 44, fontSize: 18 }}>
              {user?.email?.charAt(0).toUpperCase() || 'U'}
            </div>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-bright)' }}>{user?.email}</div>
              <div style={{ marginTop: 2 }}>
                <span className={`badge ${user?.role === 'admin' ? 'allow' : 'warn'}`}>
                  {user?.role?.toUpperCase()} PERMISSIONS
                </span>
              </div>
            </div>
          </div>
          <div style={{ background: 'var(--surface-2)', padding: '10px 14px', borderRadius: 8, fontSize: 12, color: 'var(--text-muted)' }}>
            Session is authenticated with scoped JSON Web Tokens.
          </div>
        </div>

        {/* Change Password Card */}
        <form className="card" onSubmit={onSubmit}>
          <div className="card-header">
            <h2>
              <LockIcon size={16} />
              <span>Update Password</span>
            </h2>
          </div>

          {error && <div className="card error" style={{ marginBottom: 12 }}>{error}</div>}
          {success && (
            <div
              className="card"
              style={{
                borderColor: 'var(--allow)',
                background: 'var(--allow-bg)',
                color: 'var(--allow)',
                marginBottom: 12,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}
            >
              <CheckIcon size={16} />
              <span>Password updated successfully. Other active sessions have been invalidated.</span>
            </div>
          )}

          <div className="field">
            <label htmlFor="current-password">Current Password</label>
            <input
              id="current-password"
              type="password"
              autoComplete="current-password"
              required
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="new-password">New Password (minimum 8 characters)</label>
            <input
              id="new-password"
              type="password"
              autoComplete="new-password"
              minLength={8}
              required
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="confirm-password">Confirm New Password</label>
            <input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              minLength={8}
              required
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
            />
          </div>
          <button type="submit" className="primary" disabled={saving} style={{ marginTop: 6 }}>
            <LockIcon size={14} />
            <span>{saving ? 'Updating Password…' : 'Change Password'}</span>
          </button>
        </form>
      </div>
    </>
  );
}
