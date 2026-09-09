# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Multi-dimensional risk engine: intent, tool, privilege, identity, data."""

from __future__ import annotations

import pytest

from ariadne.config import Settings
from ariadne.drift.schemas import DriftScore
from ariadne.enforcement.risk_dimensions import RiskDimensionScorer, static_base_risk
from ariadne.graph.builder import ProvenanceGraphBuilder
from ariadne.graph.store import NetworkXGraphStore
from ariadne.intent.anchor import IntentAnchor
from ariadne.proxy.schemas import ToolCall


def make_tool_call(
    tool_name: str,
    arguments: dict[str, object] | None = None,
    calling_agent_id: str = "agent-1",
    session_id: str = "sess-1",
) -> ToolCall:
    return ToolCall(
        session_id=session_id,
        step_index=1,
        tool_name=tool_name,
        arguments=arguments or {},
        calling_agent_id=calling_agent_id,
    )


def make_drift_score(value: float, session_id: str = "sess-1") -> DriftScore:
    return DriftScore(
        session_id=session_id,
        step_index=1,
        raw_distance=0.3,
        slope=0.0,
        drift_score=value,
        window_size=5,
    )


@pytest.fixture
def scorer(settings: Settings) -> RiskDimensionScorer:
    return RiskDimensionScorer(settings)


@pytest.fixture
def graph_builder(settings: Settings) -> ProvenanceGraphBuilder:
    return ProvenanceGraphBuilder(NetworkXGraphStore(), settings)


class TestStaticBaseRisk:
    def test_high_risk_markers_score_high(self) -> None:
        assert static_base_risk("delete_production_database") >= 60.0
        assert static_base_risk("send_email") >= 60.0

    def test_low_risk_markers_score_low(self) -> None:
        assert static_base_risk("read_file") <= 20.0
        assert static_base_risk("list_users") <= 20.0

    def test_unknown_tool_gets_the_neutral_baseline(self) -> None:
        assert static_base_risk("process_data") == 35.0


class TestCleanCallScoresLow:
    @pytest.mark.asyncio
    async def test_clean_read_only_call_scores_low_across_dimensions(
        self, scorer: RiskDimensionScorer, graph_builder: ProvenanceGraphBuilder
    ) -> None:
        tool_call = make_tool_call("read_file", {"path": "/tmp/report.txt"})
        drift_score = make_drift_score(5.0)
        report = await scorer.score_all(tool_call, None, drift_score, graph_builder, None)

        assert report.intent.label == "aligned"
        assert report.tool.label == "aligned"
        assert report.privilege.label == "aligned"
        assert report.data.label == "aligned"
        assert report.aggregate < 30.0


class TestToolDimension:
    @pytest.mark.asyncio
    async def test_dangerous_tool_name_scores_high_on_tool_dimension(
        self, scorer: RiskDimensionScorer, graph_builder: ProvenanceGraphBuilder
    ) -> None:
        tool_call = make_tool_call("delete_production_database")
        drift_score = make_drift_score(5.0)
        report = await scorer.score_all(tool_call, None, drift_score, graph_builder, None)

        assert report.tool.label == "critical"
        assert report.tool.value >= 60.0


class TestPrivilegeDimension:
    @pytest.mark.asyncio
    async def test_escalation_edge_in_recent_nodes_scores_high_on_privilege(
        self, scorer: RiskDimensionScorer, graph_builder: ProvenanceGraphBuilder
    ) -> None:
        session_id = "escalation-session"
        anchor = IntentAnchor(
            session_id=session_id,
            raw_text="Summarise last week's tickets.",
            embedding=__import__("numpy").zeros(384, dtype="float32"),
            goal="Summarise last week's tickets.",
        )
        await graph_builder.add_user_request(anchor)

        # A tool call whose name matches a PRIVILEGE_MARKER (see
        # ariadne/graph/builder.py) writes an ESCALATES_PRIVILEGE edge, since
        # the session never granted that capability.
        tool_call = make_tool_call("grant_admin_role", session_id=session_id)
        await graph_builder.add_tool_call(tool_call, None, enforcement_action="PENDING")

        drift_score = make_drift_score(5.0, session_id=session_id)
        report = await scorer.score_all(tool_call, anchor, drift_score, graph_builder, None)

        assert report.privilege.label == "critical"
        assert report.privilege.value >= 80.0


class TestDataDimension:
    @pytest.mark.asyncio
    async def test_prohibition_violation_scores_high_on_data_dimension(
        self, scorer: RiskDimensionScorer, graph_builder: ProvenanceGraphBuilder
    ) -> None:
        anchor = IntentAnchor(
            session_id="sess-data",
            raw_text="Summarise sales data. Do not send emails.",
            embedding=__import__("numpy").zeros(384, dtype="float32"),
            goal="Summarise sales data.",
            disallowed_actions=["send emails"],
        )
        tool_call = make_tool_call(
            "send_email", {"to": "finance@corp.com"}, session_id="sess-data"
        )
        drift_score = make_drift_score(5.0, session_id="sess-data")
        graph_builder_local = ProvenanceGraphBuilder(NetworkXGraphStore())
        report = await scorer.score_all(tool_call, anchor, drift_score, graph_builder_local, None)

        assert report.data.value >= 30.0
        # The email address in the arguments plus the prohibition violation
        # should push this well past "aligned".
        assert report.data.label in ("elevated", "critical")


class TestAggregateBounds:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tool_name", "drift_value", "args"),
        [
            ("read_file", 0.0, {}),
            ("delete_production_database", 100.0, {"token": "abc", "url": "http://evil.test"}),
            ("frobnicate", 50.0, {"email": "a@b.com"}),
            ("send_email", 70.0, {"to": "x@y.com", "secret": "s"}),
        ],
    )
    async def test_aggregate_is_always_within_bounds(
        self,
        scorer: RiskDimensionScorer,
        graph_builder: ProvenanceGraphBuilder,
        tool_name: str,
        drift_value: float,
        args: dict[str, object],
    ) -> None:
        tool_call = make_tool_call(tool_name, args)
        drift_score = make_drift_score(drift_value)
        report = await scorer.score_all(tool_call, None, drift_score, graph_builder, None)
        assert 0.0 <= report.aggregate <= 100.0


class TestWeightValidation:
    def test_weights_summing_to_one_are_accepted(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        settings = Settings(
            _env_file=None,
            DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path.as_posix()}/t.db",
            INTENT_WEIGHT=0.4,
            TOOL_WEIGHT=0.2,
            PRIVILEGE_WEIGHT=0.2,
            IDENTITY_WEIGHT=0.1,
            DATA_WEIGHT=0.1,
        )
        assert settings.intent_weight == 0.4

    def test_weights_not_summing_to_one_are_rejected(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(ValueError, match="must sum to 1.0"):
            Settings(
                _env_file=None,
                DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path.as_posix()}/t.db",
                INTENT_WEIGHT=0.5,
                TOOL_WEIGHT=0.5,
                PRIVILEGE_WEIGHT=0.5,
                IDENTITY_WEIGHT=0.1,
                DATA_WEIGHT=0.1,
            )
