// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useState } from 'react';
import { NavLink, Route, Routes, useLocation } from 'react-router-dom';
import { Landing } from './pages/Landing';
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
import { RequireAuth } from './auth/RequireAuth';
import { usePendingApprovals, useStatus } from './hooks/useRuns';
import { Account } from './pages/Account';
import { Alerts } from './pages/Alerts';
import { Analytics } from './pages/Analytics';
import { AuthCallback } from './pages/AuthCallback';
import { Login } from './pages/Login';
import { Signup } from './pages/Signup';
import { Settings } from './pages/Settings';
import { Team } from './pages/Team';
import {
  Sidebar,
  SidebarBody,
  SidebarLink,
  type SidebarLinkDef,
} from './components/ui/sidebar';
import { ThemeToggle } from './components/ThemeToggle';

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
  const location = useLocation();
  const { data: status } = useStatus();
  const { status: authStatus, user, logout } = useAuth();
  const { data: pending } = usePendingApprovals();
  const pendingCount = pending?.length ?? 0;
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // If visiting /landing or accessing the root while unauthenticated, show the interactive landing page
  const isLanding =
    location.pathname === '/landing' ||
    (location.pathname === '/' && authStatus === 'unauthenticated');

  if (isLanding) {
    return <Landing />;
  }

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

  const navLinks: SidebarLinkDef[] = [
    {
      label: 'Runs',
      href: '/',
      end: true,
      icon: <TerminalIcon size={17} />,
    },
    {
      label: 'Agents',
      href: '/agents',
      icon: <BotIcon size={17} />,
    },
    {
      label: 'Alerts',
      href: '/alerts',
      badge: pendingCount,
      icon: <BellIcon size={17} />,
    },
    {
      label: 'Analytics',
      href: '/analytics',
      icon: <BarChartIcon size={17} />,
    },
  ];

  const adminLinks: SidebarLinkDef[] = [
    {
      label: 'Policies',
      href: '/policies',
      icon: <LockIcon size={17} />,
    },
    {
      label: 'Settings',
      href: '/settings',
      icon: <SettingsIcon size={17} />,
    },
    {
      label: 'Team',
      href: '/team',
      icon: <UsersIcon size={17} />,
    },
  ];

  const isAdmin = user?.role === 'admin';

  return (
    <div className="app">
      {/* ── Topbar ── */}
      <header className="topbar">
        <NavLink to="/" className="brand brand-logo-link" title="Ariadne watches your AI agents and stops anything dangerous before it happens">
          <img
            src="/assets/logo3.png"
            alt="Ariadne — AI Agent Provenance Firewall"
            className="brand-logo-img brand-logo-light"
          />
          <img
            src="/assets/logo3-dark.png"
            alt="Ariadne — AI Agent Provenance Firewall"
            className="brand-logo-img brand-logo-dark"
          />
          <span className="brand-tag">AI SAFETY</span>
        </NavLink>

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

          <NavLink
            to="/landing"
            className="hud-pill"
            title="View Ariadne interactive architecture and threat showcase"
            style={{ textDecoration: 'none', color: 'var(--text-muted)' }}
          >
            <span>Product Tour</span>
          </NavLink>

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

      {/* ── Body: sidebar + content ── */}
      <div className="app-body">
        {authStatus === 'authenticated' && (
          <Sidebar open={sidebarOpen} setOpen={setSidebarOpen}>
            <SidebarBody className="ariadne-sidebar-body">
              {/* Primary & Admin nav links inside scrollable nav container */}
              <div className="ariadne-sidebar-nav">
                <div className="ariadne-sidebar-section">
                  {navLinks.map((link) => (
                    <SidebarLink key={link.href} link={link} />
                  ))}
                </div>

                {/* Admin-only links */}
                {isAdmin && (
                  <>
                    <div className="ariadne-sidebar-divider" />
                    <div className="ariadne-sidebar-section">
                      {adminLinks.map((link) => (
                        <SidebarLink key={link.href} link={link} />
                      ))}
                    </div>
                  </>
                )}

                {/* Non-admin: still show settings */}
                {!isAdmin && (
                  <>
                    <div className="ariadne-sidebar-divider" />
                    <div className="ariadne-sidebar-section">
                      <SidebarLink
                        link={{ label: 'Settings', href: '/settings', icon: <SettingsIcon size={17} /> }}
                      />
                    </div>
                  </>
                )}
              </div>

              {/* Bottom: Light mode & Dark mode toggle */}
              <div className="ariadne-sidebar-footer">
                <ThemeToggle />
              </div>
            </SidebarBody>
          </Sidebar>
        )}

        <main className="content">
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/auth/callback" element={<AuthCallback />} />
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
    </div>
  );
}
