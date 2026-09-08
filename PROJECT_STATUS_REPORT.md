# Ariadne — Project Status Report

**As of:** 2026-09-07
**Repo:** `srm hack` — Ariadne Provenance Firewall (AI agent guardrail system)
**Companion doc:** `ARIADNE_SYSTEM_GUIDE.md` (deep-dive on the detection algorithm and a scenario-by-scenario walkthrough of the automation) — this file is the higher-level "what's built, what's proven, what's left" report.

---

## 1. Executive Summary

Ariadne is a working, tested, end-to-end AI-agent guardrail: it sits in front of an agent's tool calls, scores each one for semantic drift from the agent's stated goal, checks it against explicit hard rules, and produces a graded ALLOW/WARN/ESCALATE/BLOCK verdict — with a full audit trail, a live dashboard, and a self-verifying automated test harness proving it actually catches attacks.

**Bottom line:** the core product is complete and verified. 13 major feature milestones shipped across the commit history, 274 automated tests pass, the type checker is clean, and a live automated red-team suite running every 30 minutes confirms the detector is genuinely catching privilege escalation, data exfiltration, and goal-hijacking attempts — not just passing unit tests in isolation. A handful of infrastructure/ops decisions (database choice, one endpoint-cleanup decision) remain before a large-scale production launch; none of them are bugs, and the plan for each is documented.

---

## 2. What Has Been Built (complete feature history)

The project was built in two phases, both complete:

### Phase A — Core platform (foundational)
- **First commit**: base FastAPI backend, core detection pipeline (embedding-based drift scorer, provenance graph, hard/soft enforcement engine).
- **Authentication, RBAC, analytics, alerts, settings, dashboard navigation**: full login system (JWT + rotating refresh cookie), admin/viewer roles, the analytics rollup page, the alerts/HITL queue, the settings page, and the dashboard's overall navigation shell.
- **Multi-tenancy foundation**: every table and route scoped by `organization_id`, so the system is safe to run for more than one customer/org from a single deployment.

### Phase B — The 11-feature expansion (all 11 shipped)
Each of these was built, tested, and verified independently before moving to the next:

1. **Drift Narrative Engine** — deterministic, rule-based plain-English explanations of *why* a score fired (never an LLM call, so it can't crash the enforcement path).
2. **Multi-Dimensional Risk Engine** — five independent 0–100 risk scores (intent, tool, privilege, identity, data) computed per call, combined into a weighted aggregate that can independently drive a BLOCK even when semantic drift alone is low.
3. **Agent Entity** — every session aggregated by `calling_agent_id` into a reputation record (total runs, blocked/escalated counts, EMA-smoothed risk score).
4. **Run Detail UX upgrade** — the full forensic step table, provenance graph, drift chart, risk radar, and report export on the Run Detail page.
5. **Policy Backtesting Engine (+ modal)** — replay a proposed policy/threshold change against real historical traffic before deploying it, see exactly which past incidents would change outcome.
6. **Agent-centric dashboard views** — the Agents list and Agent Detail pages, including a live per-agent trace stream.
7. **Trajectory Store** — a durable, labeled data-flywheel table of every session's full trajectory, for future model retraining/evaluation.
8. **Drift Extrapolation** — forward-projects a session's drift trajectory to warn "this run will cross ESCALATE in ~2 more steps at this rate," gated on fit-quality so it never projects from noise.
9. **Calibration & Versioning** — every scored event stamped with which calibration profile (measured FPR, measured detection rate, dataset, sample size) was active, so a threshold is always traceable to real data.
10. **Contextual Tool Risk** — upgrades the static name-pattern tool-risk baseline with session-history and org-specific context.
11. **Minimum Intervention Finder** — given a real incident, sweeps candidate policy changes and recommends the *smallest* change that would have prevented it without adding new false positives.

**Then a full UI polish pass** (`feat(dashboard): enhance UI components, pages, icons, and styling`) brought every page to its current visual state.

**Then this session's production-readiness pass** (see §4 below) closed out the gap between "feature-complete" and "safe to actually deploy."

---

## 3. Best Results — The Numbers That Matter

| Metric | Result |
|---|---|
| **Automated test suite** | **274 / 274 passing** (177 unit + 97 integration) |
| **Type safety** | `mypy --strict` — **0 errors across 68 source files** |
| **Frontend type safety** | `tsc --noEmit` — **0 errors** |
| **Backend source files** | 75 Python modules under `ariadne/` |
| **Frontend source files** | 29 TypeScript/TSX modules under `dashboard/src/` |
| **Database migrations** | 7 Alembic revisions, fully current, none pending |
| **CI/CD pipeline** | lint (ruff) + strict typecheck + full test suite + dependency audit (pip-audit) + secret scan (gitleaks) + container vulnerability scan (Trivy) + dashboard build — all automated on every change |
| **Live automated red-team suite** | **10/10 scenarios executing correctly** against the real running system, on a 30-minute schedule, with automatic regression alerting |
| **Detection coverage proven live** | Privilege escalation → **BLOCKED**. Data exfiltration (credentials, PII) → **BLOCKED/ESCALATED**. Goal hijacking (amount manipulation, injected instructions) → **ESCALATED/WARNED**. Benign traffic → **ALLOWED, zero false positives** across all 3 benign scenarios. |
| **Session volume processed by the harness** | 138+ real sessions recorded and growing every 30 minutes, fully automatically, no manual intervention |

**What makes these results credible, not just numbers:** the automated harness doesn't simulate a verdict — it opens a real session against Ariadne's real `/mcp` endpoint, replays a real multi-step tool-call sequence, and then queries Ariadne's own audit database to read back what it actually decided. When this harness was found to be silently broken earlier in the project (an n8n workflow bug, unrelated to Ariadne's own code), it was root-caused and fixed rather than papered over — see `ARIADNE_SYSTEM_GUIDE.md` §3.3 for the full story. That fix, and a from-scratch re-verification, both happened in this session.

---

## 4. This Session's Work: Full Production-Readiness Audit + Fixes

A complete live audit was performed — every dashboard page opened in a real browser, every backend route cross-checked against every frontend caller, Docker/CI/secrets/database reviewed, and the n8n automation tested against the live running system. Full detail lives in the plan record; summary here:

### Fixed and verified this session
- **n8n automation was silently failing every scheduled run** (~19 hours of failures) — an unpublished workflow draft plus a dead tunnel. Restarted, republished, and verified with both a manual run and a subsequent automatic scheduled run succeeding on their own.
- **WebSocket authentication hardened** — the live-alert/live-run streams used to carry the JWT access token directly in the URL (a real leak risk via logs/history). Replaced with a short-lived, single-use ticket exchange. Verified live: no credential in the WS URL, old-style requests correctly rejected.
- **A real login-race bug found and fixed** while verifying the above — two independent, un-deduped calls to the single-use refresh endpoint could race on page load, and the loser incorrectly logged out an otherwise-valid session. Fixed by routing through one deduped refresh path. Verified with repeated reloads: zero bounces.
- **Agent live-trace now genuinely agent-scoped** — was silently showing the whole system's traffic on every agent's page; now correctly filtered per agent.
- **Secrets hygiene** — the example environment file no longer ships a real-format JWT secret or a guessable admin password.

### Confirmed already solid (no changes needed)
Dockerfile, production Docker Compose stack (enforced secrets, automatic TLS, resource limits, healthchecks), the full CI/CD pipeline, config validation that hard-fails startup on missing production secrets, rate limiting, structured logging, `/health` and `/metrics` endpoints, and the database migration history.

### Left open — deliberately, as decisions rather than bugs
1. **Database**: currently SQLite (fine for a pilot; a real multi-user production launch should move to Postgres — the path for this is documented and scoped, not yet built).
2. **Two operator scripts** that can mint credentials outside the normal login flow need host-level access restriction (a deployment-process item, not code).
3. **A handful of backend API routes with no current frontend caller** (API-key management, agent create/rename, incident root-cause/blast-radius drilldown) — some are likely intentional API-only surfaces, some may be unfinished UI; needs a product decision on which before further work.

---

## 5. The Dashboard — Every Page, What It's For, and Why

The dashboard is a role-gated (admin/viewer) web app, authenticated via email/password, that renders everything the detection engine (see `ARIADNE_SYSTEM_GUIDE.md` Part 1) is doing in real time.

### Runs (`/`) — the main audit log
Every session Ariadne has ever intercepted: session ID, when it started, its stated mission, how many steps it took, its peak drift score, and its final decision (CLEAN/WARNED/ESCALATED/BLOCKED). Four scoreboard tiles up top (Total Recorded Runs, Blocked Threats, Escalated Approvals, Clean Executions) give the at-a-glance security posture. Filterable and searchable.

### Run Detail (`/runs/:sessionId`)
The full forensic trace of one session — step-by-step drift scores and decisions, a visual provenance graph of causal relationships between steps, a live-updating drift chart, a five-axis risk radar for the worst step, a downloadable compliance report, and a "simulate this policy change against this exact incident" tool.

### Agents (`/agents`) and Agent Detail (`/agents/:agentId`)
Per-agent reputation tracking (not just per-session) — total runs, blocked/escalated counts, average drift, and a smoothed risk score, so you can ask "which of my deployed agents is actually risky" over time. Agent Detail adds a real-time, correctly agent-scoped live trace panel.

### Alerts (`/alerts`)
Full alert history (every ESCALATE/BLOCK ever recorded) plus the live Pending HITL Approvals queue — the literal human-in-the-loop gate that holds money-moving and destructive actions until a person approves them. A live alert banner surfaces new escalations instantly on every page.

### Analytics (`/analytics`)
The 30-day security KPI rollup: session volume, threat intercept rate, HITL escalation rate, clean pass-through rate, a daily volume/verdict trend chart, a decisions-by-action breakdown, and which policy rules are firing most often in practice.

### Policies (`/policies`, admin only)
Full CRUD on the hard policy rules and tool-risk overrides, plus a backtest tool that replays a proposed change against real historical traffic before it goes live — see exactly which past incidents would be newly prevented vs. which clean runs would become new false positives.

### Settings (`/settings`)
Live, no-restart-required control of the drift thresholds (WARN/ESCALATE/BLOCK), plus visibility into the current embedding model, graph backend, fail mode, and a versioned history of calibration profiles (each stamped with the real measured false-positive rate and detection rate it was derived from).

### Account (`/account`) and Team (`/team`, admin only)
Self-service password change; admin-only team member management (invite, remove, reset password).

---

## 6. What Remains for a Full Production Launch

None of the following are bugs — the product works correctly today. They are the difference between "verified and ready for a pilot / demo / single-org deployment" and "ready for large-scale, multi-org, high-uptime production":

1. Move the database from SQLite to Postgres if genuine horizontal scale / high availability is required.
2. Restrict host-level access to the two credential-bypass operator scripts.
3. Decide which of the currently-unused backend API routes should get frontend UI vs. stay intentionally API-only, and act on that decision.

Everything else — the detection engine, the dashboard, the CI/CD pipeline, the security hardening done this session, and the automated proof-of-detection harness — is complete, tested, and verified against the live running system.
