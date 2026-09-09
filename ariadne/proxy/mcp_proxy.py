# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""The MCP proxy: every tool call in the chain passes through here."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from ariadne.audit.exporter import _to_audit_event
from ariadne.audit.schemas import RunSummary
from ariadne.audit.trajectory_recorder import TrajectoryRecorder
from ariadne.billing.quotas import QuotaCheckResult, QuotaEnforcer
from ariadne.config import Settings, get_settings
from ariadne.db.models import LEGACY_ORG_ID, Agent
from ariadne.db.session import Database
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

#: Params keys an orchestrator may use to identify the calling agent at
#: session start — mirrors the "agent_id" key already read per-tool-call in
#: _handle_tool_call's ToolCall.calling_agent_id.
AGENT_IDENTITY_KEYS = ("agent_id", "agentId", "calling_agent_id")


class ApprovalRegistry:
    """Pending human-in-the-loop approvals, keyed by an opaque approval id.

    Metadata rides alongside the future so a dashboard can list *what* is
    waiting (tool name, drift score, reason) — not just how many.
    """

    def __init__(self) -> None:
        self._pending: dict[str, tuple[asyncio.Future[bool], dict[str, Any]]] = {}

    def open(
        self, metadata: dict[str, Any] | None = None
    ) -> tuple[str, asyncio.Future[bool]]:
        approval_id = str(uuid.uuid4())
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[approval_id] = (future, dict(metadata or {}))
        return approval_id, future

    def resolve(self, approval_id: str, approved: bool) -> bool:
        entry = self._pending.pop(approval_id, None)
        if entry is None or entry[0].done():
            return False
        entry[0].set_result(approved)
        return True

    def discard(self, approval_id: str) -> None:
        self._pending.pop(approval_id, None)

    def list_pending(self) -> list[dict[str, Any]]:
        return [
            {"approval_id": approval_id, **metadata}
            for approval_id, (_, metadata) in self._pending.items()
        ]

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
        database: Database | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._interceptor = interceptor
        self._anchors = anchors
        self._graph = graph_builder
        self._recorder = recorder
        self._hub = stream_hub
        self._client = http_client
        self._database = database
        self._sessions: dict[str, SessionState] = {}
        self._approvals = ApprovalRegistry()
        # Feature 7 (data flywheel). Built lazily, only once a database is
        # available -- mirrors how self._database itself is optional
        # (some callers, e.g. certain tests, run the proxy without one).
        self._trajectory_recorder: TrajectoryRecorder | None = (
            TrajectoryRecorder(database, graph_builder) if database is not None else None
        )
        # Feature: per-org usage quotas. Same optionality as the trajectory
        # recorder above -- no database, no enforcement (matches every other
        # DB-backed feature in this class).
        self._quotas: QuotaEnforcer | None = (
            QuotaEnforcer(database) if database is not None else None
        )

    # ---- Session handling -------------------------------------------------

    @property
    def sessions(self) -> dict[str, SessionState]:
        return self._sessions

    @property
    def approvals(self) -> ApprovalRegistry:
        return self._approvals

    def _session(self, session_id: str, organization_id: str = LEGACY_ORG_ID) -> SessionState:
        state = self._sessions.get(session_id)
        if state is None:
            state = SessionState(session_id=session_id, organization_id=organization_id)
            self._sessions[session_id] = state
            self._recorder.record_run_start(
                RunSummary(session_id=session_id, started_at=state.started_at),
                organization_id=state.organization_id,
            )
            logger.info(
                "proxy.session_started", session_id=session_id, organization_id=organization_id
            )
        return state

    async def _start_session(
        self, session_id: str, params: dict[str, Any], organization_id: str = LEGACY_ORG_ID
    ) -> None:
        """Handshake: capture the user's request and build the intent anchor."""
        state = self._session(session_id, organization_id)
        raw_request = _extract_user_request(params)

        granted = params.get("capabilities", {})
        if isinstance(granted, dict):
            tools = granted.get("tools")
            if isinstance(tools, list):
                self._graph.grant_capabilities(session_id, {str(tool) for tool in tools})

        agent_id = await self._resolve_agent(session_id, params, state)
        state.agent_id = agent_id

        if raw_request:
            anchor = await self._anchors.generate(session_id, raw_request)
            await self._graph.add_user_request(anchor, organization_id=state.organization_id)
            self._recorder.record_run_start(
                RunSummary(
                    session_id=session_id,
                    started_at=state.started_at,
                    intent_summary=anchor.goal,
                    agent_id=agent_id,
                ),
                organization_id=state.organization_id,
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

    async def _resolve_agent(
        self, session_id: str, params: dict[str, Any], state: SessionState
    ) -> str | None:
        """Look up (or create) the Agent row this session should be attributed to.

        No `database` (unit tests that build MCPProxy without one) means
        agent resolution is simply skipped — every run keeps working exactly
        as before, just unattributed.
        """
        if self._database is None:
            return None

        agent_identity = _extract_agent_identity(params)
        explicit_name: str | None = agent_identity
        if not agent_identity:
            granted = sorted(self._graph.granted_capabilities(session_id) or set())
            basis = ",".join(granted) if granted else session_id
            agent_identity = hashlib.sha256(basis.encode("utf-8")).hexdigest()
            explicit_name = None

        async with self._database.session(state.organization_id) as session:
            existing = await session.scalar(
                select(Agent).where(
                    Agent.organization_id == state.organization_id,
                    Agent.agent_identity == agent_identity,
                )
            )
            if existing is not None:
                return str(existing.id)

            new_agent = Agent(
                id=str(uuid.uuid4()),
                organization_id=state.organization_id,
                name=explicit_name or agent_identity,
                agent_identity=agent_identity,
            )
            session.add(new_agent)
            await session.flush()
            return str(new_agent.id)

    async def end_session(self, session_id: str) -> RunSummary | None:
        """Write the closing summary and release per-session state."""
        state = self._sessions.pop(session_id, None)
        if state is None:
            return None

        # Audit writes are queued off the hot path, so the summary's counts
        # would race with the drain task without this flush.
        await self._recorder.flush()
        events = await self._recorder.get_events(session_id, state.organization_id)
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
            agent_id=state.agent_id,
        )
        self._recorder.record_run_end(summary, organization_id=state.organization_id)
        agent_identity: str | None = None
        if state.agent_id is not None:
            agent_identity = await self._update_agent_aggregates(
                state.agent_id, state.organization_id, summary
            )
        if self._trajectory_recorder is not None:
            # Fire-and-forget in spirit, awaited-but-caught in practice --
            # matches this codebase's existing style for session-end
            # side effects (_update_agent_aggregates above): the write
            # itself already catches and logs everything internally, so
            # awaiting it here cannot fail or block end_session beyond the
            # write's own latency.
            audit_events = [_to_audit_event(event) for event in events]
            await self._trajectory_recorder.record_session(
                session_id,
                audit_events,
                summary,
                organization_id=state.organization_id,
                agent_identity=agent_identity,
            )
        self._interceptor.release_session(session_id)
        logger.info(
            "proxy.session_ended",
            session_id=session_id,
            total_steps=summary.total_steps,
            final_status=summary.final_status,
            max_drift_score=round(summary.max_drift_score, 2),
        )
        return summary

    async def _update_agent_aggregates(
        self, agent_id: str, organization_id: str, summary: RunSummary
    ) -> str | None:
        """Roll this finished run's outcome into its Agent row.

        `risk_score` is set from `max_drift_score` as a simplification: wiring
        in the real Feature-2 multi-dimensional risk aggregate here would
        require plumbing that engine's per-run result through end_session,
        which only has the audit RunSummary in scope today. Tracked as a
        follow-up, not silently dropped.

        Returns the agent's `agent_identity` string (Feature 7 wants this,
        not the Agent row's opaque id, for TrajectoryRecord.agent_identity)
        so end_session can pass it along without a second lookup.
        """
        if self._database is None:
            return None
        async with self._database.session(organization_id) as session:
            agent = await session.get(Agent, agent_id)
            if agent is None:
                return None
            agent.total_runs += 1
            if summary.blocked_count > 0:
                agent.total_blocked += 1
            if summary.escalated_count > 0:
                agent.total_escalated += 1
            agent.avg_drift_score = 0.1 * summary.max_drift_score + 0.9 * agent.avg_drift_score
            agent.risk_score = summary.max_drift_score
            agent.last_seen_at = utcnow()
            return str(agent.agent_identity)

    # ---- Request handling -------------------------------------------------

    async def handle(
        self,
        request: MCPRequest,
        session_id: str,
        hitl_token: str | None = None,
        organization_id: str = LEGACY_ORG_ID,
    ) -> tuple[MCPResponse, dict[str, str]]:
        """Adjudicate and route one JSON-RPC request. Returns response + headers.

        organization_id is resolved once by the caller (create_proxy_router's
        mcp_endpoint, from the authenticated request) and only takes effect
        the first time a given session_id is seen — every later call for the
        same session reuses the org recorded on that session's SessionState,
        so a session can never be reassigned to a different tenant mid-run.
        """
        headers: dict[str, str] = {"X-Ariadne-Session-Id": session_id}

        if request.method == "initialize":
            # Only a genuinely new session counts against the quota -- a
            # reconnect replaying the handshake for a session already in
            # self._sessions must not be double-charged or blocked by usage
            # it already incurred.
            if self._quotas is not None and session_id not in self._sessions:
                quota = await self._quotas.check_session_quota(organization_id)
                if not quota.allowed:
                    logger.warning(
                        "proxy.session_quota_exceeded",
                        session_id=session_id,
                        organization_id=organization_id,
                        limit=quota.limit,
                        used=quota.used,
                    )
                    return (
                        MCPResponse.failure(
                            request.id,
                            JSONRPCErrorCode.ARIADNE_QUOTA_EXCEEDED,
                            f"Monthly session quota exceeded ({quota.used}/{quota.limit})",
                            _quota_payload(quota),
                        ),
                        headers,
                    )
            await self._start_session(session_id, request.params, organization_id)
            response = await self._forward(request, session_id)
            return response, headers

        if request.method in SESSION_END_METHODS:
            await self.end_session(session_id)
            return MCPResponse.ok(request.id, {"ok": True}), headers

        if request.method not in TOOL_CALL_METHODS:
            # Discovery and notification traffic carries no action to adjudicate.
            return await self._forward(request, session_id), headers

        return await self._handle_tool_call(
            request, session_id, hitl_token, headers, organization_id
        )

    async def _handle_tool_call(
        self,
        request: MCPRequest,
        session_id: str,
        hitl_token: str | None,
        headers: dict[str, str],
        organization_id: str = LEGACY_ORG_ID,
    ) -> tuple[MCPResponse, dict[str, str]]:
        state = self._session(session_id, organization_id)

        if self._quotas is not None:
            quota = await self._quotas.check_tool_call_quota(state.organization_id)
            if not quota.allowed:
                logger.warning(
                    "proxy.tool_call_quota_exceeded",
                    session_id=session_id,
                    organization_id=state.organization_id,
                    limit=quota.limit,
                    used=quota.used,
                )
                return (
                    MCPResponse.failure(
                        request.id,
                        JSONRPCErrorCode.ARIADNE_QUOTA_EXCEEDED,
                        f"Monthly tool-call quota exceeded ({quota.used}/{quota.limit})",
                        _quota_payload(quota),
                    ),
                    headers,
                )

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
        await self._record_result(response, tool_call, result, state.organization_id)
        return response, headers

    async def _await_human_approval(self, tool_call: ToolCall, result: InterceptionResult) -> bool:
        """POST to the HITL webhook and wait. Timeout means deny.

        The dashboard's Pending Approvals panel is a *view* onto the same
        registry a webhook resolves through `POST /mcp/hitl/{approval_id}` —
        it does not change this method's fail-fast behaviour when no webhook
        is configured at all (tests and unattended deployments rely on that
        instant deny; waiting on a human who may never look would hang every
        ESCALATE for the full HITL_TIMEOUT_SECONDS).
        """
        if not self._settings.hitl_webhook_url:
            logger.warning(
                "proxy.hitl_not_configured",
                session_id=tool_call.session_id,
                step_index=tool_call.step_index,
                resolved="deny",
                hint="set HITL_WEBHOOK_URL to enable human approval",
            )
            return False

        approval_id, future = self._approvals.open(
            {
                "session_id": tool_call.session_id,
                "step_index": tool_call.step_index,
                "tool_name": tool_call.tool_name,
                "arguments": tool_call.arguments,
                "reason": result.reason,
                "drift_score": result.drift_score,
                "triggered_rule": result.triggered_rule,
                "node_id": result.graph_node_id,
                "opened_at": utcnow().isoformat(),
            }
        )
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
        self,
        response: MCPResponse,
        tool_call: ToolCall,
        result: InterceptionResult,
        organization_id: str = LEGACY_ORG_ID,
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
        await self._interceptor.record_result(
            tool_result, result.graph_node_id, organization_id
        )

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
        # Resolved from the authenticated caller only (require_api_key
        # middleware already ran) — never from the request body, or a
        # caller could hand any org_id it likes.
        from ariadne.auth.org_scope import require_org_scope  # noqa: PLC0415

        organization_id = await require_org_scope(request)
        response, headers = await proxy.handle(
            rpc_request, session_id, x_ariadne_hitl_token, organization_id
        )
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


def _extract_agent_identity(params: dict[str, Any]) -> str | None:
    for key in AGENT_IDENTITY_KEYS:
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    client_info = params.get("clientInfo")
    if isinstance(client_info, dict):
        name = client_info.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else ({} if value is None else {"value": value})


def _quota_payload(quota: QuotaCheckResult) -> dict[str, Any]:
    return {
        "ariadne": {
            "action": "QUOTA_EXCEEDED",
            "limit": quota.limit,
            "used": quota.used,
            "period_start": quota.period_start.isoformat(),
        }
    }


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
