#!/usr/bin/env python3
# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Clears demo state so the demo can be run again cleanly.

- Deletes demo/results/tool_call_log.json and demo/results/run_summary.json
- Calls POST /demo/reset on the tool server to clear its in-memory state
- Does NOT delete prior runs from Ariadne's own database: Ariadne's runs API
  has no bulk-delete endpoint. Old sales-research-agent-* sessions simply remain in the DB;
  this is harmless (they don't affect a new run's scoring) and matches how
  scripts/ariadne_agent.py already behaves across repeated invocations.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from rich.console import Console

console = Console()

TOOL_SERVER_URL = os.environ.get("DEMO_TOOL_SERVER_URL", "http://127.0.0.1:8001")
RESULTS_DIR = Path(__file__).parent.parent / "results"


def main() -> int:
    for name in ("tool_call_log.json", "run_summary.json"):
        path = RESULTS_DIR / name
        if path.exists():
            path.unlink()
            console.print(f"[green]OK[/green] removed {path}")

    try:
        response = httpx.post(f"{TOOL_SERVER_URL}/demo/reset", timeout=5.0)
        response.raise_for_status()
        console.print(f"[green]OK[/green] reset tool server state at {TOOL_SERVER_URL}")
    except httpx.HTTPError as exc:
        console.print(
            f"[yellow]warning:[/yellow] could not reach tool server at {TOOL_SERVER_URL} "
            f"to reset its in-memory state ({exc}). Start it with:\n"
            "  uvicorn demo.tool_server.server:app --port 8001"
        )

    console.print(
        "[dim]note: prior sales-research-agent-* runs remain in Ariadne's database -- there is no "
        "bulk-delete endpoint for runs. This is harmless; it does not affect scoring "
        "for the next run.[/dim]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
