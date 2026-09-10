// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';

export function AuthCallback() {
  const navigate = useNavigate();
  const { loginWithToken } = useAuth();
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;

    const hash = window.location.hash.slice(1);
    const params = new URLSearchParams(hash);
    const token = params.get('access_token');

    if (!token) {
      navigate('/login?error=google_callback_failed', { replace: true });
      return;
    }

    // Clear token from URL before user can bookmark or share it
    window.history.replaceState(null, '', '/auth/callback');

    loginWithToken(token)
      .then(() => navigate('/', { replace: true }))
      .catch(() => navigate('/login?error=google_callback_failed', { replace: true }));
  }, [loginWithToken, navigate]);

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: 'calc(100vh - 80px)',
        flexDirection: 'column',
        gap: 12,
        color: 'var(--text-dim)',
        fontSize: 14,
      }}
    >
      <div
        style={{
          width: 32,
          height: 32,
          border: '3px solid rgba(124, 58, 237, 0.3)',
          borderTopColor: '#7C3AED',
          borderRadius: '50%',
          animation: 'spin 0.8s linear infinite',
        }}
      />
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
      <span>Signing you in…</span>
    </div>
  );
}
