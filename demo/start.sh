#!/usr/bin/env bash
# Ariadne Demo — Quick Start (LOCAL DEVELOPMENT / DEMO ONLY)
# ─────────────────────────────────────────────────────────────────────────────
# Paste the chained command copied from the dashboard into your terminal
# inside the demo/ folder:
#
#   export MCP_PROXY_URL="..." && export ARIADNE_API_KEY="..." && bash start.sh
#
# Requirements: Ariadne running on :8000.
# The demo tool server is started automatically on :9000 (Ariadne's upstream).
#
# This script and its default MCP_PROXY_URL are for running the sample agent
# scenario against a local Ariadne instance only. A real production agent
# should never point at localhost -- it connects using the command shown on
# the dashboard's Runs or Settings page, which reads the operator's real
# ARIADNE_PUBLIC_URL (e.g. https://ariadne.yourcompany.com/mcp) once that is
# configured. See ariadne/config.py's `public_url` and docker-compose.prod.yml.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

export MCP_PROXY_URL="${MCP_PROXY_URL:-http://localhost:8000/mcp}"
export ARIADNE_API_KEY="${ARIADNE_API_KEY:-}"
export ARIADNE_BASE_URL="${MCP_PROXY_URL%/mcp}"
# Demo tool server must match UPSTREAM_MCP_URL in Ariadne's .env (:9000/mcp)
export DEMO_TOOL_SERVER_URL="${DEMO_TOOL_SERVER_URL:-http://127.0.0.1:9000}"
TOOL_SERVER_PORT="${DEMO_TOOL_SERVER_URL##*:}"

# ── Validate credentials ──────────────────────────────────────────────────────
if [[ -z "${ARIADNE_API_KEY}" ]]; then
  echo "[ERROR] ARIADNE_API_KEY is not set." >&2
  echo "        Copy the command from the dashboard and paste the full line." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo ""
echo "  Ariadne Agent Monitor"
echo "  Proxy  : ${MCP_PROXY_URL}"
echo "  Key    : ${ARIADNE_API_KEY:0:18}..."
echo ""

# ── Check Ariadne is reachable ───────────────────────────────────────────────
if ! curl -sf "${ARIADNE_BASE_URL}/health" -H "X-Api-Key: ${ARIADNE_API_KEY}" > /dev/null 2>&1; then
  echo "[ERROR] Cannot reach Ariadne at ${ARIADNE_BASE_URL}" >&2
  echo "        Start it first (from repo root):" >&2
  echo "          bash scripts/start_dev.sh" >&2
  exit 1
fi
echo "[OK] Ariadne reachable."

# ── Auto-start demo tool server on :9000 if not running ──────────────────────
if ! curl -sf "${DEMO_TOOL_SERVER_URL}/health" > /dev/null 2>&1; then
  echo "[INFO] Demo tool server not running — starting it on :${TOOL_SERVER_PORT}..."
  cd "${REPO_ROOT}"
  uvicorn demo.tool_server.server:app --port "${TOOL_SERVER_PORT}" --log-level warning &
  TOOL_SERVER_PID=$!
  echo "[INFO] Tool server PID: ${TOOL_SERVER_PID}"

  for i in $(seq 1 10); do
    if curl -sf "${DEMO_TOOL_SERVER_URL}/health" > /dev/null 2>&1; then
      echo "[OK] Tool server ready on :${TOOL_SERVER_PORT}."
      break
    fi
    if [[ $i -eq 10 ]]; then
      echo "[ERROR] Tool server did not start in time." >&2
      kill "${TOOL_SERVER_PID}" 2>/dev/null || true
      exit 1
    fi
    sleep 1
  done
else
  echo "[OK] Tool server already running on :${TOOL_SERVER_PORT}."
fi

echo ""
echo "[START] Running agent monitoring demo..."
echo ""

cd "${REPO_ROOT}"
python demo/scripts/run_demo.py --direct

echo ""
echo "[OK] Run complete. Verifying assertions..."
echo ""

python demo/scripts/verify_demo.py

echo ""
echo "Dashboard: http://localhost:5173"
echo ""
