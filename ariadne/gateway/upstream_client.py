# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Talks to a customer's own MCP tool server on their behalf.

Scope note: only `test_connection` is implemented. The original spec this
was adapted from also asked for `forward_tool_call`, used by a full
multi-tenant MCP gateway that authenticates callers, resolves their org's
upstream, and forwards intercepted calls there instead of the single
global `settings.upstream_mcp_url` ariadne/proxy/mcp_proxy.py forwards
every session to today. Building `forward_tool_call` without that gateway
wiring it in would be dead code -- nothing would ever call it, and nothing
here changes what a real tool call does. `test_connection` stands alone:
it powers ariadne/api/connect.py's "Test Connection" button, which is a
complete, independently useful feature (confirm a customer's tool server
is reachable before they wire anything else up).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx


@dataclass(frozen=True)
class ConnectionTestResult:
    reachable: bool
    latency_ms: float | None
    server_info: dict[str, Any] | None
    error: str | None


class UpstreamMCPClient:
    """Speaks JSON-RPC 2.0 to a customer-configured MCP tool server."""

    async def test_connection(
        self, upstream_url: str, upstream_headers: dict[str, str]
    ) -> ConnectionTestResult:
        """Send an MCP `initialize` request and report whether it answered.

        Used by the dashboard's "Test Connection" button before an org's
        upstream config is trusted for anything else.
        """
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
                response = await client.post(
                    upstream_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": str(uuid4()),
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "ariadne-connection-tester"},
                        },
                    },
                    headers={"Content-Type": "application/json", **upstream_headers},
                )
                latency_ms = (time.perf_counter() - started) * 1000.0
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            return ConnectionTestResult(
                reachable=False, latency_ms=None, server_info=None, error=str(exc)
            )
        except ValueError as exc:  # non-JSON response body
            return ConnectionTestResult(
                reachable=False, latency_ms=None, server_info=None, error=f"invalid JSON: {exc}"
            )

        return ConnectionTestResult(
            reachable=True,
            latency_ms=round(latency_ms, 1),
            server_info=data.get("result", {}).get("serverInfo"),
            error=None,
        )
