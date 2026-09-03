// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { NavLink, Route, Routes } from 'react-router-dom';
import { AlertBanner } from './components/AlertBanner';
import { PolicyEditor } from './components/PolicyEditor';
import { RunDetail } from './components/RunDetail';
import { RunList } from './components/RunList';
import { useStatus } from './hooks/useRuns';

export function App() {
  const { data: status } = useStatus();

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          Ariadne<span>causal-provenance firewall</span>
        </div>
        <nav className="nav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
            Runs
          </NavLink>
          <NavLink to="/policies" className={({ isActive }) => (isActive ? 'active' : '')}>
            Policies
          </NavLink>
        </nav>
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
        </div>
      </header>

      <AlertBanner />

      <main className="content">
        <Routes>
          <Route path="/" element={<RunList />} />
          <Route path="/runs/:sessionId" element={<RunDetail />} />
          <Route path="/policies" element={<PolicyEditor />} />
          <Route path="*" element={<div className="empty">Not found.</div>} />
        </Routes>
      </main>
    </div>
  );
}
