#!/usr/bin/env bash
# Ariadne Continuous Monitor (LOCAL DEVELOPMENT / DEMO ONLY)
# ─────────────────────────────────────────────────────────────────────────────
# Runs the real AI agent demo in a loop so the dashboard always has live data.
# Credentials come from demo/.env — no manual export needed.
#
# Usage (from demo/ folder in Git Bash):
#   bash monitor.sh
#
# Press Ctrl+C to stop.
#
# This loop and its demo/.env MCP_PROXY_URL are for exercising a local
# Ariadne instance during development only. A real production agent should
# never point at localhost -- it connects using the command generated on the
# dashboard's Runs or Settings page once the operator sets ARIADNE_PUBLIC_URL
# (e.g. https://ariadne.yourcompany.com/mcp).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Load credentials from demo/.env
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${SCRIPT_DIR}/.env"
  set +a
else
  echo "[ERROR] demo/.env not found. Run from the demo/ folder." >&2
  exit 1
fi

export MCP_PROXY_URL="${MCP_PROXY_URL:-http://localhost:8000/mcp}"
export ARIADNE_API_KEY="${ARIADNE_API_KEY:-}"
export ARIADNE_BASE_URL="${MCP_PROXY_URL%/mcp}"
export DEMO_TOOL_SERVER_URL="${DEMO_TOOL_SERVER_URL:-http://127.0.0.1:9000}"
TOOL_SERVER_PORT="${DEMO_TOOL_SERVER_URL##*:}"

if [[ -z "${ARIADNE_API_KEY}" ]]; then
  echo "[ERROR] ARIADNE_API_KEY not set in demo/.env" >&2
  exit 1
fi

echo ""
echo "  Ariadne Continuous Monitor"
echo "  Proxy  : ${MCP_PROXY_URL}"
echo "  Key    : ${ARIADNE_API_KEY:0:30}..."
echo "  Press Ctrl+C to stop."
echo ""

# ── Check Ariadne is reachable ───────────────────────────────────────────────
if ! curl -sf "${ARIADNE_BASE_URL}/health" > /dev/null 2>&1; then
  echo "[ERROR] Ariadne not reachable at ${ARIADNE_BASE_URL}" >&2
  exit 1
fi
echo "[OK] Ariadne reachable."

# ── Auto-start demo tool server on :9000 if not running ──────────────────────
if ! curl -sf "${DEMO_TOOL_SERVER_URL}/health" > /dev/null 2>&1; then
  echo "[INFO] Starting demo tool server on :${TOOL_SERVER_PORT}..."
  cd "${REPO_ROOT}"
  uvicorn demo.tool_server.server:app --port "${TOOL_SERVER_PORT}" --log-level warning &
  TOOL_PID=$!
  for i in $(seq 1 15); do
    if curl -sf "${DEMO_TOOL_SERVER_URL}/health" > /dev/null 2>&1; then
      echo "[OK] Tool server ready."
      break
    fi
    [[ $i -eq 15 ]] && { echo "[ERROR] Tool server failed to start." >&2; kill "${TOOL_PID}" 2>/dev/null; exit 1; }
    sleep 1
  done
else
  echo "[OK] Tool server already running."
fi

cd "${REPO_ROOT}"

# ── Continuous loop ───────────────────────────────────────────────────────────
RUN=1
while true; do
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Run #${RUN}  —  $(date '+%Y-%m-%d %H:%M:%S')"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""

  python demo/scripts/run_demo.py --direct || true

  echo ""
  echo "[OK] Run #${RUN} complete. Dashboard: http://localhost:5173"
  echo "     Next run in 10 seconds..."
  echo ""

  RUN=$((RUN + 1))
  sleep 10
done
