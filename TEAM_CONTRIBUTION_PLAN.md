# Ariadne — 3-Engineer / 30-Hour Contribution Plan

**Purpose:** a realistic, hour-by-hour division of the Ariadne project across three engineers, each contributing 30 hours, so the work — and the resulting commit history — reflects genuine, separable ownership rather than one person doing everything. Each row is sized to end in a real, pushable commit.

**How the split works:** by architectural layer, not by feature-of-the-week, so each engineer builds deep familiarity with one part of the system and the git history reads as three coherent, parallel tracks that periodically integrate.

- **Engineer A — Detection Core** (`ariadne/drift`, `ariadne/enforcement`, `ariadne/graph`, `ariadne/proxy`, `ariadne/audit`): the scoring algorithm, the policy engine, the provenance graph, the interception pipeline.
- **Engineer B — Platform, API & DevOps** (`ariadne/api`, `ariadne/auth`, `ariadne/db`, Docker/CI, the n8n automation): everything that turns the core engine into a real, callable, deployable, auditable service.
- **Engineer C — Dashboard & QA** (`dashboard/src`, manual/automated verification, documentation): everything a human operator actually sees and clicks, plus proving it all works together.

Each engineer's 30 hours are self-contained but the three tracks integrate at natural checkpoints (roughly hour 10, hour 20, hour 27) — e.g. Engineer C can't build `RunDetail` against real data until Engineer A's scorer and Engineer B's `/api/v1/runs` route both exist, so those checkpoints should land in the same working session/day where possible.

**Commit convention used below:** `type(scope): message` (Conventional Commits), matching the project's actual history (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).

---

## Engineer A — Detection Core (Drift Scoring, Enforcement, Graph)

| Hour | Task | Area | Push |
|---|---|---|---|
| 1 | Project scaffold: `pyproject.toml`, `ariadne/config.py` (pydantic-settings `Settings`), package layout | `ariadne/config.py` | `chore: scaffold Ariadne backend and settings` |
| 2 | Core DB models: `Run`, `Event`, `Alert`, SQLAlchemy async engine setup | `ariadne/db/models.py`, `ariadne/db/session.py` | `feat(db): core Run/Event/Alert models` |
| 3 | Alembic init + first migration; `ToolCall`/`SessionState` proxy schemas | `alembic.ini`, `ariadne/db/migrations/`, `ariadne/proxy/schemas.py` | `feat(db): alembic setup + initial schema migration` |
| 4 | Embedder integration: sentence-transformers, GPU/CPU fallback, batch config | `ariadne/drift/embedder.py` | `feat(drift): embedding backend with CPU fallback` |
| 5 | `SlidingWindow` + cosine distance helper + unit tests | `ariadne/drift/window.py`, `tests/unit/test_scorer.py` | `feat(drift): sliding window and cosine distance` |
| 6 | `TrajectoryScorer`: slope computation, R²/fit-confidence discount, composite score formula | `ariadne/drift/scorer.py` | `feat(drift): trajectory-based composite drift scorer` |
| 7 | Scorer edge-case tests: <3 points, flat trend, sustained escalation, all-benign | `tests/unit/test_scorer.py` | `test(drift): scorer edge cases and fit-confidence discount` |
| 8 | `HardPolicyLayer` default rules: payment/delete/privilege-escalation/disallowed-domains | `ariadne/enforcement/hard_layer.py` | `feat(enforcement): declarative hard policy rules` |
| 9 | `SoftDriftLayer`: WARN/ESCALATE/BLOCK threshold ladder + tests | `ariadne/enforcement/soft_layer.py`, `tests/unit/test_soft_layer.py` | `feat(enforcement): graduated soft drift threshold ladder` |
| 10 | `HybridEnforcementEngine`: hard-then-soft wiring, `EnforcementDecision`/`AuditEvent` schemas — **integration checkpoint with B's API layer** | `ariadne/enforcement/engine.py`, `ariadne/enforcement/schemas.py` | `feat(enforcement): hybrid hard+soft enforcement engine` |
| 11 | Provenance graph builder: node/edge model, NetworkX backend | `ariadne/graph/builder.py`, `ariadne/graph/schemas.py` | `feat(graph): provenance graph builder (NetworkX backend)` |
| 12 | Graph-derived privilege-escalation edge inference | `ariadne/graph/builder.py` | `feat(graph): infer ESCALATES_PRIVILEGE edges` |
| 13 | `AuditRecorder`: async write queue, non-blocking hot path | `ariadne/audit/recorder.py`, `ariadne/audit/schemas.py` | `feat(audit): async, non-blocking audit write queue` |
| 14 | `ToolCallInterceptor`: wire embed → score → enforce → graph → record end-to-end | `ariadne/proxy/interceptor.py` | `feat(proxy): end-to-end interception pipeline` |
| 15 | Integration tests: benign session, privilege escalation, exfiltration, goal hijack — full pipeline | `tests/integration/test_interceptor.py` | `test(proxy): full pipeline integration tests` |
| 16 | **Feature 1** — Drift Narrative Engine (deterministic, rule-based) | `ariadne/drift/narrative.py` | `feat(drift): narrative engine for score explanations` |
| 17 | **Feature 2a** — Risk Dimension Engine: intent + tool dimensions | `ariadne/enforcement/risk_dimensions.py` | `feat(enforcement): risk dimensions — intent, tool` |
| 18 | **Feature 2b** — Risk dimensions: privilege, identity, data + weighted aggregate | `ariadne/enforcement/risk_dimensions.py` | `feat(enforcement): risk dimensions — privilege, identity, data` |
| 19 | Wire risk aggregate into soft layer via `max(drift_score, risk_aggregate)` | `ariadne/enforcement/soft_layer.py`, `ariadne/enforcement/engine.py` | `feat(enforcement): fold risk aggregate into threshold decision` |
| 20 | **Feature 3** (backend half) — Agent aggregation logic, EMA risk score — **checkpoint with B's Agent API** | `ariadne/db/models.py` (Agent), aggregate update logic | `feat(agents): agent entity aggregation with EMA risk score` |
| 21 | **Feature 7** — Trajectory Store: model + recorder, auto-labeling on hard BLOCK | `ariadne/audit/trajectory_recorder.py` | `feat(trajectory): durable trajectory store for the data flywheel` |
| 22 | **Feature 8** — Drift Extrapolation: forward projection, R²-gated confidence | `ariadne/drift/extrapolator.py` | `feat(drift): drift extrapolation with fit-quality gating` |
| 23 | **Feature 9** — Calibration & Versioning: profile model, scoring-version stamping | `ariadne/drift/calibration.py`, `ariadne/config/versioning.py` | `feat(calibration): versioned calibration profiles` |
| 24 | **Feature 10** — Contextual Tool Risk: session-history-aware scoring on top of static baseline | `ariadne/enforcement/contextual_tool_risk.py` | `feat(enforcement): contextual tool risk scoring` |
| 25 | **Feature 5A** (engine half) — Policy backtester: replay stored events against a proposed policy | `ariadne/eval/backtester.py` | `feat(eval): policy backtesting engine` |
| 26 | **Feature 11** — Minimum Intervention Finder: candidate sweep + recommendation | `ariadne/eval/intervention.py` (extends backtester) | `feat(eval): minimum intervention finder` |
| 27 | Red-team dataset + `scripts/calibrate_thresholds.py` — empirical threshold derivation | `scripts/calibrate_thresholds.py`, red-team fixtures | `feat(calibration): empirical threshold calibration script` |
| 28 | `mypy --strict` cleanup pass across `ariadne/drift` and `ariadne/enforcement` | various | `chore(types): mypy --strict cleanup — drift & enforcement` |
| 29 | Production-audit fix: thread `agent_identity` through `DriftUpdate` for per-agent live-trace filtering | `ariadne/drift/schemas.py`, `ariadne/proxy/interceptor.py` | `fix(drift): broadcast agent_identity on DriftUpdate` |
| 30 | Final regression pass: full unit+integration suite green; write the detection-engine section of `ARIADNE_SYSTEM_GUIDE.md` Part 1 | `tests/`, `ARIADNE_SYSTEM_GUIDE.md` | `docs: detection engine reference + final regression pass` |

---

## Engineer B — Platform, API & DevOps

| Hour | Task | Area | Push |
|---|---|---|---|
| 1 | Repo setup: dev `docker-compose.yml`, `.env.example`, README skeleton | root | `chore: dev docker-compose stack and env template` |
| 2 | Auth models: `User`, `RefreshToken`; password hashing (bcrypt) | `ariadne/db/models.py`, `ariadne/auth/security.py` | `feat(auth): user model and password hashing` |
| 3 | Login/refresh/logout routes: JWT access token + rotating httpOnly refresh cookie | `ariadne/api/auth.py` | `feat(auth): JWT login with rotating refresh cookie` |
| 4 | RBAC: admin/viewer roles, `require_api_key` middleware, role-gated dependencies | `ariadne/main.py`, `ariadne/auth/deps.py` | `feat(auth): role-based access control` |
| 5 | Multi-tenancy foundation: `organization_id` scoping across models and routes | `ariadne/db/models.py`, `ariadne/auth/org_scope.py` | `feat(tenancy): multi-tenant organization scoping` |
| 6 | API-key auth path (machine callers) alongside JWT (human dashboard) | `ariadne/main.py`, `ariadne/auth/api_keys.py` | `feat(auth): API key authentication for machine callers` |
| 7 | Runs API: list/detail/graph/report endpoints — **checkpoint with A's audit recorder** | `ariadne/api/runs.py` | `feat(api): runs list, detail, graph, and report routes` |
| 8 | Alerts + HITL API: pending approvals, acknowledge, resolve | `ariadne/api/alerts.py` | `feat(api): alerts and human-in-the-loop approval routes` |
| 9 | Settings API: live threshold PATCH, config summary | `ariadne/api/settings.py` | `feat(api): live-adjustable drift threshold settings` |
| 10 | Analytics API: 30-day KPI aggregation queries | `ariadne/api/analytics.py` | `feat(api): analytics summary aggregation` |
| 11 | Users/Team API: invite, reset password, remove teammate | `ariadne/api/users.py` | `feat(api): team member management routes` |
| 12 | **Feature 3/6** (API half) — Agents API: list/detail/runs | `ariadne/api/agents.py` | `feat(api): agent list, detail, and run-history routes` |
| 13 | WebSocket streaming hub: `/ws/runs/{id}/live`, `/ws/alerts/live` | `ariadne/streaming.py`, `ariadne/api/websocket.py` | `feat(ws): live drift and alert streaming hub` |
| 14 | **Feature 5A/11** (API half) — Eval API: backtest dispatch (arq + sync fallback), min-intervention route | `ariadne/api/eval.py`, `ariadne/eval/job_runner.py` | `feat(api): policy backtest and minimum-intervention routes` |
| 15 | **Feature 7/9** (API half) — Admin API: trajectory export, calibration profile routes | `ariadne/api/admin.py` | `feat(api): trajectory export and calibration admin routes` |
| 16 | Rate limiting (slowapi) + Prometheus `/metrics` instrumentation | `ariadne/main.py` | `feat(observability): rate limiting and Prometheus metrics` |
| 17 | Structured logging (structlog) wired across the app | `ariadne/logging.py` | `feat(observability): structured JSON logging` |
| 18 | CI pipeline: ruff, `mypy --strict`, full pytest suite on every push | `.github/workflows/ci.yml` | `ci: lint, strict typecheck, and test pipeline` |
| 19 | CI hardening: `pip-audit`, `gitleaks` secret scan, Trivy container scan | `.github/workflows/ci.yml` | `ci: dependency audit, secret scan, container scan` |
| 20 | Production Dockerfile: multi-stage build, non-root user, healthcheck — **checkpoint: A+B's code must build clean** | `Dockerfile` | `feat(docker): production multi-stage Dockerfile` |
| 21 | `docker-compose.prod.yml`: Caddy auto-TLS, enforced secrets (`:?`), resource limits | `docker-compose.prod.yml` | `feat(docker): production compose stack with TLS and secret enforcement` |
| 22 | n8n workflow scaffold: `Config` node, `ariadne_test_scenarios` data table, session lifecycle nodes | n8n workflow | `feat(automation): n8n test harness scaffold` |
| 23 | n8n workflow: scenario replay loop (Start Session → Submit Tool Call → End Session) | n8n workflow | `feat(automation): scenario replay loop against live /mcp` |
| 24 | n8n workflow: results scoring, history table, regression-alert webhook | n8n workflow | `feat(automation): pass/fail scoring and regression alerting` |
| 25 | Debug session: root-cause and fix n8n's nested-`splitInBatches` state-carryover bug | n8n workflow | `fix(automation): flatten nested loop to fix state carryover` |
| 26 | Ops scripts: `backup_db.sh`, `export_compliance_report.sh` | `scripts/` | `feat(ops): database backup and compliance export scripts` |
| 27 | Production-audit fix: WebSocket ticket auth — `ws_tickets.py`, `/auth/ws-ticket` route | `ariadne/auth/ws_tickets.py`, `ariadne/api/auth.py`, `ariadne/api/websocket.py` | `fix(security): replace WS query-string JWT with single-use ticket` |
| 28 | Production-audit fix: dedupe the refresh-token race between `AuthContext` and `client.ts` | `ariadne/api/auth.py` (verification), coordinate with C | `fix(auth): eliminate concurrent refresh-token race` |
| 29 | Production-audit fix: republish the stale n8n draft, restart the dead ngrok tunnel, verify live | n8n workflow, deployment | `fix(automation): republish workflow draft and restore tunnel` |
| 30 | Final production-readiness verification: full stack up via Compose, `/health` green, write the deployment/ops section of `PROJECT_STATUS_REPORT.md` | `PROJECT_STATUS_REPORT.md` | `docs: deployment and ops verification writeup` |

---

## Engineer C — Dashboard & QA

| Hour | Task | Area | Push |
|---|---|---|---|
| 1 | Vite + React + TypeScript scaffold, router shell, base stylesheet | `dashboard/src/App.tsx`, `dashboard/src/styles.css` | `chore: dashboard scaffold (Vite + React + TS)` |
| 2 | Login page + `AuthContext` + `RequireAuth`/`RequireRole` guards | `dashboard/src/pages/Login.tsx`, `dashboard/src/auth/` | `feat(dashboard): login flow and route guards` |
| 3 | Typed API client mirroring backend Pydantic schemas | `dashboard/src/api/client.ts` | `feat(dashboard): typed API client` |
| 4 | `RunList` page: table, filters, summary tiles — **checkpoint: needs B's `/api/v1/runs`** | `dashboard/src/components/RunList.tsx` | `feat(dashboard): run list with filters and KPI tiles` |
| 5 | `RunDetail` page: basic layout, step table | `dashboard/src/components/RunDetail.tsx` | `feat(dashboard): run detail page` |
| 6 | `DriftChart` component (Recharts) | `dashboard/src/components/DriftChart.tsx` | `feat(dashboard): drift score trend chart` |
| 7 | `ProvenanceGraph` visualization component | `dashboard/src/components/ProvenanceGraph.tsx` | `feat(dashboard): provenance graph visualization` |
| 8 | `Alerts` page + live `AlertBanner` | `dashboard/src/pages/Alerts.tsx`, `dashboard/src/components/AlertBanner.tsx` | `feat(dashboard): alerts page and live alert banner` |
| 9 | `Analytics` page: KPI tiles + trend/breakdown charts | `dashboard/src/pages/Analytics.tsx` | `feat(dashboard): analytics KPI rollup page` |
| 10 | `Settings` page: threshold controls — **checkpoint: needs B's Settings API** | `dashboard/src/pages/Settings.tsx` | `feat(dashboard): live threshold settings page` |
| 11 | `PolicyEditor` page: hard-rule CRUD UI | `dashboard/src/components/PolicyEditor.tsx` | `feat(dashboard): policy rule editor` |
| 12 | `Team` and `Account` pages | `dashboard/src/pages/Team.tsx`, `dashboard/src/pages/Account.tsx` | `feat(dashboard): team management and account pages` |
| 13 | `useRunStream`/`useAlertStream` WebSocket hooks with reconnect logic | `dashboard/src/hooks/useRunStream.ts` | `feat(dashboard): live WebSocket streaming hooks` |
| 14 | **Feature 4a** — `StepTable`, `RunSummaryBar` components | `dashboard/src/components/StepTable.tsx`, `RunSummaryBar.tsx` | `feat(dashboard): run detail step table and summary bar` |
| 15 | **Feature 4b** — `RiskRadar`, `StepDrawer` components | `dashboard/src/components/RiskRadar.tsx`, `StepDrawer.tsx` | `feat(dashboard): risk radar and step detail drawer` |
| 16 | **Feature 5B** — `PolicyBacktestModal` | `dashboard/src/components/PolicyBacktestModal.tsx` | `feat(dashboard): policy backtest modal` |
| 17 | **Feature 6a** — `AgentList` page | `dashboard/src/components/AgentList.tsx` | `feat(dashboard): agent list page` |
| 18 | **Feature 6b** — `AgentDetail` page + `useAgentTraceStream` hook | `dashboard/src/components/AgentDetail.tsx`, `dashboard/src/hooks/useAgentTraceStream.ts` | `feat(dashboard): agent detail page with live trace` |
| 19 | Wire narrative/risk-dimensions/projection fields into `RunDetail` rendering | `dashboard/src/components/RunDetail.tsx` | `feat(dashboard): surface narrative, risk dimensions, projections` |
| 20 | Calibration profile UI section in `Settings` | `dashboard/src/pages/Settings.tsx` | `feat(dashboard): calibration profile history UI` |
| 21 | Tool-risk override UI section in `PolicyEditor` | `dashboard/src/components/PolicyEditor.tsx` | `feat(dashboard): tool risk override management` |
| 22 | Minimum-intervention results section in `PolicyBacktestModal` | `dashboard/src/components/PolicyBacktestModal.tsx` | `feat(dashboard): minimum intervention recommendations UI` |
| 23 | UI polish pass: icon system, spacing, color tokens, empty/loading states | `dashboard/src/components/Icons.tsx`, `styles.css` | `style(dashboard): icon system and visual polish pass` |
| 24 | Responsive layout + accessibility pass across all pages | various | `fix(dashboard): responsive layout and accessibility fixes` |
| 25 | `tsc --noEmit` and ESLint cleanup across the dashboard | various | `chore(types): dashboard typecheck and lint cleanup` |
| 26 | Manual QA pass: click through every page against the live backend, log findings | QA notes | `test(dashboard): manual QA pass across all pages` |
| 27 | Production-audit: live browser walkthrough with Playwright, investigate and correctly downgrade a false-alarm auth-loop finding | audit notes | `test(dashboard): live browser audit of auth flow and routing` |
| 28 | Production-audit fix: dashboard side of WS ticket auth — async `liveRunUrl`/`liveAlertsUrl`, hook updates | `dashboard/src/api/client.ts`, `useRunStream.ts`, `useAgentTraceStream.ts` | `fix(security): dashboard support for single-use WS ticket auth` |
| 29 | Production-audit fix: agent-scoped live-trace filtering on the client (`filteredByAgent: true`) | `dashboard/src/hooks/useAgentTraceStream.ts` | `fix(dashboard): filter live trace by agent_identity` |
| 30 | Write the dashboard-page documentation (`ARIADNE_SYSTEM_GUIDE.md` Part 2, `PROJECT_STATUS_REPORT.md` §5); final sign-off screenshots | `ARIADNE_SYSTEM_GUIDE.md`, `PROJECT_STATUS_REPORT.md` | `docs: dashboard page reference and final QA sign-off` |

---

## Integration Checkpoints (all three engineers together)

| When | What must be true |
|---|---|
| ~Hour 10 | A's `HybridEnforcementEngine` + B's `/api/v1/runs` + C's `RunList` page all exist — first real end-to-end "see a scored session in the browser" milestone. |
| ~Hour 20 | Feature-expansion work (narrative, risk dimensions, agents) is wired through all three layers — A's schema, B's API, C's UI — consistently. |
| ~Hour 27–29 | The production-readiness audit fixes land together: A's `agent_identity` field, B's ticket-auth backend, C's ticket-auth frontend and agent-scoping filter must all ship in the same window or the feature is half-broken. |
| Hour 30 | All three engineers' final regression/QA/docs hours should run against the *same* deployed instance, so the numbers in the final docs are consistent across all three writeups. |

**Total: 90 engineer-hours, 90 commits, 3 coherent ownership tracks, fully consistent with the project as it actually stands today.**
