// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import type { UserRole } from '../api/client';
import { useAuth } from './AuthContext';

export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  if (status === 'loading') return <div className="empty">Loading…</div>;
  if (status === 'unauthenticated') return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/** Renders children only for the given role; otherwise renders nothing (not a redirect —
 *  used to hide a nav link or a write control, not to gate an entire page). */
export function RequireRole({ role, children }: { role: UserRole; children: ReactNode }) {
  const { user } = useAuth();
  if (user?.role !== role && !(role === 'viewer' && user?.role === 'admin')) return null;
  return <>{children}</>;
}
