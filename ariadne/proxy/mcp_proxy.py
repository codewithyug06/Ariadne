# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""The MCP proxy: every tool call in the chain passes through here."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from ariadne.audit.schemas import RunSummary
from ariadne.config import Settings, get_settings
from ariadne.logging import get_logger
from ariadne.proxy.interceptor import ToolCallInterceptor
from ariadne.proxy.schemas import (
    InterceptionResult,
    JSONRPCErrorCode,
    MCPRequest,
    MCPResponse,
    SessionState,
    ToolCall,
    ToolResult,
    utcnow,
)

logger = get_logger(__name__)

TOOL_CALL_METHODS = frozenset({"tools/call", "tools/execute"})
SESSION_END_METHODS = frozenset({"shutdown", "session/end", "notifications/cancelled"})

#: Params keys an orchestrator may use to hand Ariadne the original request.
USER_REQUEST_KEYS = ("userRequest", "user_request", "prompt", "objective", "goal")


class ApprovalRegistry:
    """Pending human-in-the-loop approvals, keyed by an opaque approval id."""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[bool]] = {}

    def open(self) -> tuple[str, asyncio.Future[bool]]:
        approval_id = str(uuid.uuid4())
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[approval_id] = future
        return approval_id, future

    def resolve(self, approval_id: str, approved: bool) -> bool:
        future = self._pending.pop(approval_id, None)
        if future is None or future.done():
            return False
        future.set_result(approved)
        return True

    def discard(self, approval_id: str) -> None:
        self._pending.pop(approval_id, None)

    @property
    def pending_count(self) -> int:
        return len(self._pending)


class MCPProxy:
    """JSON-RPC MCP proxy with interception between orchestrator and tool server."""

    def __init__(
        self,
        interceptor: ToolCallInterceptor,
        anchors: Any,
        graph_builder: Any,
        recorder: Any,
        stream_hub: Any,
        http_client: httpx.AsyncClient,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._interceptor = interceptor
        self._anchors = anchors
        self._graph = graph_builder
        self._recorder = recorder
        self._hub = stream_hub
        self._client = http_client
        self._sessions: dict[str, SessionState] = {}
        self._approvals = ApprovalRegistry()

    # ---- Session handling -------------------------------------------------

    @property
    def sessions(self) -> dict[str, SessionState]:
        return self._sessions

    @property
    def approvals(self) -> ApprovalRegistry:
        return self._approvals

    def _session(self, session_id: str) -> SessionState:
        state = self._sessions.get(session_id)
        if state is None:
            state = SessionState(session_id=session_id)
            self._sessions[session_id] = state
            self._recorder.record_run_start(
                RunSummary(session_id=session_id, started_at=state.started_at)
            )
            logger.info("proxy.session_started", session_id=session_id)
        return state

    async def _start_session(self, session_id: str, params: dict[str, Any]) -> None:
        """Handshake: capture the user's request and build the intent anchor."""
        state = self._session(session_id)
        raw_request = _extract_user_request(params)

        if raw_request:
            anchor = await self._anchors.generate(session_id, raw_request)
            await self._graph.add_user_request(anchor)
            self._recorder.record_run_start(
                RunSummary(
                    session_id=session_id,
                    started_at=state.started_at,
                    intent_summary=anchor.goal,
                )
            )
        else:
            logger.warning(
                "proxy.no_intent_anchor",
                session_id=session_id,
                hint=(
                    "pass the user's request in initialize params as 'userRequest' "
                    "so drift can be scored; hard policy still applies without it"
                ),
            )

        granted = params.get("capabilities", {})
        if isinstance(granted, dict):
            tools = granted.get("tools")
            if isinstance(tools, list):
                self._graph.grant_capabilities(session_id, {str(tool) for tool in tools})

    async def end_session(self, session_id: str) -> RunSummary | None:
        """Write the closing summary and release per-session state."""
        state = self._sessions.pop(session_id, None)
        if state is None:
            return None

        # Audit writes are queued off the hot path, so the summary's counts
        # would race with the drain task without this flush.
        await self._recorder.flush()
        events = await self._recorder.get_events(session_id)
        summary = RunSummary(
            session_id=session_id,
            started_at=state.started_at,
            ended_at=utcnow(),
            total_steps=state.step_counter,
            final_status=state.final_status,
            max_drift_score=state.max_drift_score,
            blocked_count=sum(1 for e in events if e.enforcement_action == "BLOCK"),
            escalated_count=sum(1 for e in events if e.enforcement_action == "ESCALATE"),
            warned_count=sum(1 for e in events if e.enforcement_action == "WARN"),
            intent_summary=_anchor_goal(self._anchors, session_id),
        )
        self._recorder.record_run_end(summary)
        self._interceptor.release_session(session_id)
        logger.info(
            "proxy.session_ended",
            session_id=session_id,
            total_steps=summary.total_steps,
            final_status=summary.final_status,
            max_drift_score=round(summary.max_drift_score, 2),
        )
        return summary

    # ---- Request handling -------------------------------------------------

    async def handle(
        self, request: MCPRequest, session_id: str, hitl_token: str | None = None
    ) -> tuple[MCPResponse, dict[str, str]]:
        """Adjudicate and route one JSON-RPC request. Returns response + headers."""
        headers: dict[str, str] = {"X-Ariadne-Session-Id": session_id}

        if request.method == "initialize":
            await self._start_session(session_id, request.params)
            response = await self._forward(request, session_id)
            return response, headers

        if request.method in SESSION_END_METHODS:
            await self.end_session(session_id)
            return MCPResponse.ok(request.id, {"ok": True}), headers

        if request.method not in TOOL_CALL_METHODS:
            # Discovery and notification traffic carries no action to adjudicate.
            return await self._forward(request, session_id), headers

        return await self._handle_tool_call(request, session_id, hitl_token, headers)

    async def _handle_tool_call(
        self,
        request: MCPRequest,
        session_id: str,
        hitl_token: str | None,
        headers: dict[str, str],
    ) -> tuple[MCPResponse, dict[str, str]]:
        state = self._session(session_id)
        state.tool_call_count += 1
        step_index = state.next_step()

        tool_call = ToolCall(
            session_id=session_id,
            step_index=step_index,
            tool_name=str(request.params.get("name", "unknown")),
            arguments=_as_dict(request.params.get("arguments")),
            calling_agent_id=str(request.params.get("agent_id", "orchestrator")),
            stated_justification=request.params.get("justification"),
            request_id=request.id,
        )

        result = await self._interceptor.intercept(tool_call, state, hitl_token)
        headers["X-Ariadne-Decision"] = result.action
        headers["X-Ariadne-Layer"] = result.layer
        if result.drift_score is not None:
            headers["X-Ariadne-Drift-Score"] = f"{result.drift_score:.1f}"
        if result.graph_node_id:
            headers["X-Ariadne-Node-Id"] = result.graph_node_id

        if result.action == "ESCALATE":
            approved = await self._await_human_approval(tool_call, result)
            if not approved:
                state.blocked = True
                return (
                    MCPResponse.failure(
                        request.id,
                        JSONRPCErrorCode.ARIADNE_ESCALATION_DENIED,
                        f"Ariadne escalated this action and it was not approved: {result.reason}",
                        _decision_payload(result),
                    ),
                    headers,
                )
            headers["X-Ariadne-Approved"] = "true"

        elif result.action == "BLOCK":
            logger.warning(
                "proxy.blocked",
                session_id=session_id,
                step_index=step_index,
                tool_name=tool_call.tool_name,
                reason=result.reason,
                triggered_rule=result.triggered_rule,
                drift_score=result.drift_score,
            )
            return (
                MCPResponse.failure(
                    request.id,
                    JSONRPCErrorCode.ARIADNE_BLOCKED,
                    f"Blocked by Ariadne: {result.reason}",
                    _decision_payload(result),
                ),
                headers,
            )

        elif result.action == "WARN":
            headers["X-Ariadne-Warning"] = result.reason[:400]

        # ALLOW / WARN / approved ESCALATE all reach the real tool.
        response = await self._forward(request, session_id)
        await self._record_result(response, tool_call, result)
        return response, headers

    async def _await_human_approval(self, tool_call: ToolCall, result: InterceptionResult) -> bool:
        """POST to the HITL webhook and wait. Timeout means deny."""
        if not self._settings.hitl_webhook_url:
            logger.warning(
                "proxy.hitl_not_configured",
                session_id=tool_call.session_id,
                step_index=tool_call.step_index,
                resolved="deny",
                hint="set HITL_WEBHOOK_URL to enable human approval",
            )
            return False

        approval_id, future = self._approvals.open()
        payload = {
            "approval_id": approval_id,
            "session_id": tool_call.session_id,
            "step_index": tool_call.step_index,
            "tool_name": tool_call.tool_name,
            "arguments": tool_call.arguments,
            "reason": result.reason,
            "drift_score": result.drift_score,
            "triggered_rule": result.triggered_rule,
            "node_id": result.graph_node_id,
            "expires_in_seconds": self._settings.hitl_timeout_seconds,
        }
        try:
            response = await self._client.post(
                self._settings.hitl_webhook_url, json=payload, timeout=10.0
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            self._approvals.discard(approval_id)
            logger.error(
                "proxy.hitl_webhook_failed",
                session_id=tool_call.session_id,
                url=self._settings.hitl_webhook_url,
                error=str(exc),
                error_type=type(exc).__name__,
                resolved="deny",
            )
            return False

        try:
            approved = await asyncio.wait_for(future, timeout=self._settings.hitl_timeout_seconds)
        except TimeoutError:
            self._approvals.discard(approval_id)
            logger.warning(
                "proxy.hitl_timeout",
                session_id=tool_call.session_id,
                step_index=tool_call.step_index,
                timeout_seconds=self._settings.hitl_timeout_seconds,
                resolved="deny",
            )
            return False

        logger.info(
            "proxy.hitl_resolved",
            session_id=tool_call.session_id,
            step_index=tool_call.step_index,
            approved=approved,
        )
        return approved

    async def _record_result(
        self, response: MCPResponse, tool_call: ToolCall, result: InterceptionResult
    ) -> None:
        if not result.graph_node_id:
            return
        tool_result = ToolResult(
            session_id=tool_call.session_id,
            step_index=tool_call.step_index,
            tool_name=tool_call.tool_name,
            content=response.result if response.error is None else response.error.message,
            is_error=response.error is not None,
        )
        await self._interceptor.record_result(tool_result, result.graph_node_id)

    async def _forward(self, request: MCPRequest, session_id: str) -> MCPResponse:
        """Relay a request to the upstream MCP server."""
        started = time.perf_counter()
        try:
            upstream = await self._client.post(
                self._settings.upstream_mcp_url,
                json=request.model_dump(mode="json"),
                headers={"X-Ariadne-Session-Id": session_id},
                timeout=self._settings.upstream_timeout_seconds,
            )
            upstream.raise_for_status()
            payload = upstream.json()
        except httpx.TimeoutException as exc:
            return self._upstream_error(request, session_id, exc, "timeout")
        except httpx.HTTPStatusError as exc:
            return self._upstream_error(
                request, session_id, exc, f"status {exc.response.status_code}"
            )
        except (httpx.HTTPError, ValueError) as exc:
            return self._upstream_error(request, session_id, exc, "transport")

        logger.debug(
            "proxy.forwarded",
            session_id=session_id,
            method=request.method,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
        )
        return MCPResponse.model_validate(payload)

    def _upstream_error(
        self, request: MCPRequest, session_id: str, exc: Exception, kind: str
    ) -> MCPResponse:
        logger.error(
            "proxy.upstream_failed",
            session_id=session_id,
            method=request.method,
            url=self._settings.upstream_mcp_url,
            failure=kind,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return MCPResponse.failure(
            request.id,
            JSONRPCErrorCode.ARIADNE_UPSTREAM_ERROR,
            f"Upstream MCP server error ({kind}): {exc}",
            {"upstream_url": self._settings.upstream_mcp_url},
        )


# ---- FastAPI wiring -------------------------------------------------------


def create_proxy_router() -> APIRouter:
    """Router mounted at /mcp. Reads the live proxy off app state."""
    router = APIRouter(tags=["mcp"])

    @router.post("", summary="MCP JSON-RPC endpoint (intercepted)")
    @router.post("/", include_in_schema=False)
    async def mcp_endpoint(
        request: Request,
        x_ariadne_session_id: str | None = Header(default=None),
        x_ariadne_hitl_token: str | None = Header(default=None),
    ) -> JSONResponse:
        proxy: MCPProxy = request.app.state.proxy
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(
                status_code=400,
                content=MCPResponse.failure(
                    None, JSONRPCErrorCode.PARSE_ERROR, "Request body is not valid JSON"
                ).model_dump(mode="json", exclude_none=True),
            )

        try:
            rpc_request = MCPRequest.model_validate(body)
        except ValueError as exc:
            return JSONResponse(
                status_code=400,
                content=MCPResponse.failure(
                    body.get("id") if isinstance(body, dict) else None,
                    JSONRPCErrorCode.INVALID_REQUEST,
                    f"Malformed JSON-RPC request: {exc}",
                ).model_dump(mode="json", exclude_none=True),
            )

        session_id = (
            x_ariadne_session_id
            or str(rpc_request.params.get("session_id") or "")
            or f"session-{uuid.uuid4()}"
        )
        response, headers = await proxy.handle(rpc_request, session_id, x_ariadne_hitl_token)
        return JSONResponse(
            content=response.model_dump(mode="json", exclude_none=True), headers=headers
        )

    @router.post("/hitl/{approval_id}", summary="Resolve a pending HITL escalation")
    async def resolve_approval(
        approval_id: str, request: Request, approved: bool = True
    ) -> JSONResponse:
        proxy: MCPProxy = request.app.state.proxy
        resolved = proxy.approvals.resolve(approval_id, approved)
        if not resolved:
            return JSONResponse(
                status_code=404,
                content={
                    "detail": "unknown or already-resolved approval",
                    "approval_id": approval_id,
                },
            )
        return JSONResponse(content={"approval_id": approval_id, "approved": approved})

    @router.post("/sessions/{session_id}/end", summary="Close a session and write its summary")
    async def close_session(session_id: str, request: Request) -> JSONResponse:
        proxy: MCPProxy = request.app.state.proxy
        summary = await proxy.end_session(session_id)
        if summary is None:
            return JSONResponse(status_code=404, content={"detail": "unknown session"})
        return JSONResponse(content=summary.model_dump(mode="json"))

    return router


def _extract_user_request(params: dict[str, Any]) -> str:
    for key in USER_REQUEST_KEYS:
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    client_info = params.get("clientInfo")
    if isinstance(client_info, dict):
        for key in USER_REQUEST_KEYS:
            value = client_info.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else ({} if value is None else {"value": value})


def _decision_payload(result: InterceptionResult) -> dict[str, Any]:
    return {
        "ariadne": {
            "action": result.action,
            "reason": result.reason,
            "drift_score": result.drift_score,
            "slope": result.slope,
            "triggered_rule": result.triggered_rule,
            "node_id": result.graph_node_id,
            "step_index": result.step_index,
            "session_id": result.session_id,
        }
    }


def _anchor_goal(anchors: Any, session_id: str) -> str:
    anchor = anchors.get(session_id)
    return anchor.goal if anchor is not None else ""
