// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { NavLink, Route, Routes } from 'react-router-dom';
import { AlertBanner } from './components/AlertBanner';
import { PolicyEditor } from './components/PolicyEditor';
import { RunDetail } from './components/RunDetail';
import { RunList } from './components/RunList';
import { useAuth } from './auth/AuthContext';
import { RequireAuth, RequireRole } from './auth/RequireAuth';
import { useStatus } from './hooks/useRuns';
import { Account } from './pages/Account';
import { Alerts } from './pages/Alerts';
import { Analytics } from './pages/Analytics';
import { Login } from './pages/Login';
import { Settings } from './pages/Settings';
import { Team } from './pages/Team';

function TeamRoute() {
  const { user } = useAuth();
  if (user?.role !== 'admin') {
    return <div className="empty">Only admins can manage the team.</div>;
  }
  return <Team />;
}

export function App() {
  const { data: status } = useStatus();
  const { status: authStatus, user, logout } = useAuth();

  if (authStatus === 'loading') {
    return <div className="empty">Loading…</div>;
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          Ariadne<span>causal-provenance firewall</span>
        </div>
        {authStatus === 'authenticated' && (
          <nav className="nav">
            <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
              Runs
            </NavLink>
            <NavLink to="/alerts" className={({ isActive }) => (isActive ? 'active' : '')}>
              Alerts
            </NavLink>
            <NavLink to="/analytics" className={({ isActive }) => (isActive ? 'active' : '')}>
              Analytics
            </NavLink>
            <RequireRole role="admin">
              <NavLink to="/policies" className={({ isActive }) => (isActive ? 'active' : '')}>
                Policies
              </NavLink>
            </RequireRole>
            <NavLink to="/settings" className={({ isActive }) => (isActive ? 'active' : '')}>
              Settings
            </NavLink>
            <RequireRole role="admin">
              <NavLink to="/team" className={({ isActive }) => (isActive ? 'active' : '')}>
                Team
              </NavLink>
            </RequireRole>
          </nav>
        )}
        <div className="status-pills">
          {status ? (
            <>
              <span>{status.active_sessions} active</span>
              <span>·</span>
              <span title="embedding backend">{status.embedder_backend}</span>
              <span>·</span>
              <span title="provenance graph backend">{status.graph_backend}</span>
              <span>·</span>
              <span title="behaviour when Ariadne's own pipeline fails">{status.fail_mode}</span>
              {status.embedder_degraded && (
                <span style={{ color: '#d29922' }} title="semantic scoring is degraded">
                  · degraded embedder
                </span>
              )}
            </>
          ) : (
            <span>connecting…</span>
          )}
          {authStatus === 'authenticated' && (
            <>
              <span>·</span>
              <NavLink to="/account" className="linklike-nav" title={user?.email}>
                {user?.role}
              </NavLink>
              <button className="linklike" onClick={() => void logout()}>
                Sign out
              </button>
            </>
          )}
        </div>
      </header>

      {authStatus === 'authenticated' && <AlertBanner />}

      <main className="content">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <RunList />
              </RequireAuth>
            }
          />
          <Route
            path="/runs/:sessionId"
            element={
              <RequireAuth>
                <RunDetail />
              </RequireAuth>
            }
          />
          <Route
            path="/alerts"
            element={
              <RequireAuth>
                <Alerts />
              </RequireAuth>
            }
          />
          <Route
            path="/analytics"
            element={
              <RequireAuth>
                <Analytics />
              </RequireAuth>
            }
          />
          <Route
            path="/policies"
            element={
              <RequireAuth>
                <PolicyEditor />
              </RequireAuth>
            }
          />
          <Route
            path="/settings"
            element={
              <RequireAuth>
                <Settings />
              </RequireAuth>
            }
          />
          <Route
            path="/account"
            element={
              <RequireAuth>
                <Account />
              </RequireAuth>
            }
          />
          <Route
            path="/team"
            element={
              <RequireAuth>
                <TeamRoute />
              </RequireAuth>
            }
          />
          <Route path="*" element={<div className="empty">Not found.</div>} />
        </Routes>
      </main>
    </div>
  );
}
