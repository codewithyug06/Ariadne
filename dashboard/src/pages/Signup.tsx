// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState, type FormEvent } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { ArrowLeft, Building2, CheckCircle2, Key, Lock, Mail, Shield, Sparkles } from 'lucide-react';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';

export function Signup() {
  const { login, status } = useAuth();
  const [organizationName, setOrganizationName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [provisioned, setProvisioned] = useState<{ apiKey: string; orgSlug: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [enteringDashboard, setEnteringDashboard] = useState(false);

  if (status === 'authenticated') return <Navigate to="/" replace />;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    setSubmitting(true);
    try {
      const response = await api.organizations.signup({
        organization_name: organizationName,
        admin_email: email,
        admin_password: password,
      });
      setProvisioned({ apiKey: response.api_key, orgSlug: response.organization.slug });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create your organization.');
    } finally {
      setSubmitting(false);
    }
  };

  const onCopyKey = async () => {
    if (!provisioned) return;
    await navigator.clipboard.writeText(provisioned.apiKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const onEnterDashboard = async () => {
    setEnteringDashboard(true);
    try {
      // The signup response's api_key is for machine/agent callers
      // (X-Api-Key), not the dashboard's JWT session -- so log in with the
      // same email/password just submitted to actually establish one.
      await login(email, password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Account created, but sign-in failed.');
      setEnteringDashboard(false);
    }
  };

  return (
    <div
      className="login-viewport-wrapper"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: 'calc(100vh - 80px)',
        padding: '32px 16px',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          top: '15%',
          left: '50%',
          transform: 'translateX(-50%)',
          width: '600px',
          height: '350px',
          background: 'radial-gradient(circle, rgba(124, 58, 237, 0.18) 0%, rgba(79, 70, 229, 0.08) 50%, transparent 70%)',
          filter: 'blur(60px)',
          pointerEvents: 'none',
          zIndex: 0,
        }}
      />

      <div style={{ width: '100%', maxWidth: 440, position: 'relative', zIndex: 1 }}>
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            padding: '5px 14px',
            borderRadius: '9999px',
            background: 'rgba(124, 58, 237, 0.12)',
            border: '1px solid rgba(124, 58, 237, 0.28)',
            color: '#A78BFA',
            fontSize: '11.5px',
            fontWeight: 600,
            letterSpacing: '0.04em',
            textTransform: 'uppercase',
            marginBottom: 16,
            marginInline: 'auto',
          }}
        >
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: '#10B981',
              boxShadow: '0 0 10px #10B981',
              display: 'inline-block',
            }}
          />
          <span>Provision Your Own Ariadne Organization</span>
        </div>

        <div
          className="login-card-container"
          style={{
            width: '100%',
            background: 'var(--surface)',
            borderRadius: 24,
            padding: '36px 32px',
            boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.45), 0 0 35px -5px rgba(124, 58, 237, 0.2)',
            border: '1px solid rgba(124, 58, 237, 0.22)',
            backdropFilter: 'blur(20px)',
          }}
        >
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <img
              src="/assets/logo1.png"
              alt="Ariadne — AI Agent Provenance Firewall"
              className="brand-logo-light"
              style={{ width: 120, height: 'auto', margin: '0 auto 14px' }}
            />
            <img
              src="/assets/logo1-dark.png"
              alt="Ariadne — AI Agent Provenance Firewall"
              className="brand-logo-dark"
              style={{ width: 120, height: 'auto', margin: '0 auto 14px' }}
            />
            <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.02em', margin: 0, color: 'var(--text-bright)' }}>
              {provisioned ? 'Organization Created' : 'Create Your Organization'}
            </h1>
            <p style={{ color: 'var(--text-dim)', fontSize: 13, marginTop: 6, marginBottom: 0 }}>
              {provisioned
                ? 'Your tenant and first API key are ready.'
                : 'Every org gets its own isolated data, users, and API keys.'}
            </p>
          </div>

          {!provisioned ? (
            <form onSubmit={onSubmit}>
              {error && (
                <div
                  className="card error"
                  style={{
                    marginBottom: 16,
                    borderRadius: 10,
                    padding: '10px 14px',
                    fontSize: '12.5px',
                    border: '1px solid rgba(239, 68, 68, 0.4)',
                    background: 'rgba(239, 68, 68, 0.1)',
                    color: '#F87171',
                  }}
                >
                  {error}
                </div>
              )}

              <div className="field" style={{ marginBottom: 16 }}>
                <label htmlFor="signup-org" style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
                  <Building2 size={13} style={{ color: '#7C3AED' }} />
                  <span>Organization Name</span>
                </label>
                <input
                  id="signup-org"
                  type="text"
                  required
                  minLength={1}
                  maxLength={255}
                  placeholder="Acme Corp"
                  value={organizationName}
                  onChange={(event) => setOrganizationName(event.target.value)}
                  style={{ width: '100%', padding: '10px 14px', borderRadius: 10, fontSize: '13.5px', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', outline: 'none' }}
                />
              </div>

              <div className="field" style={{ marginBottom: 16 }}>
                <label htmlFor="signup-email" style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
                  <Mail size={13} style={{ color: '#7C3AED' }} />
                  <span>Admin Email</span>
                </label>
                <input
                  id="signup-email"
                  type="email"
                  autoComplete="username"
                  required
                  placeholder="you@company.com"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  style={{ width: '100%', padding: '10px 14px', borderRadius: 10, fontSize: '13.5px', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', outline: 'none' }}
                />
              </div>

              <div className="field" style={{ marginBottom: 16 }}>
                <label htmlFor="signup-password" style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
                  <Lock size={13} style={{ color: '#7C3AED' }} />
                  <span>Password</span>
                </label>
                <input
                  id="signup-password"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={8}
                  placeholder="At least 8 characters"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  style={{ width: '100%', padding: '10px 14px', borderRadius: 10, fontSize: '13.5px', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', outline: 'none' }}
                />
              </div>

              <div className="field" style={{ marginBottom: 20 }}>
                <label htmlFor="signup-confirm" style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
                  <Lock size={13} style={{ color: '#7C3AED' }} />
                  <span>Confirm Password</span>
                </label>
                <input
                  id="signup-confirm"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={8}
                  placeholder="Repeat password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  style={{ width: '100%', padding: '10px 14px', borderRadius: 10, fontSize: '13.5px', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', outline: 'none' }}
                />
              </div>

              <button
                type="submit"
                disabled={submitting}
                style={{
                  width: '100%',
                  padding: '11px 18px',
                  borderRadius: 10,
                  fontSize: '13.5px',
                  fontWeight: 600,
                  color: '#FFFFFF',
                  background: 'linear-gradient(135deg, #7C3AED 0%, #4F46E5 100%)',
                  border: 'none',
                  cursor: submitting ? 'not-allowed' : 'pointer',
                  boxShadow: '0 10px 25px -5px rgba(109, 40, 217, 0.45)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 8,
                  opacity: submitting ? 0.75 : 1,
                }}
              >
                {submitting ? <span>Provisioning Organization…</span> : (
                  <>
                    <Key size={15} />
                    <span>Create Organization</span>
                  </>
                )}
              </button>

              <div style={{ textAlign: 'center', marginTop: 18, fontSize: '12.5px', color: 'var(--text-dim)' }}>
                Already have an account? <Link to="/login" style={{ color: '#A78BFA' }}>Sign in</Link>
              </div>
            </form>
          ) : (
            <div>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '8px 12px',
                  borderRadius: 10,
                  background: 'rgba(16, 185, 129, 0.12)',
                  border: '1px solid rgba(16, 185, 129, 0.3)',
                  color: '#34D399',
                  fontSize: '12px',
                  marginBottom: 16,
                }}
              >
                <CheckCircle2 size={15} style={{ flexShrink: 0 }} />
                <span>Organization "{provisioned.orgSlug}" created.</span>
              </div>

              <p style={{ fontSize: 12.5, color: 'var(--text-dim)', marginBottom: 8 }}>
                This API key authenticates your agents against Ariadne's <code>/mcp</code> endpoint.
                It is shown once — copy it now:
              </p>
              <div
                style={{
                  position: 'relative',
                  background: '#0F172A',
                  border: '1px solid rgba(124, 58, 237, 0.3)',
                  borderRadius: 10,
                  padding: '12px 14px',
                  marginBottom: 20,
                  fontFamily: 'monospace',
                  fontSize: 12.5,
                  color: '#93C5FD',
                  wordBreak: 'break-all',
                }}
              >
                {provisioned.apiKey}
                <button
                  type="button"
                  onClick={onCopyKey}
                  style={{
                    position: 'absolute',
                    top: 8,
                    right: 8,
                    background: copied ? '#059669' : '#1E293B',
                    color: '#fff',
                    border: 'none',
                    borderRadius: 6,
                    padding: '4px 10px',
                    fontSize: 11,
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  {copied ? '✓ Copied' : 'Copy'}
                </button>
              </div>

              <button
                type="button"
                disabled={enteringDashboard}
                onClick={onEnterDashboard}
                style={{
                  width: '100%',
                  padding: '11px 18px',
                  borderRadius: 10,
                  fontSize: '13.5px',
                  fontWeight: 600,
                  color: '#FFFFFF',
                  background: 'linear-gradient(135deg, #FF5745 0%, #E11D48 100%)',
                  border: 'none',
                  cursor: enteringDashboard ? 'not-allowed' : 'pointer',
                  opacity: enteringDashboard ? 0.75 : 1,
                }}
              >
                {enteringDashboard ? 'Signing in…' : 'Enter Your Dashboard →'}
              </button>
              {error && (
                <div style={{ marginTop: 12, fontSize: 12.5, color: '#F87171' }}>{error}</div>
              )}
            </div>
          )}

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 16,
              marginTop: 22,
              paddingTop: 18,
              borderTop: '1px solid var(--border)',
              fontSize: '11.5px',
              color: 'var(--text-dim)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <Shield size={12} style={{ color: '#10B981' }} />
              <span>TLS 1.3 Verified</span>
            </div>
            <span>•</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <Sparkles size={12} style={{ color: '#A78BFA' }} />
              <span>Isolated Per-Org Data</span>
            </div>
          </div>

          <div style={{ textAlign: 'center', marginTop: 18 }}>
            <Link
              to="/landing"
              style={{ fontSize: '12.5px', color: 'var(--text-dim)', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 6 }}
            >
              <ArrowLeft size={13} />
              <span>Back to Product Overview</span>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
