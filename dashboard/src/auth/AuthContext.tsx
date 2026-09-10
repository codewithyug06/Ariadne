// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  api,
  ApiError,
  onSessionExpired,
  setAccessToken,
  silentRefresh,
  type CurrentUser,
} from '../api/client';

type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

interface AuthContextValue {
  user: CurrentUser | null;
  status: AuthStatus;
  login: (email: string, password: string) => Promise<void>;
  loginWithToken: (token: string) => Promise<void>;
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
    // Goes through client.ts's deduped silentRefresh() rather than a raw
    // fetch: the refresh cookie is single-use/rotated server-side, so an
    // independent, un-deduped refresh call racing against this one would
    // read the same not-yet-rotated cookie and get a legitimate 401 —
    // which used to incorrectly log out an otherwise-valid session.
    let cancelled = false;
    (async () => {
      const ok = await silentRefresh();
      if (!ok) {
        if (!cancelled) setStatus('unauthenticated');
        return;
      }
      try {
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
      loginWithToken: async (token: string) => {
        setAccessToken(token);
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
