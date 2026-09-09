# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Provenance graph persistence: in-process NetworkX or an ArcadeDB server."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol, runtime_checkable

import networkx as nx

from ariadne.config import Settings, get_settings
from ariadne.db.models import LEGACY_ORG_ID
from ariadne.graph.schemas import EdgeType, GraphEdge, GraphNode, NodeType
from ariadne.graph.traversal import blast_radius_ids, root_cause_chain_ids
from ariadne.logging import get_logger

logger = get_logger(__name__)


@runtime_checkable
class GraphStoreInterface(Protocol):
    """The contract both backends satisfy."""

    async def add_node(self, node: GraphNode) -> str: ...

    async def add_edge(self, edge: GraphEdge) -> str: ...

    async def get_node(self, node_id: str) -> GraphNode | None: ...

    async def update_node_action(
        self, node_id: str, action: str, drift_score: float | None = None
    ) -> None: ...

    async def get_session_graph(
        self, session_id: str, organization_id: str = LEGACY_ORG_ID
    ) -> tuple[list[GraphNode], list[GraphEdge]]: ...

    async def root_cause_walk(
        self, node_id: str, max_depth: int = 10, organization_id: str = LEGACY_ORG_ID
    ) -> list[GraphNode]: ...

    async def blast_radius(
        self, node_id: str, max_depth: int = 10, organization_id: str = LEGACY_ORG_ID
    ) -> list[GraphNode]: ...

    async def list_sessions(self) -> list[str]: ...

    async def close(self) -> None: ...


class NetworkXGraphStore:
    """In-memory directed graph, one connected component per session.

    Default backend: it needs no external service, keeps the whole run in
    process for sub-millisecond traversal on the hot path, and serialises to
    JSON for persistence alongside the audit trail.
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph[str] = nx.DiGraph()
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}
        self._sessions: dict[str, list[str]] = {}
        self._lock = asyncio.Lock()

    @property
    def backend(self) -> str:
        return "networkx"

    async def add_node(self, node: GraphNode) -> str:
        async with self._lock:
            self._nodes[node.id] = node
            self._graph.add_node(
                node.id, node_type=node.node_type.value, step_index=node.step_index
            )
            self._sessions.setdefault(node.session_id, []).append(node.id)
        return node.id

    async def add_edge(self, edge: GraphEdge) -> str:
        async with self._lock:
            if edge.source_id not in self._nodes or edge.target_id not in self._nodes:
                raise KeyError(
                    f"cannot add edge {edge.edge_type.value}: "
                    f"unknown endpoint(s) {edge.source_id} -> {edge.target_id}"
                )
            self._edges[edge.id] = edge
            # A pair of nodes can carry several relationship kinds (a call both
            # follows from and contradicts an earlier one), so parallel edges
            # are kept in a list on the single DiGraph edge.
            existing: list[str] = self._graph.edges.get((edge.source_id, edge.target_id), {}).get(
                "edge_ids", []
            )
            self._graph.add_edge(edge.source_id, edge.target_id, edge_ids=[*existing, edge.id])
        return edge.id

    async def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    async def update_node_action(
        self, node_id: str, action: str, drift_score: float | None = None
    ) -> None:
        node = self._nodes.get(node_id)
        if node is None:
            return
        node.enforcement_action = action
        if drift_score is not None:
            node.drift_score = drift_score

    async def get_session_graph(
        self, session_id: str, organization_id: str = LEGACY_ORG_ID
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        node_ids = {
            node_id
            for node_id in self._sessions.get(session_id, [])
            if self._nodes[node_id].organization_id == organization_id
        }
        nodes = [self._nodes[node_id] for node_id in node_ids]
        edges = [
            edge
            for edge in self._edges.values()
            if edge.source_id in node_ids and edge.target_id in node_ids
        ]
        nodes.sort(key=lambda node: (node.step_index, node.timestamp))
        return nodes, edges

    async def root_cause_walk(
        self, node_id: str, max_depth: int = 10, organization_id: str = LEGACY_ORG_ID
    ) -> list[GraphNode]:
        entry = self._nodes.get(node_id)
        if entry is None or entry.organization_id != organization_id:
            # Unknown node, or it belongs to another org: behave exactly like
            # "not found" — never distinguish the two, or node_id guessing
            # becomes a cross-org existence oracle.
            return []
        chain = root_cause_chain_ids(self._graph, self._edges, node_id, max_depth)
        return [
            self._nodes[identifier]
            for identifier in chain
            if identifier in self._nodes
            and self._nodes[identifier].organization_id == organization_id
        ]

    async def blast_radius(
        self, node_id: str, max_depth: int = 10, organization_id: str = LEGACY_ORG_ID
    ) -> list[GraphNode]:
        entry = self._nodes.get(node_id)
        if entry is None or entry.organization_id != organization_id:
            return []
        reachable = blast_radius_ids(self._graph, node_id, max_depth)
        nodes = [
            self._nodes[identifier]
            for identifier in reachable
            if identifier in self._nodes
            and self._nodes[identifier].organization_id == organization_id
        ]
        nodes.sort(key=lambda node: (node.step_index, node.timestamp))
        return nodes

    async def list_sessions(self) -> list[str]:
        return list(self._sessions.keys())

    async def to_json(self, session_id: str) -> str:
        """Serialise one session's subgraph for archival."""
        nodes, edges = await self.get_session_graph(session_id)
        return json.dumps(
            {
                "session_id": session_id,
                "nodes": [node.model_dump(mode="json", by_alias=True) for node in nodes],
                "edges": [edge.model_dump(mode="json", by_alias=True) for edge in edges],
            },
            indent=2,
        )

    async def drop_session(self, session_id: str) -> None:
        async with self._lock:
            for node_id in self._sessions.pop(session_id, []):
                self._nodes.pop(node_id, None)
                if self._graph.has_node(node_id):
                    self._graph.remove_node(node_id)
            self._edges = {
                edge_id: edge
                for edge_id, edge in self._edges.items()
                if edge.source_id in self._nodes and edge.target_id in self._nodes
            }

    async def close(self) -> None:
        return None


class ArcadeDBGraphStore:
    """ArcadeDB-backed store for durable, cross-process provenance.

    Activated only when ARCADEDB_URL is set. Uses the HTTP API directly rather
    than the driver package so the dependency stays optional; every call has a
    defined failure mode and the caller can fall back to NetworkX.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        import httpx  # noqa: PLC0415

        self._settings = settings or get_settings()
        if not self._settings.arcadedb_url:
            raise ValueError("ARCADEDB_URL must be set to use the ArcadeDB graph store")
        self._base_url = self._settings.arcadedb_url.rstrip("/")
        self._database = self._settings.arcadedb_database
        self._client = httpx.AsyncClient(
            auth=(self._settings.arcadedb_user, self._settings.arcadedb_password),
            timeout=15.0,
        )
        self._ready = False
        self._lock = asyncio.Lock()

    @property
    def backend(self) -> str:
        return "arcadedb"

    async def _command(
        self, statement: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        import httpx  # noqa: PLC0415

        try:
            response = await self._client.post(
                f"{self._base_url}/api/v1/command/{self._database}",
                json={"language": "sql", "command": statement, "params": params or {}},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "graph.arcadedb_command_failed",
                status_code=exc.response.status_code,
                body=exc.response.text[:500],
                statement=statement[:200],
            )
            raise
        except httpx.HTTPError as exc:
            logger.error("graph.arcadedb_unreachable", error=str(exc), url=self._base_url)
            raise
        payload: dict[str, Any] = response.json()
        result: list[dict[str, Any]] = payload.get("result", [])
        return result

    async def ensure_schema(self) -> None:
        """Create the database plus one vertex/edge class per type."""
        async with self._lock:
            if self._ready:
                return
            import httpx  # noqa: PLC0415

            try:
                await self._client.post(
                    f"{self._base_url}/api/v1/server",
                    json={"command": f"create database {self._database}"},
                )
            except httpx.HTTPError:
                # Already exists, or the server manages databases externally.
                logger.debug("graph.arcadedb_database_exists", database=self._database)

            for node_type in NodeType:
                await self._command(f"CREATE VERTEX TYPE `{node_type.value}` IF NOT EXISTS")
            for edge_type in EdgeType:
                await self._command(f"CREATE EDGE TYPE `{edge_type.value}` IF NOT EXISTS")
            await self._command("CREATE PROPERTY `tool_call`.node_id STRING IF NOT EXISTS")
            self._ready = True
            logger.info("graph.arcadedb_schema_ready", database=self._database)

    async def add_node(self, node: GraphNode) -> str:
        await self.ensure_schema()
        await self._command(
            f"INSERT INTO `{node.node_type.value}` SET "
            "node_id = :node_id, session_id = :session_id, "
            "organization_id = :organization_id, step_index = :step_index, "
            "label = :label, payload = :payload, drift_score = :drift_score, "
            "enforcement_action = :enforcement_action, timestamp = :timestamp",
            {
                "node_id": node.id,
                "session_id": node.session_id,
                "organization_id": node.organization_id,
                "step_index": node.step_index,
                "label": node.label,
                "payload": json.dumps(node.payload, default=str),
                "drift_score": node.drift_score,
                "enforcement_action": node.enforcement_action,
                "timestamp": node.timestamp.isoformat(),
            },
        )
        return node.id

    async def add_edge(self, edge: GraphEdge) -> str:
        await self.ensure_schema()
        # The interpolated identifier is an EdgeType enum value, never user
        # input; every value in the statement is bound as a parameter.
        await self._command(
            f"CREATE EDGE `{edge.edge_type.value}` "  # noqa: S608
            "FROM (SELECT FROM V WHERE node_id = :source) "
            "TO (SELECT FROM V WHERE node_id = :target) "
            "SET edge_id = :edge_id",
            {"source": edge.source_id, "target": edge.target_id, "edge_id": edge.id},
        )
        return edge.id

    async def get_node(self, node_id: str) -> GraphNode | None:
        rows = await self._command(
            "SELECT FROM V WHERE node_id = :node_id LIMIT 1", {"node_id": node_id}
        )
        return _row_to_node(rows[0]) if rows else None

    async def update_node_action(
        self, node_id: str, action: str, drift_score: float | None = None
    ) -> None:
        """Persist the final verdict; nodes are written as PENDING before adjudication."""
        if drift_score is None:
            await self._command(
                "UPDATE V SET enforcement_action = :action WHERE node_id = :node_id",
                {"action": action, "node_id": node_id},
            )
            return
        await self._command(
            "UPDATE V SET enforcement_action = :action, drift_score = :drift_score "
            "WHERE node_id = :node_id",
            {"action": action, "drift_score": drift_score, "node_id": node_id},
        )

    async def get_session_graph(
        self, session_id: str, organization_id: str = LEGACY_ORG_ID
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        node_rows = await self._command(
            "SELECT FROM V WHERE session_id = :session_id AND organization_id = :organization_id "
            "ORDER BY step_index",
            {"session_id": session_id, "organization_id": organization_id},
        )
        nodes = [_row_to_node(row) for row in node_rows]
        node_ids = {node.id for node in nodes}
        edge_rows = await self._command(
            "SELECT edge_id, @type as edge_type, out.node_id as source_id, "
            "in.node_id as target_id FROM E"
        )
        edges = [
            GraphEdge(
                id=str(row.get("edge_id") or ""),
                source_id=str(row.get("source_id")),
                target_id=str(row.get("target_id")),
                edge_type=EdgeType(row.get("edge_type", EdgeType.CAUSED_BY.value)),
            )
            for row in edge_rows
            if row.get("source_id") in node_ids and row.get("target_id") in node_ids
        ]
        return nodes, edges

    async def root_cause_walk(
        self, node_id: str, max_depth: int = 10, organization_id: str = LEGACY_ORG_ID
    ) -> list[GraphNode]:
        entry_rows = await self._command(
            "SELECT FROM V WHERE node_id = :node_id LIMIT 1", {"node_id": node_id}
        )
        if not entry_rows or entry_rows[0].get("organization_id") != organization_id:
            return []
        rows = await self._command(
            "SELECT FROM (TRAVERSE in('caused_by') FROM "
            "(SELECT FROM V WHERE node_id = :node_id) MAXDEPTH :depth)",
            {"node_id": node_id, "depth": max_depth},
        )
        nodes = [
            _row_to_node(row) for row in rows if row.get("organization_id") == organization_id
        ]
        nodes.sort(key=lambda node: node.step_index, reverse=True)
        return nodes

    async def blast_radius(
        self, node_id: str, max_depth: int = 10, organization_id: str = LEGACY_ORG_ID
    ) -> list[GraphNode]:
        entry_rows = await self._command(
            "SELECT FROM V WHERE node_id = :node_id LIMIT 1", {"node_id": node_id}
        )
        if not entry_rows or entry_rows[0].get("organization_id") != organization_id:
            return []
        rows = await self._command(
            "SELECT FROM (TRAVERSE out() FROM "
            "(SELECT FROM V WHERE node_id = :node_id) MAXDEPTH :depth)",
            {"node_id": node_id, "depth": max_depth},
        )
        nodes = [
            _row_to_node(row)
            for row in rows
            if row.get("node_id") != node_id and row.get("organization_id") == organization_id
        ]
        nodes.sort(key=lambda node: node.step_index)
        return nodes

    async def list_sessions(self) -> list[str]:
        rows = await self._command("SELECT DISTINCT(session_id) as session_id FROM V")
        return [str(row["session_id"]) for row in rows if row.get("session_id")]

    async def close(self) -> None:
        await self._client.aclose()


def _row_to_node(row: dict[str, Any]) -> GraphNode:
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {"raw": payload}
    return GraphNode(
        id=str(row.get("node_id", "")),
        session_id=str(row.get("session_id", "")),
        organization_id=str(row.get("organization_id") or LEGACY_ORG_ID),
        node_type=NodeType(row.get("@type") or row.get("node_type") or NodeType.TOOL_CALL.value),
        step_index=int(row.get("step_index", 0)),
        label=str(row.get("label", "")),
        payload=payload if isinstance(payload, dict) else {},
        drift_score=row.get("drift_score"),
        enforcement_action=row.get("enforcement_action"),
    )


async def create_graph_store(settings: Settings | None = None) -> GraphStoreInterface:
    """Build the configured store, falling back to NetworkX if ArcadeDB is down.

    An unreachable graph database must not take the firewall offline: losing
    durable provenance is recoverable, losing enforcement is not.
    """
    resolved = settings or get_settings()
    if resolved.graph_backend == "arcadedb":
        try:
            store = ArcadeDBGraphStore(resolved)
            await store.ensure_schema()
            logger.info("graph.store_ready", backend="arcadedb", url=resolved.arcadedb_url)
            return store
        except Exception as exc:  # noqa: BLE001 - any failure must degrade, not crash
            logger.error(
                "graph.arcadedb_init_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                fallback="networkx",
            )
    logger.info("graph.store_ready", backend="networkx")
    return NetworkXGraphStore()
