# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""HybridEnforcementEngine: risk-dimension integration with the soft layer."""

from __future__ import annotations

import numpy as np
import pytest

from ariadne.config import Settings
from ariadne.drift.schemas import DriftScore
from ariadne.enforcement.engine import HybridEnforcementEngine
from ariadne.graph.builder import ProvenanceGraphBuilder
from ariadne.graph.store import NetworkXGraphStore
from ariadne.intent.anchor import IntentAnchor
from ariadne.proxy.schemas import ToolCall


def make_tool_call(tool_name: str, session_id: str, step_index: int = 1) -> ToolCall:
    return ToolCall(session_id=session_id, step_index=step_index, tool_name=tool_name)


def make_drift_score(value: float, session_id: str) -> DriftScore:
    return DriftScore(
        session_id=session_id,
        step_index=1,
        raw_distance=0.2,
        slope=0.0,
        drift_score=value,
        window_size=5,
    )


@pytest.fixture
def graph_builder(settings: Settings) -> ProvenanceGraphBuilder:
    return ProvenanceGraphBuilder(NetworkXGraphStore(), settings)


class TestRiskDimensionsDriveEnforcement:
    @pytest.mark.asyncio
    async def test_low_drift_but_graph_derived_privilege_escalation_still_blocks(
        self, settings: Settings, graph_builder: ProvenanceGraphBuilder
    ) -> None:
        """A call that looks fine to drift alone but carries a graph-level
        privilege-escalation edge must reach the same verdict a high drift
        score would -- proving max(drift, risk_aggregate) actually drives the
        soft layer through decide(), not just in isolation.
        """
        session_id = "privilege-integration-session"
        anchor = IntentAnchor(
            session_id=session_id,
            raw_text="Summarise last week's support tickets.",
            embedding=np.zeros(384, dtype=np.float32),
            goal="Summarise last week's support tickets.",
        )
        await graph_builder.add_user_request(anchor)

        # Matches a PRIVILEGE_MARKER in ariadne/graph/builder.py and the
        # session never granted this capability, so add_tool_call writes an
        # ESCALATES_PRIVILEGE edge.
        tool_call = make_tool_call("grant_admin_role", session_id)
        node = await graph_builder.add_tool_call(tool_call, None, enforcement_action="PENDING")

        engine = HybridEnforcementEngine(settings=settings)
        low_drift = make_drift_score(5.0, session_id)  # well under WARN (40)

        decision_with_risk = await engine.decide(
            tool_call,
            low_drift,
            tool_call_count=1,
            graph_node_id=node.id,
            intent_anchor=anchor,
            graph_builder=graph_builder,
        )

        # Drift alone (no graph_builder passed) would ALLOW at this score.
        decision_without_risk = await engine.decide(
            tool_call,
            low_drift,
            tool_call_count=1,
            graph_node_id=node.id,
        )

        assert decision_without_risk.action == "ALLOW"
        # The privilege dimension (critical, value ~90) pulled through the
        # weighted aggregate and max(drift, risk_aggregate) must push the
        # risk-aware decision to a stricter action than drift alone produces.
        assert decision_with_risk.action in ("WARN", "ESCALATE", "BLOCK")
        assert decision_with_risk.action != decision_without_risk.action

    @pytest.mark.asyncio
    async def test_risk_dimensions_are_recorded_in_the_audit_payload(
        self, settings: Settings, graph_builder: ProvenanceGraphBuilder
    ) -> None:
        session_id = "audit-payload-session"
        anchor = IntentAnchor(
            session_id=session_id,
            raw_text="Read the quarterly report.",
            embedding=np.zeros(384, dtype=np.float32),
            goal="Read the quarterly report.",
        )
        await graph_builder.add_user_request(anchor)
        tool_call = make_tool_call("read_file", session_id)
        node = await graph_builder.add_tool_call(tool_call, None, enforcement_action="PENDING")

        engine = HybridEnforcementEngine(settings=settings)
        drift = make_drift_score(5.0, session_id)
        decision = await engine.decide(
            tool_call,
            drift,
            tool_call_count=1,
            graph_node_id=node.id,
            intent_anchor=anchor,
            graph_builder=graph_builder,
        )

        assert decision.audit_event is not None
        assert "risk_dimensions" in decision.audit_event.payload
        assert decision.audit_event.payload["risk_dimensions"] is not None
        assert "aggregate" in decision.audit_event.payload["risk_dimensions"]

    @pytest.mark.asyncio
    async def test_omitting_graph_builder_skips_risk_scoring_and_records_none(
        self, settings: Settings
    ) -> None:
        session_id = "no-graph-session"
        tool_call = make_tool_call("read_file", session_id)
        engine = HybridEnforcementEngine(settings=settings)
        drift = make_drift_score(5.0, session_id)

        decision = await engine.decide(tool_call, drift, tool_call_count=1)

        assert decision.action == "ALLOW"
        assert decision.audit_event is not None
        assert decision.audit_event.payload["risk_dimensions"] is None
