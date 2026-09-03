<!-- Copyright 2026 The Ariadne Authors
     SPDX-License-Identifier: Apache-2.0 -->

# Ariadne

Ariadne is an MCP-compatible middleware proxy that sits between an agent
orchestrator and the tool server it calls. It embeds the user's original
request once as an *intent anchor*, then scores every subsequent tool call
against it — not by raw distance, but by the **slope of that distance over a
sliding window**. It records what happened as a causal provenance graph, applies
declarative policy rules alongside the drift score, and blocks, escalates, or
allows each action before it reaches the real tool. Every decision is written to
an audit trail that exports as a compliance report.

The problem it addresses: indirect prompt injection, memory poisoning, and
hallucination cascades unfold as sequences of individually plausible steps. A
per-step similarity filter either misses them or, tuned tight enough to catch
them, blocks most legitimate work. Measured on the bundled suite, a naive
per-step cosine filter catches every attack — and flags 3 of 4 benign runs
doing it.

| | Ariadne | Naive per-step cosine |
| --- | --- | --- |
| Detection rate | 100% | 100% |
| **False positive rate** | **0%** | **75%** |
| Root-cause localisation | 100% | 0% (no graph) |
| Mean steps to detection | 3.8 | 1.5 |

Eight scenarios is a smoke test, not a benchmark — see [`eval/README.md`](eval/README.md)
for the caveats and for adapters that run AgentDojo and InjecAgent.

## Architecture

```
   ┌──────────────┐   MCP/JSON-RPC    ┌──────────────────────────────┐   MCP    ┌───────────┐
   │ Orchestrator │ ────────────────► │           ARIADNE            │ ───────► │  Real MCP │
   │  LangGraph   │                   │                              │          │   tools   │
   │  CrewAI      │ ◄──────────────── │  ┌────────────────────────┐  │ ◄─────── └───────────┘
   │  AutoGen     │  result / BLOCK   │  │ 1. Intent anchor       │  │
   └──────────────┘                   │  │    embed once/session  │  │
                                      │  ├────────────────────────┤  │
                                      │  │ 2. Action embedder     │  │
                                      │  │    MiniLM, GPU or CPU  │  │
                                      │  ├────────────────────────┤  │
                                      │  │ 3. Trajectory scorer   │  │
                                      │  │    slope over window   │  │
                                      │  ├────────────────────────┤  │
                                      │  │ 4. Provenance graph    │  │
                                      │  │    caused_by, informed │  │
                                      │  │    _by, contradicts,   │  │
                                      │  │    escalates_privilege │  │
                                      │  ├────────────────────────┤  │
                                      │  │ 5. Enforcement engine  │  │
                                      │  │    hard rules first,   │  │
                                      │  │    then drift score    │  │
                                      │  └───────────┬────────────┘  │
                                      └──────────────┼───────────────┘
                                                     │
                        ┌────────────────────────────┼────────────────────────────┐
                        ▼                            ▼                            ▼
                 ┌─────────────┐            ┌────────────────┐          ┌──────────────────┐
                 │ Audit trail │            │  WS live feed  │          │  HITL webhook    │
                 │ SQLite/PG   │            │  → dashboard   │          │  approve / deny  │
                 └─────────────┘            └────────────────┘          └──────────────────┘
```

Per tool call, the decision is one of:

| | Behaviour |
| --- | --- |
| **ALLOW** | Forwarded unchanged. |
| **WARN** | Forwarded, annotated with an `X-Ariadne-Warning` header. |
| **ESCALATE** | Held. POSTed to the HITL webhook; approved within the timeout it proceeds, otherwise it is denied. |
| **BLOCK** | Never forwarded. A JSON-RPC error carrying the reason goes back to the agent. |

If Ariadne's own pipeline raises, `FAIL_MODE` decides: `FAIL_CLOSED` (default)
blocks, `FAIL_OPEN` forwards unscored. Both paths are logged and tested.

## How the scoring works

Three properties matter more than the exact formula:

**1. Slope, not distance.** Distance alone tops out at 50 of 100 points, so a
single off-mission step can never reach the BLOCK threshold on its own. A hard
stop requires a *trend*. This is what lets a research agent read an unrelated
document without being blocked.

**2. Slope amplifies distance; it does not add to it.**

```
drift_score = 50 · distance · (1 + ramp(slope))     ramp(s) = 2·max(0, σ(g·s) − ½)
```

An escalating trajectory only counts insofar as it escalates *away from the
mission*. An agent whose steps climb steadily while staying close to the user's
intent is making progress, not drifting — and an additive term scores that
identically to a real attack.

**3. A trend must look like a trend.** The fitted slope is discounted by how
full the window is and by the fit quality (R²). Below R² ≈ 0.70 the points do
not describe a line, so the "slope" is one outlier rather than an escalation.
On the bundled suite, benign lateral exploration fits at ~0.69 and sustained
injections at ~0.96 — the boundary sits between them because that is where the
measurement put it, not because it was chosen in advance.

Hard rules run *first* and short-circuit. An attacker who keeps every step
semantically on-mission still cannot wire money without human approval, and an
action that contradicts a prohibition the user stated explicitly is blocked
outright — no score can argue it down.

## Quick start

```bash
git clone <your-fork> ariadne && cd ariadne
cp .env.example .env
bash scripts/start_dev.sh
```

That brings up the proxy on `:8000` and the dashboard on `:5173`. First run
also needs the Python and Node dependencies:

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
uv pip install sentence-transformers torch   # semantic embeddings (see GPU note)
cd dashboard && npm install && cd ..
```

To see it working immediately, with a mock tool server and two scripted runs —
one clean, one a slow-burn injection:

```bash
python scripts/demo_agent.py
```

```
attack session demo-attack-37ac865d
  1. read_file              drift  23.8  ALLOW
  2. extract_text           drift  34.1  ALLOW
  3. read_file              drift  83.0  ESCALATE
  4. list_users             drift  38.1  ALLOW
  5. add_user_to_group      drift  49.3  BLOCK
     run halted by Ariadne
```

### GPU

Ariadne targets a single machine with an **RTX 4050 Laptop (6 GB VRAM)**.
`EMBEDDING_BATCH_SIZE` defaults to 32 and CUDA runs fp16, which keeps MiniLM
batches well inside 6 GB alongside a co-located LLM. The default install pulls
CPU wheels; for GPU:

```bash
uv pip install torch --index-url https://download.pytorch.org/whl/cu124
ariadne check     # prints the resolved device and confirms CUDA
```

CPU is entirely adequate for live proxying — a single tool call encodes in a
few milliseconds. The GPU matters for batch evaluation.

## Connecting your agent

Point your MCP client at `http://localhost:8000/mcp` and pass the user's
request in the `initialize` params so drift can be scored against it. Without
it, hard policy still applies but there is no anchor to measure against, and
Ariadne logs a warning saying so.

```python
import httpx

ARIADNE = "http://localhost:8000/mcp"
headers = {"X-Ariadne-Session-Id": "session-abc123"}

async with httpx.AsyncClient() as client:
    # 1. Handshake — this is where the intent anchor is built.
    await client.post(ARIADNE, headers=headers, json={
        "jsonrpc": "2.0", "id": 0, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "userRequest": "Summarise the Q3 sales report. Do not send emails.",
            "capabilities": {"tools": ["read_file", "summarize_text"]},
        },
    })

    # 2. Every tool call now flows through the interception pipeline.
    response = await client.post(ARIADNE, headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "read_file", "arguments": {"path": "/reports/q3.pdf"}},
    })

    decision = response.headers["X-Ariadne-Decision"]   # ALLOW | WARN | ESCALATE | BLOCK
    if "error" in response.json():
        ...  # blocked; error.data.ariadne carries the reason, score and node id

    # 3. Close the session to write its audit summary.
    await client.post(f"http://localhost:8000/mcp/sessions/session-abc123/end")
```

With LangGraph, wire this as the MCP endpoint your `MultiServerMCPClient`
targets — Ariadne speaks the same JSON-RPC, so no agent code changes beyond the
URL and the two extra fields above.

`capabilities.tools` is the set of tools the session is legitimately granted;
listing one there suppresses the privilege-escalation heuristic for it.

## Configuring policies

Two interchangeable backends:

**Built-in (default).** No external service. Rules live in
`ariadne/enforcement/hard_layer.py` and are editable at runtime through the
dashboard's Policies tab or the API:

```bash
curl -X POST localhost:8000/api/v1/policies -H 'Content-Type: application/json' -d '{
  "name": "no_external_uploads",
  "description": "This deployment never uploads to third-party storage.",
  "action": "BLOCK",
  "tool_name_patterns": ["upload_to_", "publish_"],
  "argument_patterns": [],
  "requires_hitl_token": false
}'
```

Rules added this way are persisted and re-applied at startup.

**OPA.** Set `OPA_URL` and the Rego policy becomes authoritative:

```bash
opa run --server --addr :8181 ariadne/enforcement/policies/
export OPA_URL=http://localhost:8181
```

`policies/default.rego` mirrors the built-in rules one-for-one; see
`policies/examples/healthcare.rego` for a domain policy that keys off data
content and calling-agent identity. If OPA becomes unreachable, Ariadne logs
the failure and falls back to the built-in rules rather than failing open.

Default rules: `payment_requires_hitl`, `no_delete_without_confirmation`,
`no_privilege_escalation`, `max_tool_calls_per_session`, `disallowed_domains`,
plus `contradicts_user_intent`, which fires when an action breaches a
prohibition stated in the user's own request.

## Running the red-team evaluation

```bash
bash scripts/run_red_team.sh
```

Runs the scenario assertions, then prints the metrics table comparing Ariadne
against the naive baseline. Four attacks (slow-burn injection, goal hijack,
privilege escalation, memory poisoning) and four benign controls, two of them
deliberately awkward. Details and external benchmark adapters:
[`eval/README.md`](eval/README.md).

## Exporting a compliance report

```bash
bash scripts/export_compliance_report.sh                # most recent run
bash scripts/export_compliance_report.sh <session-id>   # a specific run
ariadne report <session-id> --format markdown
```

Or from the dashboard's run view, or `GET /api/v1/runs/{id}/report?format=markdown`.

The report contains the run metadata, the intent anchor, the full drift curve,
every enforcement decision with its reason, a root-cause analysis for each
blocked action, and a mapping onto EU AI Act Articles 9 (risk management), 13
(transparency) and 14 (human oversight).

**Scope:** the report is *evidence* supporting those obligations. It does not
make a deployment compliant, and it says so on its face. Treat it as an input
to a conformity assessment, not a substitute for one.

## API

Interactive docs at `http://localhost:8000/docs`.

| Endpoint | Purpose |
| --- | --- |
| `POST /mcp` | The intercepted MCP endpoint. Point your agent here. |
| `POST /mcp/hitl/{approval_id}` | Resolve a pending escalation. |
| `POST /mcp/sessions/{id}/end` | Close a session, write its summary. |
| `GET /api/v1/runs` | Paginated run list. |
| `GET /api/v1/runs/{id}` | Run detail with every event. |
| `GET /api/v1/runs/{id}/graph` | Provenance graph, with the root cause resolved. |
| `GET /api/v1/runs/{id}/root-cause?node_id=` | Backward blame chain. |
| `GET /api/v1/runs/{id}/blast-radius?node_id=` | Forward reachability. |
| `GET /api/v1/runs/{id}/report` | Compliance report (`json` \| `markdown`). |
| `GET/POST/DELETE /api/v1/policies` | Hard rule management. |
| `WS /ws/runs/{id}/live` | Live drift stream, replays buffered history on connect. |
| `WS /ws/alerts/live` | ESCALATE/BLOCK across all sessions. |
| `GET /health`, `/status`, `/metrics` | Liveness, active backends, Prometheus. |

`/status` is worth knowing about: the graph store and policy engine both fall
back silently by design, and it is how you confirm which one is actually live.

## Docker

```bash
docker compose up --build                  # proxy + ArcadeDB + dashboard
docker compose --profile gpu up ariadne-gpu arcadedb dashboard
```

Multi-stage build, non-root user, healthchecks on both services. One worker by
default — the embedding model is held in-process, so scale with replicas rather
than workers.

## Production deployment

`docker-compose.yml` is the development stack: default credentials, no
authentication, single-node. `docker-compose.prod.yml` is the hardened
production stack — use it, not the dev file, for anything reachable outside
your own machine.

```bash
cp .env.example .env.prod   # fill in every value below — the stack refuses
                             # to start with any of them missing
docker compose -f docker-compose.prod.yml --env-file .env.prod up --build -d
```

Required in `.env.prod` (each is a hard `${VAR:?...}` in the compose file —
missing any one aborts startup rather than running with a silent default):

| Variable | Why it's required |
| --- | --- |
| `ARIADNE_API_KEYS` | Comma-separated bearer tokens. Every route except `/health` and `/metrics` returns 401 without one — generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. `ARIADNE_ENV=production` refuses to boot with this empty. |
| `ARCADEDB_PASSWORD` | No baked-in password, unlike the dev compose file. |
| `UPSTREAM_MCP_URL`, `HITL_WEBHOOK_URL`, `CORS_ORIGINS`, `ARIADNE_PUBLIC_API_URL` | Deployment-specific; there is no safe default. |

What the production stack adds over dev: API-key auth on every proxied/API
route (`ariadne/main.py`'s `require_api_key` middleware, constant-time
comparison), an OPA container serving the real `policies/default.rego` (not
just the built-in Python mirror), per-service CPU/memory limits, JSON-file log
rotation, `no-new-privileges`, and health-gated startup ordering. Verified live
in this environment: ArcadeDB reports `(healthy)` via its own `/api/v1/ready`
check and OPA serves the real policy at `/v1/data/ariadne/allow` (confirmed
`{"allow": false}` for a `grant_role` call, matching `no_privilege_escalation`).

An optional `ollama` service is defined under the `llm` profile
(`--profile llm up`) for the intent decomposer; it requests the RTX 4050 via
an NVIDIA device reservation. On Windows, GPU passthrough to Docker Desktop's
Linux containers needs WSL2 GPU support configured separately — running Ollama
natively on the host (as this environment does — see below) avoids that
entirely and is what's actually verified.

### Running Ollama on the host instead of in Docker

On a disk-constrained Windows host, keep the Ollama app on `C:` but redirect
model storage (`mistral:7b-instruct` is ~4.1 GB) to a drive with room:

```bash
OLLAMA_MODELS=D:\OllamaModels ollama serve
ollama pull mistral:7b-instruct
```

Then point Ariadne at it: `OLLAMA_URL=http://localhost:11434`,
`OLLAMA_MODEL=mistral:7b-instruct`. Without a reachable Ollama, the intent
decomposer falls back to its heuristic (regex) path automatically — this is
the tested default and a perfectly viable production choice; the LLM path
only improves goal/constraint extraction quality, it isn't required for
detection to work.

### TLS / HTTPS

`docker-compose.prod.yml` includes a `proxy` service (Caddy) that is the
*only* container with a published port — `ariadne` and `dashboard` stay bound
to `127.0.0.1` and are unreachable from outside the host. Caddy terminates
HTTPS and auto-provisions/renews Let's Encrypt certificates with zero manual
cert management, driven by the `Caddyfile` at the repo root.

```bash
# In .env.prod:
ARIADNE_DOMAIN=ariadne.yourcompany.com
DASHBOARD_DOMAIN=dashboard.yourcompany.com
```

Both domains must resolve to this host, and ports 80/443 must be reachable
for the ACME HTTP-01 challenge. Adds HSTS, `X-Content-Type-Options`, and
`X-Frame-Options` headers on every response.

### Rate limiting

Every route is rate-limited per API key (or per client IP, if unauthenticated
in dev mode) via `slowapi` — `RATE_LIMIT_PER_MINUTE` in `.env` (default 120).
A leaked or compromised key gets throttled rather than able to hammer the
embedder or upstream tool server unbounded. Exceeding the limit returns
`429 Too Many Requests`.

### Backups and restore

```bash
./scripts/backup_db.sh                 # backs up ./data/ariadne.db → ./backups/
```

Uses SQLite's online backup API (`sqlite3 .backup`), not a file copy — safe
to run against a live database with the app still writing, since a plain
`cp` mid-write under WAL mode can capture torn state. Prunes backups older
than `RETENTION_DAYS` (default 14). Restore by stopping the `ariadne`
container, replacing `data/ariadne.db` with a decompressed backup, and
restarting. Run on a schedule via cron or a systemd timer.

### Scaling past one instance

SQLite has a single writer, so multiple Ariadne replicas need a real
database server. The audit schema (`ariadne/db/models.py`) uses only generic
SQLAlchemy types (`JSON`, not a SQLite-specific one), so switching is a
`DATABASE_URL` change, not a schema migration:

```bash
uv sync --extra postgres
DATABASE_URL=postgresql+asyncpg://user:pass@host/ariadne alembic upgrade head
```

The embedding model is held in-process per replica — scale with container
replicas behind the Caddy/load-balancer tier, not with `uvicorn --workers`
(each worker would load its own copy of the model).

### CI/CD

`.github/workflows/ci.yml` runs on every push and PR: `ruff`, `mypy --strict`,
the full test suite, a `pip-audit` dependency vulnerability scan, a
`gitleaks` secret scan, a `trivy` scan of the built Docker image (fails on
CRITICAL/HIGH CVEs), and the dashboard's `tsc`/production build.

## Empirical threshold calibration

The 40/65/85 WARN/ESCALATE/BLOCK defaults were originally hand-tuned against
eight red-team scenarios. `scripts/calibrate_thresholds.py` checks that
against real attack data instead of guessing: it runs every InjecAgent
direct-harm and data-stealing case (real MiniLM embeddings, real scorer, real
graph) alongside Ariadne's four benign controls, records each scenario's peak
drift score, and grid-searches the ESCALATE/BLOCK cutoff that maximises
detection subject to a false-positive ceiling.

```bash
uv run python scripts/calibrate_thresholds.py --limit 40 --max-fpr 0.25
```

Result on 164 real scenarios (160 InjecAgent attacks, 4 benign controls): the
highest benign score was 62.0 (`control_lateral_research` — deliberately
awkward, wide-ranging research). The current ESCALATE=65 sits just above that
with 0% measured false positives and ~76% detection; pushing to the
data-optimal 63 only gains ~2 points of detection while eating into the
safety margin on the one real benign signal we have. **Conclusion: the
existing defaults are already near-optimal for this data — kept unchanged.**
Full per-scenario scores are in `threshold_calibration.json`.

## Embedder fine-tuning (negative result, documented honestly)

`scripts/finetune_embedder.py` fine-tunes `all-MiniLM-L6-v2` with triplet loss
on 1,792 real (anchor, positive, negative) triples built directly from
InjecAgent — anchor is the user's instruction, positive is the tool call they
actually asked for, negative is the attacker's tool call from the same case.

```bash
uv run python scripts/finetune_embedder.py --epochs 3 --output models/ariadne-embedder-v1
```

Measured result: **no detection improvement.** InjecAgent direct-harm
detection stayed at 11/15 before and after (two cases flipped in opposite
directions, net zero), and triplet-ranking accuracy was already 1.000 before
training — the frozen base model already ranks the correct action closer than
the attacker's for every triplet in this construction. Training loss collapsed
to ~0 almost immediately, which is the signature of a task that's too easy for
the loss to teach anything new: because the positive text is built from the
user's own tool call, it shares vocabulary with the anchor, so ranking
accuracy is easy to max out without moving the actual score-relevant geometry
(absolute cosine separation, not just relative order).

The model is left in place as a working, reproducible local artifact under
`models/ariadne-embedder-v1/` (gitignored — regenerate with the command
above, don't commit it) but **is not the default** — `EMBEDDING_MODEL`
still points at the stock hub model, because there's no measured evidence the
fine-tuned one is better and real evidence it's a wash. The honest next step
for anyone picking this up: rebuild the triplet set with positives that don't
lexically echo the anchor (e.g. paraphrase or use a different real user_tool
call from an unrelated case as a harder positive), and/or switch to
`MultipleNegativesRankingLoss` with in-batch negatives for more gradient
signal per step than one explicit triplet at a time.

## Development

```bash
pytest tests/unit tests/integration -q     # 141 tests
mypy --strict ariadne                      # clean across 41 files
ruff check ariadne eval tests scripts
cd dashboard && npx tsc --noEmit && npm run build
```

Unit and integration tests use a deterministic stand-in embedder so they run
offline in seconds; `--real-embedder` exercises the sentence-transformers path.
The red-team suite always uses the real model — a detection test against stubbed
embeddings proves nothing.

The three cases in `tests/unit/test_scorer.py::TestCoreBehaviouralSpec` are the
behavioural contract. If they regress, the detection thesis is broken regardless
of what else passes.

## Deliberate deviations from the original spec

1. **uv instead of Poetry**, with an adapted Dockerfile. Same lockfile guarantees.
2. **RTX 4050 (6 GB)**, not 5070 Ti: batch size 32, fp16 on CUDA.
3. **`sentence-transformers`/`torch`, `arcadedb-python` and `opa-python-client`
   are optional extras.** All three have real in-process fallbacks, so none is
   an import-time requirement. The embedder falls back to deterministic feature
   hashing — a genuine embedding, not a stub, though without semantic
   generalisation — and says so loudly in the logs and on `/status`.
4. **The composite score is multiplicative, and the slope term is recentred**
   (see *How the scoring works*). The spec's additive `50·d + 50·σ(10·s)` puts
   a 25-point floor under every action, because σ(0) = ½; measured against real
   MiniLM embeddings that floor was the single largest source of false
   positives, pushing ordinary on-mission calls into WARN. Both spec invariants
   still hold, more strictly than before: distance alone cannot reach BLOCK,
   and slope alone scores nothing.
5. **Slope confidence weighting** (window fill × trend fit) is an addition, not
   in the spec. Without it a lone lateral step is numerically indistinguishable
   from step three of an escalation.
6. **`DRIFT_SLOPE_THRESHOLD` defaults to 0.04**, not 0.08, tuned against
   measured MiniLM geometry. It is now the half-power point of the slope ramp,
   so the knob has a defined meaning rather than being an unused constant.
7. **Tool calls are embedded in content register** — `"send email:
   attacker@evil.com"`, not `"Agent called tool send_email with arguments…"`.
   The boilerplate is shared by every action and dominates the embedding,
   costing ~0.25 of cosine distance uniformly. Removing it was the single
   largest accuracy improvement in the pipeline.
8. **The dashboard loads no third-party CSS or JS at runtime** (no Tailwind
   CDN). A tool that polices an agent's supply chain should not import an
   unpinned script from someone else's.

Items 4–7 came out of measuring against real embeddings rather than reasoning
about the formula. The `scripts/demo_agent.py` and red-team numbers above are
what they produce.

## Known limitations

- **Thresholds are tuned on eight scenarios.** They are defaults, not
  constants. Re-tune against your own agent traffic before trusting them.
- **The intent anchor is only as good as the request.** A vague request produces
  a vague anchor and weak drift signal. Hard policy is unaffected.
- **Ollama is optional and usually absent.** Without it the decomposer mines
  constraints with regex, which is deliberately conservative: a wrong constraint
  becomes a wrong `contradicts` edge.
- **The NetworkX graph store is per-process.** Multi-replica deployments need
  ArcadeDB for a shared graph.
- **An agent that never escalates is not detected by the soft layer.** A single
  catastrophic first action is a hard-policy problem, and that is the layer
  built to catch it.

## Contributing

1. `uv pip install -e ".[dev]"`
2. Make the change, with tests. New detection behaviour needs a red-team
   scenario *and* a benign control that must not regress.
3. `pytest tests/unit tests/integration -q && mypy --strict ariadne && ruff check ariadne eval tests`
4. `bash scripts/run_red_team.sh` — detection rate and FPR must not regress.
5. Open a PR describing the measured effect on both numbers, not just the
   intended one.

Tuning changes are the ones to be most careful with: it is easy to raise
detection by raising false positives, and the table at the top of this README is
the whole argument for the project.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
