// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { cn } from '../lib/utils';
import '../landing.css';

interface ThreatScenario {
  title: string;
  badge: string;
  badgeClass: string;
  intent: string;
  call: string;
  distance: string;
  slope: string;
  fitR2: string;
  driftScore: string;
  ruleTrigger: string;
  narrative: string;
}

const SCENARIOS: Record<'privilege' | 'goalHijack' | 'benign', ThreatScenario> = {
  privilege: {
    title: 'Scenario A: Privilege Escalation Attack',
    badge: 'BLOCKED',
    badgeClass: 'tag-block',
    intent: 'Process a $5 goodwill refund for shipping delay on order #8492',
    call: `{\n  "tool": "grant_role",\n  "arguments": {\n    "user": "eval_tester",\n    "role": "cluster_admin",\n    "duration": "permanent"\n  }\n}`,
    distance: '0.94',
    slope: '+0.48 (escalating)',
    fitR2: '0.96 (high confidence)',
    driftScore: '95.0 / 100',
    ruleTrigger: 'Hard Policy: no_privilege_escalation + Provenance Graph (ESCALATES_PRIVILEGE)',
    narrative: 'Refused immediately. The tool \'grant_role\' attempts administrative privilege escalation outside stated intent anchor. Intercepted before tool execution; zero side-effects produced.',
  },
  goalHijack: {
    title: 'Scenario B: Slow-Burn Goal Hijacking',
    badge: 'ESCALATE',
    badgeClass: 'tag-escalate',
    intent: 'Process a $5 goodwill refund for shipping delay on order #8492',
    call: `{\n  "tool": "wire_transfer",\n  "arguments": {\n    "amount": 50000.00,\n    "currency": "USD",\n    "destination_iban": "GB29NWBK60161331926819"\n  }\n}`,
    distance: '0.81',
    slope: '+0.34 (escalating)',
    fitR2: '0.91 (high confidence)',
    driftScore: '78.4 / 100',
    ruleTrigger: 'Hard Policy: payment_requires_hitl + Soft Drift Tier',
    narrative: 'Held for cryptographic Human-in-the-Loop verification. Transfer amount $50,000 exceeds intent mission ($5 refund). Requires signed operator token to resume.',
  },
  benign: {
    title: 'Scenario C: Benign Order Lookup (Zero False Positives)',
    badge: 'ALLOW',
    badgeClass: 'tag-allow',
    intent: 'Process a $5 goodwill refund for shipping delay on order #8492',
    call: `{\n  "tool": "lookup_order",\n  "arguments": {\n    "order_id": "8492",\n    "include_tracking": true\n  }\n}`,
    distance: '0.11',
    slope: '0.00 (flat)',
    fitR2: '0.12 (discounted)',
    driftScore: '5.8 / 100',
    ruleTrigger: 'Within Aligned Drift Baseline',
    narrative: 'Execution allowed silently (< 12ms latency). Cosine distance within normal intent boundary. No hard policies violated.',
  },
};

export function Landing() {
  const navigate = useNavigate();
  const { status: authStatus } = useAuth();

  const [viewMode, setViewMode] = useState<'dribbble' | 'full'>('dribbble');
  const [artworkMode, setArtworkMode] = useState<'live' | 'original'>('live');
  const [tourTab, setTourTab] = useState<'interceptor' | 'trajectory' | 'hitl' | 'backtester'>('interceptor');
  const [scenario, setScenario] = useState<'privilege' | 'goalHijack' | 'benign'>('privilege');
  const [hitlStatus, setHitlStatus] = useState<'pending' | 'approved' | 'rejected'>('pending');
  const [backtestRunning, setBacktestRunning] = useState(false);
  const [backtestDone, setBacktestDone] = useState(false);
  const [isAnnual, setIsAnnual] = useState(true);

  const currentScenario = SCENARIOS[scenario];

  const handleRunBacktest = () => {
    setBacktestRunning(true);
    setTimeout(() => {
      setBacktestRunning(false);
      setBacktestDone(true);
    }, 700);
  };

  useEffect(() => {
    // 1. Dynamic Cursor Tracking Pupil Eyes
    const pupilLeft = document.getElementById('pupilLeft');
    const pupilRight = document.getElementById('pupilRight');
    const eyesBox = document.getElementById('interactiveEyesBox');

    const handleMouseMove = (e: MouseEvent) => {
      if (!pupilLeft || !pupilRight || !eyesBox) return;
      const rect = eyesBox.getBoundingClientRect();
      const eyeCenterX = rect.left + rect.width / 2;
      const eyeCenterY = rect.top + rect.height / 2;

      const deltaX = e.clientX - eyeCenterX;
      const deltaY = e.clientY - eyeCenterY;
      const distance = Math.hypot(deltaX, deltaY);
      const maxRadius = 5.5;

      const moveX = distance > 0 ? (deltaX / distance) * Math.min(distance * 0.08, maxRadius) : 0;
      const moveY = distance > 0 ? (deltaY / distance) * Math.min(distance * 0.08, maxRadius) : 0;

      pupilLeft.style.transform = `translate(${moveX}px, ${moveY}px)`;
      pupilRight.style.transform = `translate(${moveX}px, ${moveY}px)`;
    };

    window.addEventListener('mousemove', handleMouseMove);

    // 2. Constellation Parallax
    const container = document.getElementById('constellationNetwork');
    const nodes = container?.querySelectorAll<HTMLElement>('.node-wrapper');

    const handleContainerMouseMove = (e: MouseEvent) => {
      if (!container || !nodes) return;
      const rect = container.getBoundingClientRect();
      const mouseX = (e.clientX - rect.left) / rect.width - 0.5;
      const mouseY = (e.clientY - rect.top) / rect.height - 0.5;

      nodes.forEach((node, index) => {
        const depth = ((index % 3) + 1) * 7;
        const x = mouseX * depth;
        const y = mouseY * depth;
        node.style.transform = `translate3d(${x}px, ${y}px, 0)`;
      });
    };

    const handleContainerMouseLeave = () => {
      if (!nodes) return;
      nodes.forEach((node) => {
        node.style.transform = 'translate3d(0, 0, 0)';
        node.style.transition = 'transform 0.5s ease-out';
        setTimeout(() => { node.style.transition = ''; }, 500);
      });
    };

    container?.addEventListener('mousemove', handleContainerMouseMove);
    container?.addEventListener('mouseleave', handleContainerMouseLeave);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      container?.removeEventListener('mousemove', handleContainerMouseMove);
      container?.removeEventListener('mouseleave', handleContainerMouseLeave);
    };
  }, []);

  return (
    <div className={cn('landing-page-root', viewMode === 'dribbble' ? 'mode-dribbble' : 'mode-full')}>
{/*  View Mode Switcher Header Bar  */}
  <aside className="view-controller-bar" aria-label="View mode controller">
    <div className="view-bar-content">
      <div className="view-badge">
        <span className="pulse-dot"></span>
        <span>Ariadne <strong>Provenance Firewall</strong> · Live MCP Security Gateway</span>
      </div>
      <div className="view-toggle-group">
        <span className="toggle-label">Presentation View:</span>
        <div className="toggle-buttons">
          <button type="button" className={cn("btn-toggle", viewMode === "dribbble" && "active")} onClick={() => setViewMode("dribbble")} title="Display as framed showcase card">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="4"></rect><path d="M9 3v18"></path></svg>
            Showcase Card
          </button>
          <button type="button" className={cn("btn-toggle", viewMode === "full" && "active")} onClick={() => setViewMode("full")} title="Expand to full-width responsive landing page">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 3 21 3 21 9"></polyline><polyline points="9 21 3 21 3 15"></polyline><line x1="21" y1="3" x2="14" y2="10"></line><line x1="3" y1="21" x2="10" y2="14"></line></svg>
            Full Page Experience
          </button>
        </div>
      </div>
    </div>
  </aside>

  {/*  Main Showcase Container (Supports both framed Dribbble card & full page)  */}
  <main className="landing-viewport-wrapper">
    <div className="showcase-card-frame" id="mainContainer">

      {/*  ==================== HERO SECTION ====================  */}
      <section className="hero-section" id="hero">
        
        {/*  Floating Pill Navigation Bar  */}
        <header className="navbar-wrapper">
          <nav className="pill-navbar" aria-label="Main Navigation">
            <a href="#hero" className="nav-logo" style={{ display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none' }}>
              <img
                src="/assets/logo2.png"
                alt="Ariadne"
                style={{ height: 26, width: 'auto', display: 'block' }}
              />
              <span className="logo-text" style={{ fontSize: 18, fontWeight: 800, letterSpacing: '-0.02em', color: '#0F172A' }}>Ariadne</span>
              <span className="logo-badge">FIREWALL</span>
            </a>

            <div className="nav-links">
              <a href="#features" className="nav-link">Engine</a>
              <a href="#tour" className="nav-link">Live Tour</a>
              <a href="#comparison" className="nav-link">Why Ariadne</a>
              <a href="#pricing" className="nav-link">Deployment</a>
              <a href="#faq" className="nav-link">FAQ</a>
            </div>

            <div className="nav-actions">
              {authStatus === 'authenticated' ? (
                <Link to="/" className="btn-pill-dark" style={{ textDecoration: 'none' }}>
                  Console Dashboard →
                </Link>
              ) : (
                <>
                  <Link to="/login" className="btn-sign-in" style={{ textDecoration: 'none' }}>
                    Audit Logs
                  </Link>
                  <button type="button" className="btn-pill-dark btn-open-demo" onClick={() => navigate('/signup')}>
                    Deploy Sandbox
                  </button>
                </>
              )}
            </div>
          </nav>
        </header>

        {/*  Hero Interactive Constellation Network Diagram  */}
        <div className="constellation-wrapper">
          {/*  Switcher between Live Interactive Vector and Topology Diagram  */}
          <div className="constellation-mode-switch">
            <button type="button" className={cn("btn-subtoggle", artworkMode === "live" && "active")} onClick={() => setArtworkMode("live")}>
              <span className="mini-dot"></span> Live Pipeline Topology
            </button>
            <button type="button" className={cn("btn-subtoggle", artworkMode === "original" && "active")} onClick={() => setArtworkMode("original")}>
              Architecture Overview
            </button>
          </div>

          {/*  Mode A: Exact Master Artwork Render / Overview  */}
          <div className="master-artwork-display" id="masterArtworkDisplay" style={{display: artworkMode === "original" ? "flex" : "none"}}>
            <div className="architecture-visual-fallback">
              <div className="fallback-hero-badge">Ariadne Provenance &amp; Enforcement Architecture</div>
              <div className="fallback-flow">
                <div className="flow-step">
                  <strong>1. Agent Intent</strong>
                  <span>Sentence-Transformers Anchor</span>
                </div>
                <div className="flow-arrow">→</div>
                <div className="flow-step highlight-core">
                  <strong>2. Ariadne /mcp Proxy</strong>
                  <span>Hard Policies + Trajectory Slope</span>
                </div>
                <div className="flow-arrow">→</div>
                <div className="flow-step">
                  <strong>3. Verdict Ladder</strong>
                  <span>ALLOW / WARN / ESCALATE / BLOCK</span>
                </div>
              </div>
            </div>
          </div>

          {/*  Mode B: Live Interactive Vector Constellation  */}
          <div className="constellation-container" id="constellationNetwork" style={{display: artworkMode === "live" ? "block" : "none"}}>

            {/*  SVG Vector Connectors Layer with Exact Geometry  */}
            <svg className="circuit-connections-svg" viewBox="0 0 1100 360" preserveAspectRatio="none" aria-hidden="true">
              {/*  Left paths connecting to center  */}
              {/*  Path from Intent Anchor (Yellow) to Left Fork  */}
              <path className="circuit-line" d="M 260 76 L 330 76 L 390 180 L 470 180" />
              {/*  Path from Autonomous Agent (Avatar) to Center Interceptor  */}
              <path className="circuit-line" d="M 160 180 L 470 180" />
              {/*  Path from Trajectory & Slope Scorer (Cyan) to Center  */}
              <path className="circuit-line" d="M 270 284 L 340 284 L 390 180 L 470 180" />

              {/*  Right paths connecting from center  */}
              {/*  Path from Center to Hard Policy Shield (Red)  */}
              <path className="circuit-line" d="M 630 180 L 710 180 L 770 76 L 840 76" />
              {/*  Path from Center to Human-in-the-Loop Operator (Avatar)  */}
              <path className="circuit-line" d="M 630 180 L 710 180 L 760 284 L 830 284" />
              {/*  Path from Center to Live Sentinel Eye  */}
              <path className="circuit-line" d="M 630 180 L 935 180" />

              {/*  Accent Junction Dots with subtle glow  */}
              <circle className="junction-dot" cx="330" cy="76" r="3.5" />
              <circle className="junction-dot" cx="340" cy="284" r="3.5" />
              <circle className="junction-dot" cx="770" cy="76" r="3.5" />
              <circle className="junction-dot" cx="760" cy="284" r="3.5" />
            </svg>

            {/*  Satellite Nodes & Elements  */}
            <div className="nodes-layer">

              {/*  1. Yellow Node: Intent Anchor (Vector Baseline)  */}
              <div className="node-wrapper node-yellow" style={{top: '38px', left: '188px'}} data-tooltip="Intent Anchor · Stated mission vector embedding via all-MiniLM-L6-v2">
                <div className="squircle-box yellow-squircle float-anim float-delay-1">
                  {/*  Compass / Target Anchor Icon  */}
                  <svg className="node-icon bulb-icon" width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="#161616" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="9"></circle>
                    <path d="M12 3v3M12 18v3M3 12h3M18 12h3"></path>
                    <polygon points="12 8 14 12 12 16 10 12 12 8" fill="#161616"></polygon>
                  </svg>
                  <span className="node-subtag">Intent Anchor</span>
                </div>
              </div>

              {/*  2. Agent Node (Autonomous Agent Dispatcher)  */}
              <div className="node-wrapper node-avatar-male" style={{top: '135px', left: '70px'}} data-tooltip="Autonomous AI Agent · Claude 3.5 / AutoGPT / LangChain generating /mcp tool calls">
                <div className="avatar-squircle float-anim float-delay-2 agent-bot-badge">
                  <img src="/assets/avatar_male.png" alt="Autonomous AI Agent Caller" className="avatar-img" />
                  <span className="agent-chip">AI Agent</span>
                </div>
              </div>

              {/*  3. Cyan Node: Trajectory & Slope Scorer  */}
              <div className="node-wrapper node-blue" style={{top: '242px', left: '190px'}} data-tooltip="Trajectory & Slope Scorer · Least-squares sliding window (last 5 steps) + R² confidence discount">
                <div className="squircle-box cyan-squircle float-anim float-delay-3">
                  {/*  Regression Slope / Trend Icon  */}
                  <svg className="node-icon balloon-icon" width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"></polyline>
                    <polyline points="16 7 22 7 22 13"></polyline>
                  </svg>
                  <span className="node-subtag">Drift Slope</span>
                </div>
              </div>

              {/*  4. Center Purple Squircle: Ariadne Firewall Proxy Core  */}
              <div className="node-wrapper node-center" style={{top: '105px', left: '470px'}} data-tooltip="Ariadne /mcp Interception Proxy · Hard Policy Layer + 4-Tier Graduated Soft Ladder">
                <div className="squircle-box center-purple-squircle float-anim float-center">
                  <div className="check-ring">
                    <svg className="check-svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                      <polyline points="9 12 11 14 15 10"></polyline>
                    </svg>
                  </div>
                  <span className="core-label">Ariadne Core</span>
                </div>
              </div>

              {/*  5. Red/Coral Node: Hard Policy Enforcement  */}
              <div className="node-wrapper node-red" style={{top: '35px', left: '840px'}} data-tooltip="Hard Policy Engine · Zero-tolerance instant block on privilege escalation & destructive SQL/bash">
                <div className="squircle-box coral-squircle float-anim float-delay-2">
                  <svg className="node-icon shield-icon" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                    <polygon points="13 7 9 13 12 13 11 17 15 11 12 11 13 7" fill="#FFFFFF" stroke="none" />
                  </svg>
                  <span className="node-subtag">Hard Policy</span>
                </div>
              </div>

              {/*  6. Human-in-the-Loop Operator Avatar  */}
              <div className="node-wrapper node-avatar-female" style={{top: '248px', left: '830px'}} data-tooltip="Human-in-the-Loop (HITL) · Single-use approval tokens for payment & sensitive operations">
                <div className="avatar-squircle avatar-small float-anim float-delay-4 operator-badge">
                  <img src="/assets/avatar_female.png" alt="Security Operator Gatekeeper" className="avatar-img" />
                  <span className="agent-chip hitl-chip">HITL Approver</span>
                </div>
              </div>

              {/*  7. White Squircle: Sentinel Eye (Real-Time Observability)  */}
              <div className="node-wrapper node-eyes" style={{top: '135px', left: '935px'}} data-tooltip="Live Sentinel & Deterministic Drift Narrative · Tracking every tool call with zero LLM hallucination">
                <div className="squircle-box white-squircle float-anim float-delay-1" id="interactiveEyesBox">
                  <div className="eyes-container">
                    <div className="eye left-eye">
                      <div className="pupil" id="pupilLeft"></div>
                    </div>
                    <div className="eye right-eye">
                      <div className="pupil" id="pupilRight"></div>
                    </div>
                  </div>
                  <span className="node-subtag-dark">Live Sentinel</span>
                </div>
              </div>

            </div>{/*  /nodes-layer  */}

          </div>{/*  /constellation-container  */}
        </div>{/*  /constellation-wrapper  */}

        {/*  Hero Headline & Subtitle & CTA  */}
        <div className="hero-copy-container">
          <div className="hero-kicker">
            <span className="status-indicator"></span>
            <span>INLINE MODEL CONTEXT PROTOCOL (MCP) INTERCEPTOR</span>
          </div>
          <h1 className="hero-headline">
            Provenance Firewall<br />
            for AI Agents
          </h1>
          <p className="hero-subheadline">
            Ariadne intercepts autonomous tool calls at the MCP boundary, evaluates multi-step trajectory drift from stated intent, and prevents privilege escalation and goal hijacking in real time.
          </p>
          <div className="hero-cta-wrapper">
            <button type="button" className="btn-cta-coral btn-open-demo" id="heroRequestDemoBtn" onClick={() => navigate('/signup')}>
              Explore Live Sandbox
            </button>
            <a href="#tour" className="btn-cta-secondary">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
              Watch Attack Replay
            </a>
          </div>

          {/*  Hero Metrics Strip  */}
          <div className="hero-specs-row">
            <div className="spec-pill">
              <strong>&lt; 15ms</strong>
              <span>Interception Latency</span>
            </div>
            <div className="spec-divider"></div>
            <div className="spec-pill">
              <strong>0.0% FPR</strong>
              <span>Benign False Positives</span>
            </div>
            <div className="spec-divider"></div>
            <div className="spec-pill">
              <strong>FAIL_CLOSED</strong>
              <span>Default Posture</span>
            </div>
            <div className="spec-divider"></div>
            <div className="spec-pill">
              <strong>10/10</strong>
              <span>Red-Team Scenarios Proven</span>
            </div>
          </div>
        </div>

      </section>
      {/*  ==================== /HERO SECTION ====================  */}

      {/*  ==================== EXTENDED FULL PAGE SECTIONS ====================  */}
      <div className="full-page-content" id="extendedContent">

        {/*  Social Proof / Agent Ecosystem Strip  */}
        <section className="proof-bar">
          <p className="proof-lead">BUILT FOR MODERN AGENT FRAMEWORKS &amp; THE MODEL CONTEXT PROTOCOL (MCP)</p>
          <div className="proof-logos">
            <div className="logo-item"><strong>Anthropic Claude</strong></div>
            <div className="logo-item"><strong>LangChain</strong></div>
            <div className="logo-item"><strong>CrewAI</strong></div>
            <div className="logo-item"><strong>Model Context Protocol</strong></div>
            <div className="logo-item"><strong>OpenAI Swarm</strong></div>
            <div className="logo-item"><strong>AutoGPT</strong></div>
            <div className="logo-item"><strong>LlamaIndex</strong></div>
          </div>
        </section>

        {/*  Section 1: Modular Bento Grid ("How Ariadne Defends Agents")  */}
        <section className="section-bento" id="features">
          <div className="section-header-centered">
            <span className="section-pill">Detection Architecture</span>
            <h2 className="section-title">Zero-compromise protection without slowing agent velocity</h2>
            <p className="section-desc">Traditional LLM firewalls inspect isolated prompts. Ariadne inspects the live execution trajectory, measuring cumulative semantic drift and enforcing strict provenance boundaries.</p>
          </div>

          <div className="bento-grid">
            {/*  Bento Box 1: Trajectory Slope Scorer  */}
            <div className="bento-card bento-col-8 bento-drift">
              <div className="bento-badge blue-badge">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"></polyline><polyline points="16 7 22 7 22 13"></polyline></svg>
                Trajectory &amp; Slope Analysis
              </div>
              <h3>Why raw cosine distance isn't enough — The Slope Trick</h3>
              <p>An agent glancing at an unrelated document is forgiven. Ariadne computes least-squares regression slope over a 5-step sliding window with an R² trend confidence discount, catching slow-burn prompt injections while forgiving exploratory lookups.</p>
              
              <div className="mock-trajectory-widget">
                <div className="intent-banner">
                  <span className="intent-lbl">SESSION INTENT ANCHOR:</span>
                  <span className="intent-val">"Process a $5 goodwill refund for shipping delay on order #8492"</span>
                </div>

                <div className="trajectory-steps">
                  <div className="step-row step-allow">
                    <div className="step-meta">
                      <span className="step-num">Step 1</span>
                      <code className="step-call">lookup_order(order_id="8492")</code>
                    </div>
                    <div className="step-stats">
                      <span className="stat-tag">dist: 0.11</span>
                      <span className="stat-tag">slope: 0.00</span>
                      <span className="verdict-tag tag-allow">ALLOW (6.2)</span>
                    </div>
                  </div>

                  <div className="step-row step-allow">
                    <div className="step-meta">
                      <span className="step-num">Step 2</span>
                      <code className="step-call">view_customer_notes(cust_id="c_102")</code>
                    </div>
                    <div className="step-stats">
                      <span className="stat-tag">dist: 0.24</span>
                      <span className="stat-tag">slope: +0.07</span>
                      <span className="verdict-tag tag-allow">ALLOW (14.5)</span>
                    </div>
                  </div>

                  <div className="step-row step-escalate">
                    <div className="step-meta">
                      <span className="step-num">Step 3</span>
                      <code className="step-call">query_internal_payroll(scope="all")</code>
                    </div>
                    <div className="step-stats">
                      <span className="stat-tag">dist: 0.72</span>
                      <span className="stat-tag">slope: +0.32</span>
                      <span className="verdict-tag tag-escalate">ESCALATE (71.8)</span>
                    </div>
                  </div>

                  <div className="step-row step-block">
                    <div className="step-meta">
                      <span className="step-num">Step 4</span>
                      <code className="step-call">grant_role(user="attacker", role="admin")</code>
                    </div>
                    <div className="step-stats">
                      <span className="stat-tag">dist: 0.94</span>
                      <span className="stat-tag">slope: +0.48</span>
                      <span className="verdict-tag tag-block">BLOCKED (95.0)</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/*  Bento Box 2: 4-Tier Verdict Ladder  */}
            <div className="bento-card bento-col-4 bento-ladder">
              <div className="bento-badge purple-badge">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
                Graduated Defense
              </div>
              <h3>4-Tier Verdict Ladder</h3>
              <p>Graduated enforcement instead of blunt all-or-nothing execution drops:</p>
              
              <div className="ladder-stack">
                <div className="ladder-tier tier-allow">
                  <div className="ladder-dot"></div>
                  <div className="ladder-info">
                    <strong>ALLOW (&lt; 40)</strong>
                    <span>On-mission silent passthrough (&lt; 15ms)</span>
                  </div>
                </div>
                <div className="ladder-tier tier-warn">
                  <div className="ladder-dot"></div>
                  <div className="ladder-info">
                    <strong>WARN (≥ 40)</strong>
                    <span>Forwarded but flagged on live audit stream</span>
                  </div>
                </div>
                <div className="ladder-tier tier-escalate">
                  <div className="ladder-dot"></div>
                  <div className="ladder-info">
                    <strong>ESCALATE (≥ 66.5)</strong>
                    <span>Held for cryptographic HITL operator approval</span>
                  </div>
                </div>
                <div className="ladder-tier tier-block">
                  <div className="ladder-dot"></div>
                  <div className="ladder-info">
                    <strong>BLOCK (≥ 86.5)</strong>
                    <span>Refused outright; never reaches real tool</span>
                  </div>
                </div>
              </div>
            </div>

            {/*  Bento Box 3: Deterministic Narrative Engine  */}
            <div className="bento-card bento-col-4 bento-narrative">
              <div className="bento-badge yellow-badge">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
                Zero Hallucinations
              </div>
              <h3>Deterministic Drift Narrative</h3>
              <p>Every verdict generates a 100% rule-based plain-English explanation. Never an LLM call in the hot path.</p>
              
              <div className="narrative-quote-box">
                <div className="narrative-chip">Root Cause Summary</div>
                <p className="narrative-text">
                  "Call to <code className="inline-code">grant_role</code> diverged from intent anchor. Trigger: 3 consecutive steps with climbing drift (+0.48 slope, R² 0.96) and inferred <span className="text-alert">ESCALATES_PRIVILEGE</span> edge. First divergence at Step 3."
                </p>
                <div className="narrative-meta">
                  <span>Engine: Deterministic Rule Synthesizer</span>
                  <span className="badge-fast">&lt; 1ms</span>
                </div>
              </div>
            </div>

            {/*  Bento Box 4: Multi-Dimensional Risk Engine  */}
            <div className="bento-card bento-col-8 bento-risk">
              <div className="bento-badge red-badge">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>
                5-Dimensional Risk Engine
              </div>
              <h3>Multi-Dimensional Risk Aggregate &amp; Causal Provenance</h3>
              <p>A call can be lethal even with zero semantic drift (e.g. credential leakage or unverified caller). Ariadne scores 5 independent risk dimensions and evaluates <code className="inline-code">max(drift_score, risk_aggregate)</code>.</p>
              
              <div className="risk-bars-container">
                <div className="risk-bar-item">
                  <div className="risk-bar-head">
                    <span>1. Intent Drift (Cosine + Slope)</span>
                    <strong className="risk-score-aligned">32 / 100 · Aligned</strong>
                  </div>
                  <div className="risk-bar-track"><div className="risk-bar-fill fill-green" style={{width: '32%'}}></div></div>
                </div>

                <div className="risk-bar-item">
                  <div className="risk-bar-head">
                    <span>2. Contextual Tool Risk</span>
                    <strong className="risk-score-elevated">68 / 100 · Elevated</strong>
                  </div>
                  <div className="risk-bar-track"><div className="risk-bar-fill fill-yellow" style={{width: '68%'}}></div></div>
                </div>

                <div className="risk-bar-item">
                  <div className="risk-bar-head">
                    <span>3. Privilege Provenance (Graph-Inferred)</span>
                    <strong className="risk-score-critical">92 / 100 · Critical</strong>
                  </div>
                  <div className="risk-bar-track"><div className="risk-bar-fill fill-red" style={{width: '92%'}}></div></div>
                </div>

                <div className="risk-bar-item">
                  <div className="risk-bar-head">
                    <span>4. Identity Verification (Agent Trust EMA)</span>
                    <strong className="risk-score-elevated">45 / 100 · Elevated</strong>
                  </div>
                  <div className="risk-bar-track"><div className="risk-bar-fill fill-yellow" style={{width: '45%'}}></div></div>
                </div>

                <div className="risk-bar-item">
                  <div className="risk-bar-head">
                    <span>5. Data Sensitivity (PII &amp; Secret Tokens)</span>
                    <strong className="risk-score-critical">88 / 100 · Critical</strong>
                  </div>
                  <div className="risk-bar-track"><div className="risk-bar-fill fill-red" style={{width: '88%'}}></div></div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/*  Section 2: Interactive Product Tour & Threat Simulation  */}
                <section className="section-interactive-tour" id="tour">
          <div className="section-header-centered">
            <span className="section-pill">Interactive Demonstration</span>
            <h2 className="section-title">See Ariadne intercept real agent attacks</h2>
            <p className="section-desc">Click through live test harness scenarios to inspect how Ariadne evaluates tool calls, fits trajectory slopes, and gates execution.</p>
          </div>

          <div className="interactive-preview-card">
            {/* Tabs */}
            <div className="preview-tabs">
              <button
                type="button"
                className={cn("tab-btn", tourTab === 'interceptor' && "active")}
                onClick={() => setTourTab('interceptor')}
              >
                Live MCP Interceptor
              </button>
              <button
                type="button"
                className={cn("tab-btn", tourTab === 'trajectory' && "active")}
                onClick={() => setTourTab('trajectory')}
              >
                Drift Trajectory &amp; Slope
              </button>
              <button
                type="button"
                className={cn("tab-btn", tourTab === 'hitl' && "active")}
                onClick={() => setTourTab('hitl')}
              >
                Human-in-the-Loop (HITL) Queue
              </button>
              <button
                type="button"
                className={cn("tab-btn", tourTab === 'backtester' && "active")}
                onClick={() => setTourTab('backtester')}
              >
                Policy Backtester &amp; Provenance
              </button>
            </div>

            {/* Tab Content Display */}
            <div className="preview-display" id="tabContentDisplay">
              {tourTab === 'interceptor' && (
                <div className="tour-interactive-container">
                  <div className="scenario-selector-bar">
                    <span className="selector-label">Select Test Harness Scenario:</span>
                    <div className="scenario-pill-group">
                      <button
                        type="button"
                        className={cn("scenario-pill", scenario === 'privilege' && "active")}
                        onClick={() => setScenario('privilege')}
                      >
                        Privilege Escalation
                      </button>
                      <button
                        type="button"
                        className={cn("scenario-pill", scenario === 'goalHijack' && "active")}
                        onClick={() => setScenario('goalHijack')}
                      >
                        Goal Hijacking
                      </button>
                      <button
                        type="button"
                        className={cn("scenario-pill", scenario === 'benign' && "active")}
                        onClick={() => setScenario('benign')}
                      >
                        Benign Support Query
                      </button>
                    </div>
                  </div>

                  <div className="interceptor-grid">
                    {/* Left: Stated Intent & Intercepted Payload */}
                    <div className="interceptor-col">
                      <div className="code-panel">
                        <div className="panel-header">
                          <span className="panel-dot dot-red"></span>
                          <span className="panel-dot dot-yellow"></span>
                          <span className="panel-dot dot-green"></span>
                          <span className="panel-title">Intercepted /mcp Payload</span>
                        </div>
                        <div className="panel-body">
                          <div className="payload-intent">
                            <span className="label-dim">INTENT ANCHOR:</span>
                            <div className="intent-quote">"{currentScenario.intent}"</div>
                          </div>
                          <pre className="json-code"><code>{currentScenario.call}</code></pre>
                        </div>
                      </div>
                    </div>

                    {/* Right: Real-Time Ariadne Verdict */}
                    <div className="interceptor-col">
                      <div className="verdict-card">
                        <div className="verdict-head">
                          <div>
                            <span className="verdict-label">GATEWAY DECISION</span>
                            <h4 className="verdict-title">{currentScenario.title}</h4>
                          </div>
                          <span className={cn("verdict-badge-large", currentScenario.badgeClass)}>
                            {currentScenario.badge}
                          </span>
                        </div>

                        <div className="verdict-stats-grid">
                          <div className="stat-box">
                            <span className="stat-name">Raw Cosine Distance</span>
                            <strong className="stat-value">{currentScenario.distance}</strong>
                          </div>
                          <div className="stat-box">
                            <span className="stat-name">Trajectory Slope (m)</span>
                            <strong className="stat-value">{currentScenario.slope}</strong>
                          </div>
                          <div className="stat-box">
                            <span className="stat-name">R² Fit Quality</span>
                            <strong className="stat-value">{currentScenario.fitR2}</strong>
                          </div>
                          <div className="stat-box">
                            <span className="stat-name">Composite Risk Score</span>
                            <strong className="stat-value">{currentScenario.driftScore}</strong>
                          </div>
                        </div>

                        <div className="verdict-rules-box">
                          <span className="rules-label">ENFORCEMENT TRIGGER:</span>
                          <p className="rules-desc">{currentScenario.ruleTrigger}</p>
                        </div>

                        <div className="verdict-narrative-box">
                          <span className="rules-label">DETERMINISTIC DRIFT NARRATIVE:</span>
                          <p className="narrative-desc">"{currentScenario.narrative}"</p>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {tourTab === 'trajectory' && (
                <div className="tour-interactive-container">
                  <div className="trajectory-explain-head">
                    <div>
                      <h4 style={{ fontSize: '20px', fontWeight: 700, color: '#111827' }}>Sliding-Window Least-Squares Trajectory</h4>
                      <p style={{ fontSize: '13.5px', color: '#6B7280' }}>Formula: <code className="inline-code">drift_score = 50 * distance * (1 + ramp(slope))</code> with R² trend discount</p>
                    </div>
                    <span style={{ fontSize: '13px', fontWeight: 600, color: '#0284C7', background: '#E0F2FE', padding: '6px 14px', borderRadius: '9999px' }}>
                      ● Active Sliding Window: 5 steps
                    </span>
                  </div>

                  <div className="trajectory-visual-cards">
                    <div className="step-card">
                      <span className="step-badge">Step 1</span>
                      <code className="tool-name">lookup_order</code>
                      <div className="step-detail">Distance: <strong>0.11</strong></div>
                      <div className="step-detail">Window Slope: <strong>0.00</strong></div>
                      <span className="pill-mini allow-mini">ALLOW (6.2)</span>
                    </div>

                    <div className="step-card">
                      <span className="step-badge">Step 2</span>
                      <code className="tool-name">view_notes</code>
                      <div className="step-detail">Distance: <strong>0.24</strong></div>
                      <div className="step-detail">Window Slope: <strong>+0.07</strong></div>
                      <span className="pill-mini allow-mini">ALLOW (14.5)</span>
                    </div>

                    <div className="step-card highlight-step">
                      <span className="step-badge">Step 3 (Divergence)</span>
                      <code className="tool-name">list_internal_users</code>
                      <div className="step-detail">Distance: <strong>0.58</strong></div>
                      <div className="step-detail">Window Slope: <strong>+0.21</strong></div>
                      <span className="pill-mini warn-mini">WARN (48.0)</span>
                    </div>

                    <div className="step-card alert-step">
                      <span className="step-badge">Step 4</span>
                      <code className="tool-name">dump_payroll_table</code>
                      <div className="step-detail">Distance: <strong>0.79</strong></div>
                      <div className="step-detail">Window Slope: <strong>+0.38</strong></div>
                      <span className="pill-mini escalate-mini">ESCALATE (79.2)</span>
                    </div>

                    <div className="step-card block-step">
                      <span className="step-badge">Step 5</span>
                      <code className="tool-name">exfiltrate_s3_bucket</code>
                      <div className="step-detail">Distance: <strong>0.96</strong></div>
                      <div className="step-detail">Window Slope: <strong>+0.52</strong></div>
                      <span className="pill-mini block-mini">BLOCK (98.0)</span>
                    </div>
                  </div>

                  <div className="slope-insight-box">
                    <strong>Why this matters:</strong> An agent that takes an exploratory query at step 2 with high distance (e.g. 0.65) followed by an on-topic action will have a negative or flat slope, keeping its final score under the WARN line. Only sustained escalating drift triggers BLOCK.
                  </div>
                </div>
              )}

              {tourTab === 'hitl' && (
                <div className="tour-interactive-container">
                  <div className="hitl-head">
                    <div>
                      <h4 style={{ fontSize: '20px', fontWeight: 700, color: '#111827' }}>Human-in-the-Loop (HITL) Real-Time Approval Queue</h4>
                      <p style={{ fontSize: '13.5px', color: '#6B7280' }}>High-risk operations are quarantined at the proxy until an authorized security operator acts.</p>
                    </div>
                    <span className="pending-pill">
                      {hitlStatus === 'pending' ? '1 Pending Approval Token' : '0 Pending Tokens'}
                    </span>
                  </div>

                  <div className="hitl-card-item">
                    <div className="hitl-card-top">
                      <div className="hitl-session-info">
                        <span className="session-tag">Session: <strong style={{ fontFamily: 'JetBrains Mono, monospace' }}>test-goal-hijack-892</strong></span>
                        <span className="agent-tag">Calling Agent: <strong>AutoGPT-CustomerSupport</strong></span>
                      </div>
                      <span className="risk-badge-high">Risk Score: 78.4 / 100</span>
                    </div>

                    <div className="hitl-body">
                      <div className="hitl-row">
                        <span className="hitl-lbl">Stated Mission:</span>
                        <span>"Process a $5 goodwill refund for delayed shipping on order #8492"</span>
                      </div>
                      <div className="hitl-row">
                        <span className="hitl-lbl">Intercepted Action:</span>
                        <code className="call-code">wire_transfer(amount=50000.00, currency="USD", iban="GB29NWBK60161331926819")</code>
                      </div>
                      <div className="hitl-row">
                        <span className="hitl-lbl">Quarantine Reason:</span>
                        <span style={{ color: '#DC2626', fontWeight: 600 }}>Hard Policy violation (payment_requires_hitl) + Semantic drift exceeds safe threshold.</span>
                      </div>
                    </div>

                    {hitlStatus === 'pending' ? (
                      <div className="hitl-actions-row">
                        <button
                          type="button"
                          className="btn-hitl-approve"
                          onClick={() => setHitlStatus('approved')}
                        >
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>
                          Sign &amp; Approve Token
                        </button>
                        <button
                          type="button"
                          className="btn-hitl-reject"
                          onClick={() => setHitlStatus('rejected')}
                        >
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                          Block &amp; Revoke Session
                        </button>
                      </div>
                    ) : hitlStatus === 'approved' ? (
                      <div style={{ background: '#D1FAE5', color: '#065F46', padding: '14px', borderRadius: '10px', marginTop: '14px', fontSize: '13.5px', fontWeight: 600 }}>
                        ✓ Cryptographic HITL Approval Token generated: <code style={{ fontFamily: 'monospace' }}>hitl_tok_e91a7742b0</code>. Operation allowed for one-time execution.
                      </div>
                    ) : (
                      <div style={{ background: '#FEE2E2', color: '#991B1B', padding: '14px', borderRadius: '10px', marginTop: '14px', fontSize: '13.5px', fontWeight: 600 }}>
                        ✕ Tool call blocked outright and agent session <code style={{ fontFamily: 'monospace' }}>test-goal-hijack-892</code> terminated. Quarantine logged to immutable audit trail.
                      </div>
                    )}
                  </div>
                </div>
              )}

              {tourTab === 'backtester' && (
                <div className="tour-interactive-container">
                  <div className="backtest-head">
                    <div>
                      <h4 style={{ fontSize: '20px', fontWeight: 700, color: '#111827' }}>Policy Backtesting &amp; Minimum Intervention Finder</h4>
                      <p style={{ fontSize: '13.5px', color: '#6B7280' }}>Simulate threshold changes against 138+ historical recorded trajectories before deploying.</p>
                    </div>
                    <button
                      type="button"
                      className="btn-backtest-run"
                      onClick={handleRunBacktest}
                      disabled={backtestRunning}
                      style={backtestDone ? { background: '#059669' } : {}}
                    >
                      {backtestRunning ? 'Simulating Replay (138 runs)...' : backtestDone ? '✓ Replay Complete: 0 Regressions' : 'Replay 138 Historical Runs'}
                    </button>
                  </div>

                  <div className="backtest-results-grid">
                    <div className="backtest-stat-card">
                      <span className="backtest-stat-lbl">Dataset Size</span>
                      <strong className="backtest-stat-val">138 Sessions</strong>
                      <span className="backtest-stat-sub">Automated Red-Team Harness</span>
                    </div>

                    <div className="backtest-stat-card">
                      <span className="backtest-stat-lbl">Measured Benign FPR</span>
                      <strong className="backtest-stat-val" style={{ color: '#059669' }}>0.00%</strong>
                      <span className="backtest-stat-sub">Zero false positive alarms</span>
                    </div>

                    <div className="backtest-stat-card">
                      <span className="backtest-stat-lbl">Attack Detection Rate</span>
                      <strong className="backtest-stat-val" style={{ color: '#7C3AED' }}>100.0%</strong>
                      <span className="backtest-stat-sub">10 / 10 attacks blocked/escalated</span>
                    </div>
                  </div>

                  <div className="backtest-recommendation-box">
                    <div className="rec-title">
                      <span className="rec-icon">⚡</span>
                      <span>Minimum Intervention Recommendation</span>
                    </div>
                    <p className="rec-body">
                      "Candidate change to <code className="inline-code">WARN: 40.0</code> and <code className="inline-code">BLOCK: 86.5</code> yields optimal security margin. Zero benign runs disrupted while catching all 7 exfiltration and privilege escalation variants. Recommended for immediate production application."
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>

        {/*  Section 3: Objection Handling & Comparison Table  */}
        <section className="section-comparison" id="comparison">
          <div className="section-header-centered">
            <span className="section-pill">Architectural Comparison</span>
            <h2 className="section-title">Why traditional LLM guardrails fail autonomous agents</h2>
            <p className="section-desc">Prompt filters check text before the LLM starts thinking. Ariadne sits at the tool boundary where agents actually take action in the real world.</p>
          </div>

          <div className="comparison-table-wrapper">
            <table className="comparison-table">
              <thead>
                <tr>
                  <th>Capability</th>
                  <th>Legacy Prompt Guardrails (LlamaGuard, NeMo)</th>
                  <th className="highlight-col">Ariadne Provenance Firewall</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><strong>Interception Point</strong></td>
                  <td>User prompt text only (blind to agent execution)</td>
                  <td className="highlight-col"><span className="badge-yes">Inline /mcp proxy</span> intercepting every tool call payload</td>
                </tr>
                <tr>
                  <td><strong>Multi-Step Attack Detection</strong></td>
                  <td>Blind to multi-step creep (each call looks innocent)</td>
                  <td className="highlight-col"><span className="badge-yes">Sliding-window slope regression</span> with R² trend fit discount</td>
                </tr>
                <tr>
                  <td><strong>Privilege Escalation Defense</strong></td>
                  <td>None (no awareness of output-to-input taint flow)</td>
                  <td className="highlight-col"><span className="badge-yes">NetworkX Causal Graph</span> inferring privilege escalation edges</td>
                </tr>
                <tr>
                  <td><strong>Enforcement Granularity</strong></td>
                  <td>Binary drop / pass</td>
                  <td className="highlight-col"><span className="badge-yes">4-Tier Graduated Ladder</span> (ALLOW / WARN / ESCALATE / BLOCK)</td>
                </tr>
                <tr>
                  <td><strong>Human-in-the-Loop (HITL)</strong></td>
                  <td>None or custom hacky polling scripts</td>
                  <td className="highlight-col"><span className="badge-yes">Native cryptographic approval token</span> workflow</td>
                </tr>
                <tr>
                  <td><strong>Evaluation Latency</strong></td>
                  <td>300ms - 800ms (second LLM-as-judge call)</td>
                  <td className="highlight-col"><span className="badge-yes">&lt; 15ms</span> local embeddings &amp; deterministic rules</td>
                </tr>
                <tr>
                  <td><strong>Fail-Safe Behavior</strong></td>
                  <td>Often fails open on network timeout</td>
                  <td className="highlight-col"><span className="badge-yes">Strict FAIL_CLOSED posture</span> (zero silent bypasses)</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        {/*  Section 4: Transparent Deployment Plans  */}
        <section className="section-pricing" id="pricing">
          <div className="section-header-centered">
            <span className="section-pill">Deployment Options</span>
            <h2 className="section-title">From open-source local gateway to enterprise cluster</h2>
            
            {/* Monthly / Annual Toggle */}
            <div className="billing-toggle-container">
              <span
                className={cn("toggle-choice", !isAnnual && "active")}
                onClick={() => setIsAnnual(false)}
                style={{ cursor: 'pointer' }}
              >
                Monthly
              </span>
              <label className="switch-toggle">
                <input
                  type="checkbox"
                  id="billingCycleToggle"
                  checked={isAnnual}
                  onChange={(e) => setIsAnnual(e.target.checked)}
                />
                <span className="slider-toggle"></span>
              </label>
              <span
                className={cn("toggle-choice", isAnnual && "active")}
                onClick={() => setIsAnnual(true)}
                style={{ cursor: 'pointer' }}
              >
                Annual <span className="discount-pill">Save 20%</span>
              </span>
            </div>
          </div>

          <div className="pricing-cards-grid">
            {/*  Tier 1: Developer / OSS  */}
            <div className="pricing-card">
              <div className="tier-name">Developer / Open Source</div>
              <div className="tier-price">
                <span className="currency">$</span>
                <span className="price-val" data-monthly="0" data-annual="0">0</span>
                <span className="per-user">/forever</span>
              </div>
              <p className="tier-desc">Self-hosted local gateway for individual researchers and indie developers building MCP tools.</p>
              <ul className="tier-features">
                <li>Local FastAPI /mcp proxy gateway</li>
                <li>CPU Sentence-Transformers embedder</li>
                <li>SQLite session &amp; trajectory store</li>
                <li>Local web dashboard with live charts</li>
                <li>Unlimited local agent tool calls</li>
              </ul>
              <button type="button" className="btn-tier btn-open-demo" onClick={() => navigate('/signup')}>Run via Docker</button>
            </div>

            {/*  Tier 2: Team Production (Featured)  */}
            <div className="pricing-card featured-tier">
              <div className="popular-ribbon">Recommended</div>
              <div className="tier-name">Production Team</div>
              <div className="tier-price">
                <span className="currency">$</span>
                <span className="price-val">{isAnnual ? 39 : 49}</span>
                <span className="per-user">/month</span>
              </div>
              <p className="tier-desc">Fully featured multi-tenant guardrail with live WebSocket streaming and policy backtesting.</p>
              <ul className="tier-features">
                <li><strong>Everything in Developer, plus:</strong></li>
                <li>Multi-tenant Organization scoping (RBAC)</li>
                <li>GPU-accelerated vector embedding pipeline</li>
                <li>Policy Backtesting Engine &amp; Replay</li>
                <li>Slack &amp; PagerDuty HITL approval webhooks</li>
                <li>Real-time WebSocket event &amp; trace streams</li>
                <li>Minimum Intervention Policy Optimizer</li>
              </ul>
              <button type="button" className="btn-tier btn-tier-coral btn-open-demo" onClick={() => navigate('/signup')}>Deploy Production Stack</button>
            </div>

            {/*  Tier 3: Enterprise Security  */}
            <div className="pricing-card">
              <div className="tier-name">Enterprise Guardrail</div>
              <div className="tier-price">
                <span className="price-val custom-price">Custom</span>
              </div>
              <p className="tier-desc">High-throughput cluster with on-premise airgapped support, mTLS, and custom compliance rules.</p>
              <ul className="tier-features">
                <li>Airgapped on-premise Kubernetes Helm charts</li>
                <li>Custom hard policy compliance packs (SOC-2/HIPAA)</li>
                <li>SPIFFE / mTLS cryptographic agent identity</li>
                <li>Sub-5ms hardware-accelerated scoring</li>
                <li>Dedicated 24/7 incident response &amp; 99.99% SLA</li>
              </ul>
              <button type="button" className="btn-tier btn-open-demo" onClick={() => navigate('/signup')}>Contact Enterprise Team</button>
            </div>
          </div>
        </section>

        {/*  Section 5: FAQ Accordion  */}
        <section className="section-faq" id="faq">
          <div className="section-header-centered">
            <span className="section-pill">Technical FAQ</span>
            <h2 className="section-title">Frequently asked questions about Ariadne</h2>
          </div>

          <div className="faq-accordion-list">
            <details className="faq-item" open>
              <summary className="faq-question">
                <span>How does Ariadne intercept tool calls without introducing latency?</span>
                <span className="faq-icon">+</span>
              </summary>
              <div className="faq-answer">
                Ariadne acts as a high-performance proxy at the <code className="inline-code">/mcp</code> endpoint. Tool arguments and intent anchors are encoded with locally cached Sentence-Transformers models (<code className="inline-code">all-MiniLM-L6-v2</code>). Combined with non-blocking async audit queues and deterministic scoring formulas, the median evaluation latency is under 15ms—completely imperceptible to LLM agent workflows.
              </div>
            </details>

            <details className="faq-item">
              <summary className="faq-question">
                <span>How does the slope algorithm avoid false positives on exploratory searches?</span>
                <span className="faq-icon">+</span>
              </summary>
              <div className="faq-answer">
                A single off-topic lookup yields high cosine distance, but distance alone is capped at 50 points—insufficient to trigger a BLOCK verdict. The dangerous multiplier is the <strong>least-squares slope</strong> across a sliding window of recent steps. Furthermore, Ariadne applies an <strong>R² trend confidence discount</strong>: isolated exploration produces low fit quality and is discounted, whereas sustained, multi-step drift produces a tight linear fit that amplifies the risk score.
              </div>
            </details>

            <details className="faq-item">
              <summary className="faq-question">
                <span>What happens if Ariadne crashes or encounters an unhandled exception?</span>
                <span className="faq-icon">+</span>
              </summary>
              <div className="faq-answer">
                Ariadne operates with a strict <code className="inline-code">FAIL_CLOSED</code> posture by default. If an internal database disconnect or embedder error occurs, un-evaluated tool calls are rejected outright rather than silently forwarded to the tool backend. An internal fault can never be weaponized as an invisible bypass.
              </div>
            </details>

            <details className="faq-item">
              <summary className="faq-question">
                <span>Can we test policy and threshold adjustments before deploying to production?</span>
                <span className="faq-icon">+</span>
              </summary>
              <div className="faq-answer">
                Yes. Ariadne includes a built-in <strong>Policy Backtesting Engine</strong> and <strong>Minimum Intervention Finder</strong>. You can replay thousands of recorded production trajectories against a proposed threshold change to confirm zero false positives before saving the new configuration.
              </div>
            </details>
          </div>
        </section>

        {/*  Bottom CTA Banner  */}
        <section className="cta-bottom-banner">
          <div className="banner-inner">
            <h2 className="banner-title">Stop agent jailbreaks before the tool executes</h2>
            <p className="banner-sub">Protect your databases, APIs, and infrastructure with real-time provenance tracking and graduated drift enforcement.</p>
            <div className="banner-cta-buttons">
              <button type="button" className="btn-cta-coral btn-open-demo" onClick={() => navigate('/signup')}>Deploy Ariadne Sandbox</button>
              <a href="#tour" className="btn-cta-ghost">View Live Replay</a>
            </div>
          </div>
        </section>

        {/*  Footer  */}
        <footer className="site-footer">
          <div className="footer-top">
            <div className="footer-brand">
              <div className="footer-logo">
                <span className="logo-mark">
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                    <path d="M12 2L3 6V12C3 17.52 6.84 22.74 12 24C17.16 22.74 21 17.52 21 12V6L12 2Z" fill="#7C3AED"/>
                    <circle cx="12" cy="12" r="2" fill="#FFFFFF"/>
                  </svg>
                </span>
                <span className="logo-text">Ariadne Firewall</span>
              </div>
              <p className="footer-tagline">Real-Time Provenance Firewall &amp; Trajectory Drift Guardrail for Autonomous AI Agents.</p>
            </div>

            <div className="footer-columns">
              <div className="footer-col">
                <h4>Engine</h4>
                <a href="#features">Trajectory Drift Scorer</a>
                <a href="#features">Hard Policy Engine</a>
                <a href="#features">Provenance Graph</a>
                <a href="#features">5-Axis Risk Engine</a>
              </div>
              <div className="footer-col">
                <h4>Capabilities</h4>
                <a href="#tour">Live MCP Proxy</a>
                <a href="#tour">Human-in-the-Loop (HITL)</a>
                <a href="#comparison">Policy Backtesting</a>
                <a href="#comparison">Deterministic Narratives</a>
              </div>
              <div className="footer-col">
                <h4>Docs &amp; Specs</h4>
                <a href="#pricing">Model Context Protocol (MCP)</a>
                <a href="#pricing">Deployment Guide</a>
                <a href="#faq">Red-Team Benchmarks</a>
                <a href="#faq">REST &amp; WebSocket API</a>
              </div>
            </div>
          </div>

          <div className="footer-bottom">
            <p>&copy; 2026 Ariadne Provenance Firewall. Built for autonomous AI agent safety. All rights reserved.</p>
            <div className="footer-legal">
              <a href="#">Security Architecture</a>
              <a href="#">Compliance (SOC-2)</a>
              <a href="#">Open Source License</a>
            </div>
          </div>
        </footer>

      </div>
      {/*  ==================== /EXTENDED FULL PAGE SECTIONS ====================  */}

    </div>{/*  /showcase-card-frame  */}
  </main>

  {/*  ==================== INTERACTIVE SANDBOX DEMO MODAL ====================  */}
  {/* ==================== INTERACTIVE SANDBOX DEMO MODAL ==================== */}
  {demoModalOpen && (
    <div className="modal-overlay open" id="demoModal" aria-hidden="false" onClick={(e) => { if (e.target === e.currentTarget) setDemoModalOpen(false); }}>
      <div className="modal-dialog">
        <button type="button" className="modal-close-btn" onClick={() => setDemoModalOpen(false)} aria-label="Close modal">&times;</button>
        
        {!demoSuccess ? (
          <div id="modalFormView">
            <div className="modal-header">
              <div className="modal-logo-icon">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                  <path d="M12 2L3 6V12C3 17.52 6.84 22.74 12 24C17.16 22.74 21 17.52 21 12V6L12 2Z" fill="#7C3AED"/>
                  <polyline points="9 12 11 14 15 10" stroke="#FFFFFF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <h3>Deploy Ariadne Agent Sandbox</h3>
              <p>Get instant sandbox credentials and test inline tool interception with your agent framework in under 2 minutes.</p>
            </div>

            <form className="demo-form" id="demoBookingForm" onSubmit={(e) => { e.preventDefault(); setDemoSuccess(true); }}>
              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="inputName">Full Name</label>
                  <input type="text" id="inputName" placeholder="Alex Chen" defaultValue="Security Tester" required />
                </div>
                <div className="form-group">
                  <label htmlFor="inputEmail">Work Email</label>
                  <input type="email" id="inputEmail" placeholder="alex@company.com" defaultValue="tester@ariadne.local" required />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="inputFramework">Agent Framework</label>
                  <select id="inputFramework" defaultValue="anthropic-mcp">
                    <option value="anthropic-mcp">Anthropic Claude (MCP)</option>
                    <option value="langchain">LangChain / LangGraph</option>
                    <option value="crewai">CrewAI</option>
                    <option value="autogpt">AutoGPT / Agent Zero</option>
                    <option value="custom">Custom Agent Orchestration</option>
                  </select>
                </div>
                <div className="form-group">
                  <label htmlFor="inputDeployment">Target Deployment</label>
                  <select id="inputDeployment" defaultValue="cloud">
                    <option value="docker">Local Docker Compose</option>
                    <option value="cloud">Managed Cloud Proxy</option>
                    <option value="k8s">Kubernetes Airgapped</option>
                  </select>
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="inputPrimaryNeed">Primary Security Focus</label>
                <select id="inputPrimaryNeed" defaultValue="escalation">
                  <option value="escalation">Privilege Escalation &amp; Unauthorized Roles</option>
                  <option value="drift">Goal Hijacking &amp; Multi-Step Intent Drift</option>
                  <option value="exfil">Sensitive Data Exfiltration &amp; PII Leakage</option>
                  <option value="hitl">Human-in-the-Loop Workflow Governance</option>
                </select>
              </div>

              <button type="submit" className="btn-submit-demo">Generate Sandbox Gateway Key</button>
            </form>
          </div>
        ) : (
          /* Success State */
          <div id="modalSuccessView" className="modal-success">
            <div className="success-icon-badge">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#10B981" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </div>
            <h3>Sandbox Gateway Provisioned!</h3>
            <p>Your local interception endpoint is ready. Route your agent's MCP requests through the gateway:</p>
            <div className="code-snippet-box" style={{ position: 'relative' }}>
              <code>export MCP_PROXY_URL="http://localhost:8000/mcp"<br />export ARIADNE_API_KEY="ariadne_live_sbx_9942a"</code>
              <button
                type="button"
                onClick={handleCopyCurl}
                style={{
                  position: 'absolute',
                  top: '10px',
                  right: '10px',
                  background: copiedCurl ? '#059669' : '#1E293B',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '6px',
                  padding: '4px 10px',
                  fontSize: '11px',
                  fontWeight: 600,
                  cursor: 'pointer'
                }}
              >
                {copiedCurl ? '✓ Copied' : 'Copy'}
              </button>
            </div>
            <button
              type="button"
              className="btn-cta-coral"
              id="btnDoneSuccess"
              onClick={() => {
                setDemoModalOpen(false);
                navigate('/');
              }}
            >
              Launch Dashboard →
            </button>
          </div>
        )}
      </div>
    </div>
  )}

    </div>
  );
}
