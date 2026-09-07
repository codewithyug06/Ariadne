# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Standalone stand-in for the real upstream MCP tool server.

Ariadne's proxy always forwards intercepted calls to UPSTREAM_MCP_URL after
scoring/enforcement -- without something listening there, every session
fails at the forwarding step with "All connection attempts failed", even
though scoring and the decision itself already happened. scripts/ariadne_agent.py
embeds this same handler but only for the lifetime of that one script; this
version runs standalone so any external tester (e.g. the n8n test harness)
can drive traffic through Ariadne without also owning the upstream's lifecycle.

    python scripts/mock_upstream_server.py
"""

from __future__ import annotations

from typing import Any

import uvicorn
from fastapi import FastAPI

app = FastAPI(title="mock-upstream-mcp")


@app.post("/mcp")
async def handle(payload: dict[str, Any]) -> dict[str, Any]:
    method = payload.get("method")
    request_id = payload.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "mock-upstream", "version": "1.0.0"},
                "capabilities": {"tools": {}},
            },
        }
    if method in ("tools/call", "tools/execute"):
        name = payload.get("params", {}).get("name", "unknown")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": f"{name} completed"}],
                "isError": False,
            },
        }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


def main() -> int:
    uvicorn.run(app, host="127.0.0.1", port=9000, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
