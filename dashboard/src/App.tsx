// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { NavLink, Route, Routes } from 'react-router-dom';
import { AgentDetail } from './components/AgentDetail';
import { AgentList } from './components/AgentList';
import { AlertBanner } from './components/AlertBanner';
import { PolicyEditor } from './components/PolicyEditor';
import { RunDetail } from './components/RunDetail';
import { RunList } from './components/RunList';
import {
  ActivityIcon,
  BarChartIcon,
  BellIcon,
  BotIcon,
  LockIcon,
  LogOutIcon,
  SettingsIcon,
  ShieldIcon,
  TerminalIcon,
  UsersIcon,
} from './components/Icons';
import { useAuth } from './auth/AuthContext';
import { RequireAuth, RequireRole } from './auth/RequireAuth';
import { usePendingApprovals, useStatus } from './hooks/useRuns';
import { Account } from './pages/Account';
import { Alerts } from './pages/Alerts';
import { Analytics } from './pages/Analytics';
import { Login } from './pages/Login';
import { Settings } from './pages/Settings';
import { Team } from './pages/Team';

function TeamRoute() {
  const { user } = useAuth();
  if (user?.role !== 'admin') {
    return (
      <div className="card empty">
        <LockIcon size={32} style={{ margin: '0 auto 12px', color: 'var(--text-dim)' }} />
        <div>Only administrators can manage the team.</div>
      </div>
    );
  }
  return <Team />;
}

export function App() {
  const { data: status } = useStatus();
  const { status: authStatus, user, logout } = useAuth();
  const { data: pending } = usePendingApprovals();
  const pendingCount = pending?.length ?? 0;

  if (authStatus === 'loading') {
    return (
      <div className="empty" style={{ paddingTop: '20vh' }}>
        <div className="brand" style={{ justifyContent: 'center', marginBottom: 16 }}>
          <div className="brand-icon">
            <ShieldIcon size={16} />
          </div>
          <span className="brand-title" style={{ fontSize: 18 }}>Ariadne</span>
        </div>
        <div style={{ color: 'var(--text-dim)' }}>Connecting to provenance firewall…</div>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        <NavLink to="/" className="brand" title="Ariadne watches your AI agents and stops anything dangerous before it happens">
          <div className="brand-icon">
            <ShieldIcon size={16} />
          </div>
          <span className="brand-title">Ariadne</span>
          <span className="brand-tag">AI SAFETY</span>
        </NavLink>

        {authStatus === 'authenticated' && (
          <nav className="nav">
            <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
              <TerminalIcon size={15} />
              <span>Runs</span>
            </NavLink>
            <NavLink to="/agents" className={({ isActive }) => (isActive ? 'active' : '')}>
              <BotIcon size={15} />
              <span>Agents</span>
            </NavLink>
            <NavLink to="/alerts" className={({ isActive }) => (isActive ? 'active' : '')}>
              <BellIcon size={15} />
              <span>Alerts</span>
              {pendingCount > 0 && <span className="nav-badge">{pendingCount}</span>}
            </NavLink>
            <NavLink to="/analytics" className={({ isActive }) => (isActive ? 'active' : '')}>
              <BarChartIcon size={15} />
              <span>Analytics</span>
            </NavLink>
            <RequireRole role="admin">
              <NavLink to="/policies" className={({ isActive }) => (isActive ? 'active' : '')}>
                <LockIcon size={15} />
                <span>Policies</span>
              </NavLink>
            </RequireRole>
            <NavLink to="/settings" className={({ isActive }) => (isActive ? 'active' : '')}>
              <SettingsIcon size={15} />
              <span>Settings</span>
            </NavLink>
            <RequireRole role="admin">
              <NavLink to="/team" className={({ isActive }) => (isActive ? 'active' : '')}>
                <UsersIcon size={15} />
                <span>Team</span>
              </NavLink>
            </RequireRole>
          </nav>
        )}

        <div className="status-pills">
          {status ? (
            <div
              className={`hud-pill ${status.active_sessions > 0 ? 'active' : ''}`}
              title="How many agent tasks Ariadne is watching right now"
            >
              <span className={`live-dot ${status.active_sessions > 0 ? 'on' : ''}`} />
              <span>{status.active_sessions} running now</span>
            </div>
          ) : (
            <div className="hud-pill">
              <ActivityIcon size={12} />
              <span>Connecting…</span>
            </div>
          )}

          {authStatus === 'authenticated' && (
            <div className="user-profile-pill">
              <NavLink to="/account" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div className="user-avatar" title={user?.email}>
                  {user?.email?.charAt(0).toUpperCase() || 'U'}
                </div>
                <span style={{ fontSize: 11.5, color: 'var(--text)', fontWeight: 500 }}>
                  {user?.role}
                </span>
              </NavLink>
              <button
                className="linklike"
                onClick={() => void logout()}
                title="Sign out"
                style={{ marginLeft: 4, display: 'flex', alignItems: 'center' }}
              >
                <LogOutIcon size={13} style={{ color: 'var(--text-dim)' }} />
              </button>
            </div>
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
            path="/agents"
            element={
              <RequireAuth>
                <AgentList />
              </RequireAuth>
            }
          />
          <Route
            path="/agents/:agentId"
            element={
              <RequireAuth>
                <AgentDetail />
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
          <Route
            path="*"
            element={
              <div className="card empty">
                <h2>Page Not Found</h2>
                <p style={{ color: 'var(--text-dim)' }}>The requested security route does not exist.</p>
              </div>
            }
          />
        </Routes>
      </main>
    </div>
  );
}
