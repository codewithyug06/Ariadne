# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Node and edge types for the execution provenance graph."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from ariadne.db.models import LEGACY_ORG_ID
from ariadne.proxy.schemas import utcnow


class EdgeType(str, Enum):
    CAUSED_BY = "caused_by"
    INFORMED_BY = "informed_by"
    CONTRADICTS = "contradicts"
    ESCALATES_PRIVILEGE = "escalates_privilege"
    PRODUCES = "produces"
    CALLS = "calls"


class NodeType(str, Enum):
    USER_REQUEST = "user_request"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    SUB_AGENT_INVOCATION = "sub_agent_invocation"
    MEMORY_WRITE = "memory_write"
    FINAL_OUTPUT = "final_output"
    ALERT = "alert"


def new_id() -> str:
    return str(uuid.uuid4())


class GraphNode(BaseModel):
    id: str = Field(default_factory=new_id)
    session_id: str
    # Defaults to the Legacy Org so every pre-Phase-1 call site (unit tests
    # constructing nodes directly, callers that haven't threaded a real
    # tenant through yet) keeps working unchanged; every genuinely
    # multi-tenant caller (the proxy, the builder's public methods) passes
    # the resolved organization_id explicitly.
    organization_id: str = LEGACY_ORG_ID
    node_type: NodeType
    step_index: int
    label: str
    payload: dict[str, Any] = Field(default_factory=dict)
    drift_score: float | None = None
    enforcement_action: str | None = None
    timestamp: datetime = Field(default_factory=utcnow)
    node_metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata")

    model_config = {"populate_by_name": True}


class GraphEdge(BaseModel):
    id: str = Field(default_factory=new_id)
    source_id: str
    target_id: str
    edge_type: EdgeType
    edge_metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata")

    model_config = {"populate_by_name": True}


class SessionGraph(BaseModel):
    """A whole session's graph, in the shape the dashboard consumes."""

    session_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    root_cause_node_id: str | None = None
