// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, ApiError, onSessionExpired, setAccessToken, type CurrentUser } from '../api/client';

type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

interface AuthContextValue {
  user: CurrentUser | null;
  status: AuthStatus;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>('loading');

  useEffect(() => {
    onSessionExpired(() => {
      setAccessToken(null);
      setUser(null);
      setStatus('unauthenticated');
    });
  }, []);

  useEffect(() => {
    // On a fresh page load there is no in-memory access token, only the
    // httpOnly refresh cookie (if the browser still has one). Try to trade
    // it for a fresh access token so a reload doesn't force a re-login.
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch('/api/v1/auth/refresh', {
          method: 'POST',
          credentials: 'include',
        });
        if (!response.ok) throw new Error('no session');
        const body = (await response.json()) as { access_token: string };
        setAccessToken(body.access_token);
        const me = await api.me();
        if (!cancelled) {
          setUser(me);
          setStatus('authenticated');
        }
      } catch {
        if (!cancelled) {
          setAccessToken(null);
          setStatus('unauthenticated');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      status,
      login: async (email: string, password: string) => {
        const response = await api.login(email, password);
        setAccessToken(response.access_token);
        const me = await api.me();
        setUser(me);
        setStatus('authenticated');
      },
      logout: async () => {
        try {
          await api.logout();
        } catch (error) {
          // Even if the server call fails (e.g. already expired), clear
          // local state so the UI doesn't strand the user mid-logout.
          if (!(error instanceof ApiError)) throw error;
        }
        setAccessToken(null);
        setUser(null);
        setStatus('unauthenticated');
      },
    }),
    [user, status],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside an AuthProvider');
  return context;
}
