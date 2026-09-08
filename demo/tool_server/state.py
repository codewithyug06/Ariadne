# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Shared state: records which tools were actually called (reached this server).

Used by verify_demo.py to prove Ariadne blocked before forwarding. In production
Ariadne stops the call before it reaches the upstream. This state file is the
evidence: email_attempts=0 proves the email never sent.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATE_FILE = Path(__file__).parent.parent / "results" / "tool_call_log.json"


class ToolCallState:
    """Log of every tool call that reached this server."""

    def __init__(self) -> None:
        self._calls: list[dict[str, Any]] = []

    def record(self, tool_name: str, arguments: dict[str, Any]) -> None:
        self._calls.append(
            {
                "tool": tool_name,
                "arguments": arguments,
                "reached_upstream": True,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        self._flush()

    @property
    def calls(self) -> list[dict[str, Any]]:
        return list(self._calls)

    @property
    def email_attempts(self) -> int:
        return sum(1 for c in self._calls if c["tool"] == "send_email")

    @property
    def crm_contact_attempts(self) -> int:
        return sum(1 for c in self._calls if c["tool"] == "create_crm_contact")

    def _flush(self) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self._calls, indent=2))

    def reset(self) -> None:
        self._calls = []
        if STATE_FILE.exists():
            STATE_FILE.unlink()


state = ToolCallState()
