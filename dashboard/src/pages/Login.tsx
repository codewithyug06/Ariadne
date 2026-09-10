// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState, type FormEvent } from 'react';
import { Link, Navigate, useSearchParams } from 'react-router-dom';
import { Key, Lock, Mail, Shield, Sparkles, UserPlus } from 'lucide-react';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';

const GOOGLE_ERROR_MESSAGES: Record<string, string> = {
  google_denied: 'Google sign-in was cancelled.',
  google_invalid: 'Google sign-in failed. Try again.',
  google_state_invalid: 'Sign-in session expired. Try again.',
  google_token_failed: 'Could not verify Google credentials. Try again.',
  google_userinfo_failed: 'Could not retrieve your Google account info.',
  google_email_unverified: 'Your Google account email is not verified.',
  google_callback_failed: 'Google sign-in failed. Try again.',
};

export function Login() {
  const { login, status } = useAuth();
  const [searchParams] = useSearchParams();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(
    GOOGLE_ERROR_MESSAGES[searchParams.get('error') ?? ''] ?? null
  );
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
      {/* Ambient gradient orbs */}
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
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          bottom: '10%',
          right: '20%',
          width: '320px',
          height: '240px',
          background: 'radial-gradient(circle, rgba(255, 87, 69, 0.12) 0%, transparent 70%)',
          filter: 'blur(50px)',
          pointerEvents: 'none',
          zIndex: 0,
        }}
      />

      <div style={{ width: '100%', maxWidth: 440, position: 'relative', zIndex: 1 }}>
        {/* Security Status Pill */}
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
          <span>Fail-Closed Gateway · MCP Proxy Active</span>
        </div>

        {/* Card Frame */}
        <form
          className="login-card-container"
          onSubmit={onSubmit}
          style={{
            width: '100%',
            background: 'var(--surface)',
            borderRadius: 24,
            padding: '36px 32px',
            boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.45), 0 0 35px -5px rgba(124, 58, 237, 0.2)',
            border: '1px solid rgba(124, 58, 237, 0.22)',
            backdropFilter: 'blur(20px)',
            transition: 'all 0.3s ease',
          }}
        >
          {/* Brand Header */}
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <img
              src="/assets/logo1.png"
              alt="Ariadne — AI Agent Provenance Firewall"
              className="brand-logo-light"
              style={{ width: 120, height: 'auto', margin: '0 auto 14px', filter: 'drop-shadow(0 4px 12px rgba(109, 40, 217, 0.25))' }}
            />
            <img
              src="/assets/logo1-dark.png"
              alt="Ariadne — AI Agent Provenance Firewall"
              className="brand-logo-dark"
              style={{ width: 120, height: 'auto', margin: '0 auto 14px', filter: 'drop-shadow(0 4px 12px rgba(167, 139, 250, 0.35))' }}
            />
            <h1
              style={{
                fontSize: 22,
                fontWeight: 700,
                letterSpacing: '-0.02em',
                margin: 0,
                color: 'var(--text-bright)',
                fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
              }}
            >
              Sign in to Ariadne
            </h1>
            <p style={{ color: 'var(--text-dim)', fontSize: 13, marginTop: 6, marginBottom: 0 }}>
              Causal Provenance Firewall &amp; Agent Drift Guardrail
            </p>
          </div>

          {/* Error Banner */}
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

          {/* Google Sign-In */}
          <a
            href="/api/v1/auth/google"
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 10,
              width: '100%',
              padding: '10px 18px',
              borderRadius: 10,
              fontSize: '13.5px',
              fontWeight: 600,
              color: 'var(--text)',
              background: 'var(--surface-2)',
              border: '1px solid var(--border)',
              textDecoration: 'none',
              marginBottom: 16,
              transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLAnchorElement).style.borderColor = '#7C3AED';
              (e.currentTarget as HTMLAnchorElement).style.boxShadow = '0 0 0 2px rgba(124, 58, 237, 0.15)';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLAnchorElement).style.borderColor = 'var(--border)';
              (e.currentTarget as HTMLAnchorElement).style.boxShadow = 'none';
            }}
          >
            {/* Google logo */}
            <svg width="17" height="17" viewBox="0 0 18 18" aria-hidden="true">
              <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.875 2.684-6.615z"/>
              <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z"/>
              <path fill="#FBBC05" d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z"/>
              <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"/>
            </svg>
            <span>Continue with Google</span>
          </a>

          {/* Divider */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              marginBottom: 16,
              color: 'var(--text-dim)',
              fontSize: '11.5px',
            }}
          >
            <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
            <span>or sign in with email</span>
            <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
          </div>

          {/* Email Field */}
          <div className="field" style={{ marginBottom: 16 }}>
            <label
              htmlFor="login-email"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontSize: '12px',
                fontWeight: 600,
                color: 'var(--text-muted)',
                marginBottom: 6,
              }}
            >
              <Mail size={13} style={{ color: '#7C3AED' }} />
              <span>Operator Email</span>
            </label>
            <input
              id="login-email"
              type="email"
              autoComplete="username"
              required
              placeholder="you@yourcompany.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              style={{
                width: '100%',
                padding: '10px 14px',
                borderRadius: 10,
                fontSize: '13.5px',
                border: '1px solid var(--border)',
                background: 'var(--bg)',
                color: 'var(--text)',
                outline: 'none',
                transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
              }}
              onFocus={(e) => {
                e.target.style.borderColor = '#7C3AED';
                e.target.style.boxShadow = '0 0 0 3px rgba(124, 58, 237, 0.18)';
              }}
              onBlur={(e) => {
                e.target.style.borderColor = 'var(--border)';
                e.target.style.boxShadow = 'none';
              }}
            />
          </div>

          {/* Password Field */}
          <div className="field" style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <label
                htmlFor="login-password"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  fontSize: '12px',
                  fontWeight: 600,
                  color: 'var(--text-muted)',
                }}
              >
                <Lock size={13} style={{ color: '#7C3AED' }} />
                <span>Password</span>
              </label>
            </div>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              required
              placeholder="••••••••••••"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              style={{
                width: '100%',
                padding: '10px 14px',
                borderRadius: 10,
                fontSize: '13.5px',
                border: '1px solid var(--border)',
                background: 'var(--bg)',
                color: 'var(--text)',
                outline: 'none',
                transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
              }}
              onFocus={(e) => {
                e.target.style.borderColor = '#7C3AED';
                e.target.style.boxShadow = '0 0 0 3px rgba(124, 58, 237, 0.18)';
              }}
              onBlur={(e) => {
                e.target.style.borderColor = 'var(--border)';
                e.target.style.boxShadow = 'none';
              }}
            />
          </div>

          {/* Submit Button */}
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
              transition: 'transform 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease',
              opacity: submitting ? 0.75 : 1,
            }}
            onMouseEnter={(e) => {
              if (!submitting) (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(-1px)';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(0)';
            }}
          >
            {submitting ? (
              <span>Authenticating…</span>
            ) : (
              <>
                <Key size={15} />
                <span>Sign In</span>
              </>
            )}
          </button>

          {/* Security features row */}
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
              <span>Zero-Side-Effects</span>
            </div>
          </div>

          {/* Sign up link */}
          <div style={{ textAlign: 'center', marginTop: 18 }}>
            <span style={{ fontSize: '12.5px', color: 'var(--text-dim)' }}>
              New to Ariadne?{' '}
            </span>
            <Link
              to="/signup"
              style={{
                fontSize: '12.5px',
                color: '#A78BFA',
                textDecoration: 'none',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                fontWeight: 600,
                transition: 'color 0.15s ease',
              }}
              onMouseEnter={(e) => ((e.currentTarget as HTMLAnchorElement).style.color = '#7C3AED')}
              onMouseLeave={(e) => ((e.currentTarget as HTMLAnchorElement).style.color = '#A78BFA')}
            >
              <UserPlus size={13} />
              <span>Create your organization</span>
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
}
