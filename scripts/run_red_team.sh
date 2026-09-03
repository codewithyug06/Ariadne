#!/usr/bin/env bash
# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
#
# Run the red-team suite and print the detection metrics table.
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

# Rich draws box characters; Windows consoles default to cp1252 and would fail.
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

OUTPUT="${1:-red_team_results.json}"

echo "==> Red-team scenario assertions"
"$PYTHON" -m pytest tests/red_team tests/integration/test_drift_detection.py -v --tb=short

echo ""
echo "==> Detection metrics (Ariadne vs naive per-step cosine baseline)"
"$PYTHON" -m tests.red_team.run_scenarios --output "$OUTPUT"

echo ""
echo "Full results: $OUTPUT"
