# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Real upstream MCP tool server for the Ariadne customer-research demo.

This is the UPSTREAM that Ariadne proxies tool calls to. The architecture is:

    n8n AI Agent
         |  (MCP Client Tool node)
    Ariadne  :8000   <- intercepts, scores, enforces
         |  (if ALLOW -- forwards to real upstream)
    This server  :8001  <- executes the actual tool

Ariadne's BLOCK means this server never receives the blocked call. That is the
proof the demo needs to show: demo/results/tool_call_log.json records every
call that reached here, so "send_email: 0 calls" is evidence, not a claim.

Run with:
    uvicorn demo.tool_server.server:app --port 8001
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from demo.tool_server.state import state
from demo.tool_server.tools import TOOL_HANDLERS, TOOL_SCHEMAS

app = FastAPI(title="ariadne-demo-upstream-mcp")


@app.post("/mcp")
@app.post("/mcp/")
async def handle_mcp(payload: dict[str, Any]) -> dict[str, Any]:
    method = payload.get("method")
    request_id = payload.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "ariadne-demo-upstream", "version": "1.0.0"},
                "capabilities": {"tools": {}},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": TOOL_SCHEMAS},
        }

    if method in ("tools/call", "tools/execute"):
        params = payload.get("params", {})
        name = params.get("name", "unknown")
        arguments = params.get("arguments", {})
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": f"unknown tool: {name}"},
            }
        result = await handler(**arguments)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": str(result)}],
                "structuredContent": result,
                "isError": False,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


@app.get("/mcp/sse")
async def mcp_sse() -> StreamingResponse:
    """Minimal SSE keep-alive stream for MCP clients (e.g. n8n's MCP Client
    Tool node) that expect an event-stream endpoint alongside the JSON-RPC
    POST handler. This demo has no async server-initiated notifications, so
    the stream only emits periodic comments to keep the connection alive.
    """

    async def _stream() -> Any:
        yield ": connected\n\n"
        try:
            while True:
                await asyncio.sleep(15)
                yield ": ping\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.post("/demo/reset")
async def demo_reset() -> dict[str, Any]:
    """Admin-only (no auth by design -- local demo server) reset endpoint."""
    state.reset()
    return {"reset": True}


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "email_attempts": state.email_attempts,
        "crm_contact_attempts": state.crm_contact_attempts,
    }
