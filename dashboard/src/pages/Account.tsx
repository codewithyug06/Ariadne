// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState, type FormEvent } from 'react';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';

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
        <h1>Account</h1>
        <span className="subtitle">{user?.email}</span>
      </div>

      <form className="card" style={{ maxWidth: 420 }} onSubmit={onSubmit}>
        <h2>Change password</h2>
        {error && <div className="error">{error}</div>}
        {success && (
          <div className="event ALLOW" style={{ marginBottom: 12 }}>
            Password changed. Other signed-in sessions have been signed out.
          </div>
        )}
        <div className="field">
          <label htmlFor="current-password">Current password</label>
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
          <label htmlFor="new-password">New password</label>
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
          <label htmlFor="confirm-password">Confirm new password</label>
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
        <button type="submit" disabled={saving}>
          {saving ? 'Saving…' : 'Change password'}
        </button>
      </form>
    </>
  );
}
