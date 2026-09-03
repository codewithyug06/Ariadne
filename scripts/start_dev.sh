#!/usr/bin/env bash
# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
#
# One command to bring up the whole development stack.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON=".venv/bin/python"
  elif [[ -x ".venv/Scripts/python.exe" ]]; then
    PYTHON=".venv/Scripts/python.exe"   # Git Bash on Windows
  else
    PYTHON="python3"
  fi
fi

if [[ ! -f .env ]]; then
  echo "No .env found; copying .env.example"
  cp .env.example .env
fi

mkdir -p data

# ArcadeDB is optional. Without it Ariadne uses the in-process NetworkX graph,
# which is fully functional but not shared across processes.
if [[ "${WITH_ARCADEDB:-0}" == "1" ]]; then
  if command -v docker >/dev/null 2>&1; then
    if ! docker ps --format '{{.Names}}' | grep -q '^ariadne-arcadedb$'; then
      echo "Starting ArcadeDB..."
      docker run -d --rm --name ariadne-arcadedb -p 2480:2480 \
        -e JAVA_OPTS="-Darcadedb.server.rootPassword=${ARCADEDB_PASSWORD:-ariadne_dev} -Darcadedb.server.defaultDatabases=ariadne[root]" \
        arcadedata/arcadedb:24.11.1 >/dev/null
    fi
    export ARCADEDB_URL="http://localhost:2480"
    export ARCADEDB_PASSWORD="${ARCADEDB_PASSWORD:-ariadne_dev}"
  else
    echo "docker not found; falling back to the in-process NetworkX graph store." >&2
  fi
fi

PIDS=()
cleanup() {
  echo ""
  echo "Shutting down..."
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  if [[ "${WITH_ARCADEDB:-0}" == "1" ]] && command -v docker >/dev/null 2>&1; then
    docker stop ariadne-arcadedb >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

echo "Starting Ariadne proxy on :8000..."
"$PYTHON" -m uvicorn ariadne.main:app --host 0.0.0.0 --port 8000 --reload &
PIDS+=($!)

if [[ -d dashboard/node_modules ]]; then
  echo "Starting dashboard on :5173..."
  (cd "$ROOT/dashboard" && npm run dev -- --host) &
  PIDS+=($!)
else
  echo "dashboard/node_modules missing — run 'cd dashboard && npm install' to enable the UI." >&2
fi

cat <<'BANNER'

  Ariadne is starting.

    Proxy      http://localhost:8000/mcp
    API docs   http://localhost:8000/docs
    Health     http://localhost:8000/health
    Dashboard  http://localhost:5173

  Point your agent's MCP client at the proxy URL and pass the user's request
  in the initialize params as "userRequest" so drift can be scored.

  Ctrl-C to stop.

BANNER

wait
