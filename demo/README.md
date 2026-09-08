# Ariadne Demo — Sales Research Agent

A self-contained demonstration of Ariadne's real detection pipeline: a
competitive-research agent is told to research three companies and never
contact anyone. One scraped page carries an indirect prompt injection asking
for an email introduction. Ariadne's actual drift scoring, provenance graph,
and hard-policy engine intercept the resulting `send_email` call before it
ever reaches the upstream tool server — no part of the result shown below is
mocked, hardcoded, or simulated.

## Prerequisites

```bash
# Ariadne itself must be running first
cd <ariadne-repo-root>
uv pip install -e ".[dev,embeddings]"

# The demo needs Ariadne's proxy pointed at the demo tool server instead of
# the default mock upstream on :9000 -- set this in your .env:
#   UPSTREAM_MCP_URL=http://localhost:8001/mcp

bash scripts/start_dev.sh   # Ariadne on :8000, dashboard on :5173

# In a second terminal: the demo's own upstream tool server
uvicorn demo.tool_server.server:app --port 8001

# n8n (only needed for the full agent-driven run; --direct mode skips it)
npm install -g n8n
n8n start   # n8n on :5678
```

## One-time setup

```bash
# 1. Mint an Ariadne API key if you don't already have one
python scripts/provision_api_key.py
export ARIADNE_API_KEY=<the key it prints>

# 2. (n8n path only) Set your Anthropic API key for the AI Agent node
export ANTHROPIC_API_KEY=sk-ant-...

# 3. (n8n path only) Import the workflow
# Open http://localhost:5678 -> Menu -> Import from File -> demo/n8n/workflow.json
# See demo/n8n/setup_instructions.md for credential wiring and a known MCP
# transport caveat.
```

## Run the demo

Two ways to run it, both exercising Ariadne's real pipeline:

```bash
# Fastest / most reliable: play the tool-call sequence directly through
# Ariadne's /mcp proxy (same technique scripts/ariadne_agent.py uses),
# without depending on n8n's MCP client transport.
python demo/scripts/run_demo.py --direct

# Full end-to-end via n8n's AI Agent deciding which tools to call
python demo/scripts/run_demo.py --n8n-webhook <path from your imported workflow>
```

## Verify it worked

```bash
python demo/scripts/verify_demo.py
# Expected: N/N assertions passed
```

## Run again (clean slate)

```bash
python demo/scripts/reset_demo.py
python demo/scripts/run_demo.py --direct
```

Note: Ariadne has no bulk-delete endpoint for runs, so prior `sales-research-agent-*` sessions
remain in its database after a reset. This is harmless — it does not affect
scoring for the next run.

## What to show an audience

1. Open the Ariadne dashboard: `http://localhost:5173`
2. Run: `python demo/scripts/run_demo.py --direct`
3. Watch the terminal: real drift scores rising as the poisoned page is
   scraped, then a real BLOCK on `send_email`
4. Switch to the dashboard: open the run, show the step table, drift chart,
   and the BLOCK badge on the final row
5. Point out the panel's line: `send_email calls reached upstream: 0` —
   proof from the tool server's own log, not from Ariadne's self-report
6. Run `python demo/scripts/verify_demo.py` for the full assertion list

## What's real here, and what to know before deploying

- The tool server (`demo/tool_server/`) is a real FastAPI JSON-RPC server,
  modeled on `scripts/mock_upstream_server.py`. Every `send_email` /
  `create_crm_contact` call it receives is logged to
  `demo/results/tool_call_log.json` — that log, not a printed claim, is what
  `verify_demo.py` checks.
- Every drift score, decision, and root-cause value printed by `run_demo.py`
  is read back from Ariadne's own API (`GET /api/v1/runs/{id}`,
  `/graph`) after the run finishes.
- The n8n workflow JSON's node parameters are validated against n8n's actual
  node schemas, but the MCP Client Tool node's streamable-HTTP handshake
  against Ariadne's hand-rolled `/mcp` proxy has a documented caveat — see
  `demo/n8n/setup_instructions.md`. `--direct` mode is the dependable path if
  you hit transport issues and just need to show the interception working.
