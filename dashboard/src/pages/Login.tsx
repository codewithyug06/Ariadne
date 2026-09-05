// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState, type FormEvent } from 'react';
import { Navigate } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { LockIcon, ShieldIcon, SparklesIcon } from '../components/Icons';

export function Login() {
  const { login, status } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (status === 'authenticated') return <Navigate to="/" replace />;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Authentication failed.');
    } finally {
      setSubmitting(false);
    }
  };

  const fillDemoAdmin = () => {
    setEmail('admin@example.com');
    setPassword('dev-admin-password');
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: 'calc(100vh - 120px)',
        padding: 20,
      }}
    >
      <form
        className="card"
        style={{
          width: '100%',
          maxWidth: 400,
          padding: 32,
          boxShadow: 'var(--shadow-lg)',
          border: '1px solid var(--border)',
        }}
        onSubmit={onSubmit}
      >
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <div
            className="brand-icon"
            style={{ width: 44, height: 44, margin: '0 auto 12px', borderRadius: 12 }}
          >
            <ShieldIcon size={24} />
          </div>
          <h2 style={{ fontSize: 20, margin: 0, color: 'var(--text-bright)', textTransform: 'none' }}>
            Ariadne Firewall
          </h2>
          <div style={{ color: 'var(--text-dim)', fontSize: 13, marginTop: 4 }}>
            Causal Provenance & Agent Trajectory Security
          </div>
        </div>

        {error && <div className="card error" style={{ marginBottom: 14 }}>{error}</div>}

        <div className="field">
          <label htmlFor="login-email">Operator Email</label>
          <input
            id="login-email"
            type="email"
            autoComplete="username"
            required
            placeholder="admin@example.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>

        <div className="field" style={{ marginBottom: 20 }}>
          <label htmlFor="login-password">Password</label>
          <input
            id="login-password"
            type="password"
            autoComplete="current-password"
            required
            placeholder="••••••••••••"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>

        <button type="submit" className="primary" disabled={submitting} style={{ width: '100%', padding: '9px 16px' }}>
          <LockIcon size={14} />
          <span>{submitting ? 'Authenticating…' : 'Sign in to Dashboard'}</span>
        </button>

        <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--border-subtle)', textAlign: 'center' }}>
          <button
            type="button"
            className="secondary"
            onClick={fillDemoAdmin}
            style={{ width: '100%', fontSize: 12, padding: '6px 12px' }}
          >
            <SparklesIcon size={13} style={{ color: 'var(--accent)' }} />
            <span>Fill Local Dev Credentials</span>
          </button>
        </div>
      </form>
    </div>
  );
}
