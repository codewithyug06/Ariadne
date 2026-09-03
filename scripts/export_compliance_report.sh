#!/usr/bin/env bash
# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
#
# Export a compliance report for a run.
#
#   scripts/export_compliance_report.sh                 # most recent run
#   scripts/export_compliance_report.sh <session-id>    # a specific run
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON=".venv/bin/python"
  elif [[ -x ".venv/Scripts/python.exe" ]]; then
    PYTHON=".venv/Scripts/python.exe"
  else
    PYTHON="python3"
  fi
fi

export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

SESSION_ID="${1:-}"
if [[ -z "$SESSION_ID" ]]; then
  echo "No session given; selecting the most recent run..."
  SESSION_ID="$("$PYTHON" - <<'PY'
import asyncio
from ariadne.audit.recorder import AuditRecorder
from ariadne.config import get_settings
from ariadne.db.session import Database


async def latest() -> None:
    settings = get_settings()
    database = Database(settings)
    await database.create_all()
    runs, _ = await AuditRecorder(database, settings).list_runs(limit=1)
    print(runs[0].session_id if runs else "")
    await database.close()


asyncio.run(latest())
PY
)"
  if [[ -z "$SESSION_ID" ]]; then
    echo "No runs recorded yet. Route an agent through the proxy first, or run:" >&2
    echo "    bash scripts/run_red_team.sh" >&2
    exit 1
  fi
fi

echo "Exporting compliance report for: $SESSION_ID"
"$PYTHON" -m ariadne.cli report "$SESSION_ID" --format markdown \
  --output "compliance_report_${SESSION_ID}.md"
"$PYTHON" -m ariadne.cli report "$SESSION_ID" --format json \
  --output "compliance_report_${SESSION_ID}.json"

echo ""
echo "Wrote:"
echo "  compliance_report_${SESSION_ID}.md"
echo "  compliance_report_${SESSION_ID}.json"
