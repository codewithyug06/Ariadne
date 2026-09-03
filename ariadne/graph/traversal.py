# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Backward blame-chain and forward blast-radius walks over the provenance graph."""

from __future__ import annotations

from collections import deque

import networkx as nx

from ariadne.graph.schemas import EdgeType, GraphEdge, GraphNode, NodeType

#: Relationships that carry causal responsibility backwards. `informed_by` is
#: included because a poisoned tool result informs the action it corrupts —
#: that is exactly the link a root-cause walk must not lose.
CAUSAL_EDGE_TYPES = frozenset({EdgeType.CAUSED_BY, EdgeType.INFORMED_BY, EdgeType.PRODUCES})


def root_cause_chain_ids(
    graph: nx.DiGraph[str],
    edges: dict[str, GraphEdge],
    node_id: str,
    max_depth: int = 10,
) -> list[str]:
    """Walk backwards along causal edges from `node_id`.

    Returns the blame chain starting at `node_id` and ending at the deepest
    ancestor reached, ordered newest-first. Cycles cannot occur in a valid
    execution graph but are guarded against anyway, since edge inference is
    heuristic and a bad edge should not hang the proxy.
    """
    if node_id not in graph:
        return []

    chain: list[str] = [node_id]
    visited: set[str] = {node_id}
    frontier = deque([(node_id, 0)])

    while frontier:
        current, depth = frontier.popleft()
        if depth >= max_depth:
            continue
        for predecessor in graph.predecessors(current):
            if predecessor in visited:
                continue
            if not _has_causal_edge(graph, edges, predecessor, current):
                continue
            visited.add(predecessor)
            chain.append(predecessor)
            frontier.append((predecessor, depth + 1))

    return chain


def _has_causal_edge(
    graph: nx.DiGraph[str], edges: dict[str, GraphEdge], source: str, target: str
) -> bool:
    edge_ids: list[str] = graph.edges[source, target].get("edge_ids", [])
    return any(
        edges[edge_id].edge_type in CAUSAL_EDGE_TYPES for edge_id in edge_ids if edge_id in edges
    )


def blast_radius_ids(graph: nx.DiGraph[str], node_id: str, max_depth: int = 10) -> list[str]:
    """Every node downstream of `node_id` — what blocking it would have prevented.

    Follows all outgoing edge types, not just causal ones: an action that
    merely informed a later step still had reach, and an operator triaging an
    incident needs the full footprint.
    """
    if node_id not in graph:
        return []

    reachable: list[str] = []
    visited: set[str] = {node_id}
    frontier = deque([(node_id, 0)])

    while frontier:
        current, depth = frontier.popleft()
        if depth >= max_depth:
            continue
        for successor in graph.successors(current):
            if successor in visited:
                continue
            visited.add(successor)
            reachable.append(successor)
            frontier.append((successor, depth + 1))

    return reachable


def find_root_cause(nodes: list[GraphNode], warn_threshold: float) -> GraphNode | None:
    """The origin of a blame chain — what turns "step 7 was blocked" into
    "step 2 poisoned the run", which is the answer an incident responder needs.

    Two rules, in order:

    1. **The earliest untrusted input that precedes the drift.** Injections
       arrive in tool *results*, not in the agent's own calls, and the result
       that carries one is rarely anomalous by itself — a poisoned vendor
       profile looks like a vendor profile. Blaming the first step that scored
       badly therefore names a symptom several steps downstream of the cause.
       Where an earlier tool result exists in the chain, it is the better
       explanation.
    2. Otherwise, the earliest node whose drift crossed WARN.
    """
    if not nodes:
        return None

    scored = [
        node
        for node in nodes
        if node.drift_score is not None and node.drift_score >= warn_threshold
    ]
    earliest_scored = min(scored, key=lambda node: node.step_index) if scored else None

    results = [node for node in nodes if node.node_type == NodeType.TOOL_RESULT]
    if results:
        earliest_result = min(results, key=lambda node: node.step_index)
        if earliest_scored is None or earliest_result.step_index <= earliest_scored.step_index:
            return earliest_result

    if earliest_scored is not None:
        return earliest_scored
    return min(nodes, key=lambda node: node.step_index)


def order_chain_newest_first(nodes: list[GraphNode]) -> list[GraphNode]:
    """Blame chains read naturally from the blocked step backwards."""
    return sorted(nodes, key=lambda node: node.step_index, reverse=True)
