# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Wire types for the MCP interception layer."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    """Timezone-aware UTC now. Used everywhere instead of the deprecated utcnow()."""
    return datetime.now(UTC)


class JSONRPCErrorCode(int, Enum):
    """JSON-RPC 2.0 codes plus Ariadne's reserved implementation-defined range."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    # -32000..-32099 is reserved for implementation-defined server errors.
    ARIADNE_BLOCKED = -32001
    ARIADNE_ESCALATION_DENIED = -32002
    ARIADNE_ESCALATION_TIMEOUT = -32003
    ARIADNE_UPSTREAM_ERROR = -32004


class ToolCall(BaseModel):
    """A single tool invocation observed on the wire."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    step_index: int
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    calling_agent_id: str = "unknown"
    stated_justification: str | None = None
    request_id: str | int | None = None
    timestamp: datetime = Field(default_factory=utcnow)

    def to_natural_language(self) -> str:
        """Render the call as the text that actually gets embedded.

        Deliberately written in the same register as a user's request — "send
        email to finance@corp.com" rather than "Agent called tool send_email
        with arguments ...". Measured against all-MiniLM-L6-v2, the boilerplate
        framing is shared by every action and dominates the embedding: it pulls
        all actions toward each other and away from the intent anchor, costing
        roughly 0.25 of cosine distance uniformly and collapsing the gap
        between on-mission and off-mission calls. Stripping it is the single
        largest accuracy win in the pipeline.

        Argument values are included because they carry most of the injection
        signal — a benign tool name with a hostile recipient address is the
        common shape.
        """
        verb = self.tool_name.replace("_", " ").replace("-", " ").strip()
        if self.arguments:
            values = ", ".join(_stringify(value) for _, value in sorted(self.arguments.items()))
            sentence = f"{verb}: {values}"
        else:
            sentence = verb
        if self.stated_justification:
            sentence += f" (in order to {self.stated_justification})"
        return sentence


def _stringify(value: Any, limit: int = 240) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


class ToolResult(BaseModel):
    """The upstream server's answer to a tool call."""

    session_id: str
    step_index: int
    tool_name: str
    content: Any = None
    is_error: bool = False
    latency_ms: float = 0.0
    timestamp: datetime = Field(default_factory=utcnow)

    def to_natural_language(self) -> str:
        verb = self.tool_name.replace("_", " ").strip()
        status = "error" if self.is_error else "result"
        return f"{verb} {status}: {_stringify(self.content, 512)}"


class MCPRequest(BaseModel):
    """Inbound JSON-RPC request from the orchestrator."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class MCPError(BaseModel):
    code: int
    message: str
    data: dict[str, Any] | None = None


class MCPResponse(BaseModel):
    """Outbound JSON-RPC response to the orchestrator."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    result: Any = None
    error: MCPError | None = None

    @classmethod
    def ok(cls, request_id: str | int | None, result: Any) -> MCPResponse:
        return cls(id=request_id, result=result)

    @classmethod
    def failure(
        cls,
        request_id: str | int | None,
        code: JSONRPCErrorCode,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> MCPResponse:
        return cls(id=request_id, error=MCPError(code=int(code), message=message, data=data))


class SessionState(BaseModel):
    """Per-session bookkeeping held by the proxy for the life of a run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    # Resolved once, at session establishment, from the authenticated
    # caller's credentials (see mcp_proxy.py::create_proxy_router) — never
    # from anything the client sends in params.
    organization_id: str = "00000000-0000-0000-0000-000000000000"
    started_at: datetime = Field(default_factory=utcnow)
    step_counter: int = 0
    tool_call_count: int = 0
    granted_capabilities: set[str] = Field(default_factory=set)
    last_node_id: str | None = None
    max_drift_score: float = 0.0
    warned: bool = False
    escalated: bool = False
    blocked: bool = False
    #: Step index of the first time this session's drift score crossed the
    #: WARN threshold. Set once, never reset — used by the narrative engine
    #: (ariadne.drift.narrative) to describe how long a run has been diverging.
    first_divergence_step: int | None = None
    #: Feature 3 (agent entity). Resolved once at session start (see
    #: mcp_proxy.py::_resolve_agent) — the Agent row this session's Run is
    #: attributed to, or None if resolution somehow failed.
    agent_id: str | None = None
    #: Feature 10 (contextual tool-risk scoring). Every ToolCall seen this
    #: session, in order, appended by the interceptor after each call is
    #: adjudicated. Used to compute session-novelty risk modifiers (first use
    #: of a tool, rapid repetition) -- see
    #: ariadne/enforcement/contextual_tool_risk.py. Unbounded for the life of
    #: a session, same tolerance-for-growth as the rest of SessionState (it
    #: already lives only in memory for one run, same as `warned`/`blocked`).
    tool_call_history: list[ToolCall] = Field(default_factory=list)

    def next_step(self) -> int:
        self.step_counter += 1
        return self.step_counter

    @property
    def final_status(self) -> str:
        if self.blocked:
            return "BLOCKED"
        if self.escalated:
            return "ESCALATED"
        if self.warned:
            return "WARNED"
        return "CLEAN"


class InterceptionResult(BaseModel):
    """Everything the interception pipeline learned about one tool call."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    step_index: int
    tool_name: str
    action: str
    reason: str
    drift_score: float | None = None
    slope: float | None = None
    raw_distance: float | None = None
    graph_node_id: str | None = None
    triggered_rule: str | None = None
    layer: str = "none"
    requires_hitl_token: bool = False
    latency_ms: float = 0.0
    degraded: bool = False

    @property
    def allowed(self) -> bool:
        return self.action in ("ALLOW", "WARN")
