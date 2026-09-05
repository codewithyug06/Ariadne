# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Incremental construction of the execution provenance graph."""

from __future__ import annotations

import json
from typing import Any

from ariadne.config import Settings, get_settings
from ariadne.db.models import LEGACY_ORG_ID
from ariadne.drift.schemas import DriftScore
from ariadne.graph.schemas import EdgeType, GraphEdge, GraphNode, NodeType, SessionGraph
from ariadne.graph.store import GraphStoreInterface
from ariadne.graph.traversal import find_root_cause, order_chain_newest_first
from ariadne.intent.anchor import IntentAnchor
from ariadne.logging import get_logger
from ariadne.proxy.schemas import ToolCall, ToolResult

logger = get_logger(__name__)

#: Tool-name and argument markers that indicate a capability grab. Kept here
#: rather than in the policy layer because the graph records the *relationship*
#: (this call escalates relative to the session) while the policy layer decides
#: what to do about it.
PRIVILEGE_MARKERS = (
    "admin",
    "root",
    "sudo",
    "grant",
    "permission",
    "role",
    "privilege",
    "escalat",
    "impersonate",
    "assume_role",
    "chmod",
    "chown",
    "policy_attach",
)

WRITE_MARKERS = (
    "write",
    "create",
    "update",
    "delete",
    "drop",
    "insert",
    "upsert",
    "send",
    "post",
    "put",
    "patch",
    "execute",
    "deploy",
    "purchase",
    "pay",
)


class ProvenanceGraphBuilder:
    """Adds nodes and edges to the graph as a run unfolds.

    One builder per process; session context is carried in arguments so a
    single instance safely serves concurrent sessions.
    """

    def __init__(self, store: GraphStoreInterface, settings: Settings | None = None) -> None:
        self._store = store
        self._settings = settings or get_settings()
        self._session_roots: dict[str, str] = {}
        self._last_call_node: dict[str, str] = {}
        self._granted_capabilities: dict[str, set[str]] = {}

    # ---- Node creation ----------------------------------------------------

    async def add_user_request(
        self, anchor: IntentAnchor, organization_id: str = LEGACY_ORG_ID
    ) -> GraphNode:
        """Root node: the request every later action is measured against."""
        node = GraphNode(
            session_id=anchor.session_id,
            organization_id=organization_id,
            node_type=NodeType.USER_REQUEST,
            step_index=0,
            label=_truncate(anchor.goal or anchor.raw_text, 120),
            payload={
                "raw_text": anchor.raw_text,
                "goal": anchor.goal,
                "constraints": anchor.constraints,
                "disallowed_actions": anchor.disallowed_actions,
                "risk_level": anchor.risk_level.value,
                "decomposition_source": anchor.decomposition_source,
            },
        )
        await self._store.add_node(node)
        self._session_roots[anchor.session_id] = node.id
        self._granted_capabilities.setdefault(anchor.session_id, set())
        logger.info(
            "graph.user_request_added",
            session_id=anchor.session_id,
            node_id=node.id,
        )
        return node

    async def add_tool_call(
        self,
        tool_call: ToolCall,
        drift_score: DriftScore | None,
        enforcement_action: str,
        anchor: IntentAnchor | None = None,
        organization_id: str = LEGACY_ORG_ID,
    ) -> GraphNode:
        """Add the call node plus every relationship it implies."""
        node = GraphNode(
            session_id=tool_call.session_id,
            organization_id=organization_id,
            node_type=NodeType.TOOL_CALL,
            step_index=tool_call.step_index,
            label=f"{tool_call.tool_name}()",
            payload={
                "tool_name": tool_call.tool_name,
                "arguments": _jsonable(tool_call.arguments),
                "calling_agent_id": tool_call.calling_agent_id,
                "stated_justification": tool_call.stated_justification,
                "natural_language": tool_call.to_natural_language(),
            },
            drift_score=drift_score.drift_score if drift_score else None,
            enforcement_action=enforcement_action,
            metadata={
                "slope": drift_score.slope if drift_score else None,
                "raw_distance": drift_score.raw_distance if drift_score else None,
            },
        )
        await self._store.add_node(node)

        await self._link_predecessor(tool_call.session_id, node)
        if anchor is not None:
            await self._infer_contradiction(anchor, tool_call, node)
        await self._infer_privilege_escalation(tool_call, node)

        self._last_call_node[tool_call.session_id] = node.id
        return node

    async def finalize_node(self, node: GraphNode, enforcement_action: str) -> None:
        """Write the adjudicated verdict onto a node in the store."""
        node.enforcement_action = enforcement_action
        await self._store.update_node_action(node.id, enforcement_action, node.drift_score)

    async def add_tool_result(
        self, tool_result: ToolResult, call_node_id: str, organization_id: str = LEGACY_ORG_ID
    ) -> GraphNode:
        """Result nodes are what make memory poisoning traceable."""
        node = GraphNode(
            session_id=tool_result.session_id,
            organization_id=organization_id,
            node_type=NodeType.TOOL_RESULT,
            step_index=tool_result.step_index,
            label=f"{tool_result.tool_name} -> {'error' if tool_result.is_error else 'ok'}",
            payload={
                "tool_name": tool_result.tool_name,
                "content": _jsonable(tool_result.content),
                "is_error": tool_result.is_error,
                "latency_ms": tool_result.latency_ms,
            },
        )
        await self._store.add_node(node)
        await self._store.add_edge(
            GraphEdge(source_id=call_node_id, target_id=node.id, edge_type=EdgeType.PRODUCES)
        )
        # The result informs whatever the agent does next; that edge is added
        # when the next call arrives (see _link_predecessor).
        self._last_call_node[tool_result.session_id] = node.id
        return node

    async def add_sub_agent_invocation(
        self,
        session_id: str,
        step_index: int,
        agent_id: str,
        prompt: str,
        organization_id: str = LEGACY_ORG_ID,
    ) -> GraphNode:
        node = GraphNode(
            session_id=session_id,
            organization_id=organization_id,
            node_type=NodeType.SUB_AGENT_INVOCATION,
            step_index=step_index,
            label=f"sub-agent {agent_id}",
            payload={"agent_id": agent_id, "prompt": _truncate(prompt, 2000)},
        )
        await self._store.add_node(node)
        await self._link_predecessor(session_id, node, EdgeType.CALLS)
        self._last_call_node[session_id] = node.id
        return node

    async def add_memory_write(
        self,
        session_id: str,
        step_index: int,
        key: str,
        value: Any,
        organization_id: str = LEGACY_ORG_ID,
    ) -> GraphNode:
        node = GraphNode(
            session_id=session_id,
            organization_id=organization_id,
            node_type=NodeType.MEMORY_WRITE,
            step_index=step_index,
            label=f"memory[{key}]",
            payload={"key": key, "value": _jsonable(value)},
        )
        await self._store.add_node(node)
        await self._link_predecessor(session_id, node)
        self._last_call_node[session_id] = node.id
        return node

    async def add_alert(
        self,
        session_id: str,
        step_index: int,
        reason: str,
        triggering_node_id: str,
        action: str,
        organization_id: str = LEGACY_ORG_ID,
    ) -> GraphNode:
        node = GraphNode(
            session_id=session_id,
            organization_id=organization_id,
            node_type=NodeType.ALERT,
            step_index=step_index,
            label=f"{action}: {_truncate(reason, 80)}",
            payload={"reason": reason, "action": action},
            enforcement_action=action,
        )
        await self._store.add_node(node)
        await self._store.add_edge(
            GraphEdge(
                source_id=triggering_node_id,
                target_id=node.id,
                edge_type=EdgeType.CAUSED_BY,
            )
        )
        return node

    async def add_final_output(
        self,
        session_id: str,
        step_index: int,
        output: str,
        organization_id: str = LEGACY_ORG_ID,
    ) -> GraphNode:
        node = GraphNode(
            session_id=session_id,
            organization_id=organization_id,
            node_type=NodeType.FINAL_OUTPUT,
            step_index=step_index,
            label="final output",
            payload={"output": _truncate(output, 4000)},
        )
        await self._store.add_node(node)
        await self._link_predecessor(session_id, node)
        return node

    # ---- Edge inference ---------------------------------------------------

    async def _link_predecessor(
        self, session_id: str, node: GraphNode, edge_type: EdgeType | None = None
    ) -> None:
        """Attach the node to whatever immediately preceded it in the run."""
        predecessor_id = self._last_call_node.get(session_id) or self._session_roots.get(session_id)
        if predecessor_id is None or predecessor_id == node.id:
            return
        predecessor = await self._store.get_node(predecessor_id)
        resolved_type = edge_type
        if resolved_type is None:
            # A result feeding the next action is `informed_by` — the edge that
            # carries injected content forward and makes it findable later.
            resolved_type = (
                EdgeType.INFORMED_BY
                if predecessor is not None and predecessor.node_type == NodeType.TOOL_RESULT
                else EdgeType.CAUSED_BY
            )
        await self._store.add_edge(
            GraphEdge(source_id=predecessor_id, target_id=node.id, edge_type=resolved_type)
        )

    async def _infer_contradiction(
        self, anchor: IntentAnchor, tool_call: ToolCall, node: GraphNode
    ) -> None:
        """Link an action back to the request it contradicts."""
        description = tool_call.to_natural_language()
        breached = anchor.violated_prohibitions(description)

        # A read-only mission plus a write-shaped tool is a contradiction even
        # when the user never spelled the prohibition out.
        read_only = any(
            "read" in constraint and "only" in constraint for constraint in anchor.constraints
        ) or any("read-only" in constraint for constraint in anchor.constraints)
        if read_only and any(marker in tool_call.tool_name.lower() for marker in WRITE_MARKERS):
            breached.append("read-only constraint")

        if not breached:
            return

        root_id = self._session_roots.get(tool_call.session_id)
        if root_id is None:
            return
        await self._store.add_edge(
            GraphEdge(
                source_id=node.id,
                target_id=root_id,
                edge_type=EdgeType.CONTRADICTS,
                metadata={"violated": breached},
            )
        )
        logger.warning(
            "graph.contradiction_detected",
            session_id=tool_call.session_id,
            step_index=tool_call.step_index,
            tool_name=tool_call.tool_name,
            violated=breached,
        )

    async def _infer_privilege_escalation(self, tool_call: ToolCall, node: GraphNode) -> None:
        """Mark calls that reach for capabilities the session never had."""
        haystack = f"{tool_call.tool_name} {json.dumps(_jsonable(tool_call.arguments))}".lower()
        markers = [marker for marker in PRIVILEGE_MARKERS if marker in haystack]
        if not markers:
            return

        granted = self._granted_capabilities.setdefault(tool_call.session_id, set())
        if tool_call.tool_name.lower() in granted:
            return

        root_id = self._session_roots.get(tool_call.session_id)
        if root_id is None:
            return
        await self._store.add_edge(
            GraphEdge(
                source_id=node.id,
                target_id=root_id,
                edge_type=EdgeType.ESCALATES_PRIVILEGE,
                metadata={"markers": markers},
            )
        )
        logger.warning(
            "graph.privilege_escalation_detected",
            session_id=tool_call.session_id,
            step_index=tool_call.step_index,
            tool_name=tool_call.tool_name,
            markers=markers,
        )

    # ---- Session bookkeeping ---------------------------------------------

    def grant_capabilities(self, session_id: str, capabilities: set[str]) -> None:
        """Record the tools a session was legitimately given at handshake."""
        self._granted_capabilities.setdefault(session_id, set()).update(
            capability.lower() for capability in capabilities
        )

    def granted_capabilities(self, session_id: str) -> set[str]:
        return set(self._granted_capabilities.get(session_id, set()))

    def root_node_id(self, session_id: str) -> str | None:
        return self._session_roots.get(session_id)

    def discard(self, session_id: str) -> None:
        self._session_roots.pop(session_id, None)
        self._last_call_node.pop(session_id, None)
        self._granted_capabilities.pop(session_id, None)

    # ---- Queries ----------------------------------------------------------

    async def session_graph(
        self, session_id: str, organization_id: str = LEGACY_ORG_ID
    ) -> SessionGraph:
        """The whole session, with the root cause resolved if one exists."""
        nodes, edges = await self._store.get_session_graph(session_id, organization_id)
        blocked = [node for node in nodes if node.enforcement_action == "BLOCK"]
        root_cause_id: str | None = None
        if blocked:
            chain = await self._store.root_cause_walk(
                blocked[0].id, organization_id=organization_id
            )
            root_cause = find_root_cause(chain, self._settings.drift_score_warn)
            root_cause_id = root_cause.id if root_cause else None
        return SessionGraph(
            session_id=session_id, nodes=nodes, edges=edges, root_cause_node_id=root_cause_id
        )

    async def blame_chain(
        self, node_id: str, max_depth: int = 10, organization_id: str = LEGACY_ORG_ID
    ) -> list[GraphNode]:
        chain = await self._store.root_cause_walk(node_id, max_depth, organization_id)
        return order_chain_newest_first(chain)

    async def blast_radius(
        self, node_id: str, max_depth: int = 10, organization_id: str = LEGACY_ORG_ID
    ) -> list[GraphNode]:
        return await self._store.blast_radius(node_id, max_depth, organization_id)


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _jsonable(value: Any) -> Any:
    """Coerce arbitrary tool payloads into something JSON-serialisable."""
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value
