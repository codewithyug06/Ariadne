# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the deterministic drift narrative engine."""

from __future__ import annotations

from ariadne.drift.narrative import DriftNarrator
from ariadne.drift.schemas import DriftScore
from ariadne.drift.window import SlidingWindow
from ariadne.graph.schemas import EdgeType, GraphNode, NodeType

SESSION = "session-1"


def _score(value: float, slope: float = 0.0) -> DriftScore:
    return DriftScore(
        session_id=SESSION,
        step_index=1,
        raw_distance=0.5,
        slope=slope,
        drift_score=value,
        window_size=5,
    )


def _window(distances: list[float] | None = None) -> SlidingWindow:
    window = SlidingWindow(SESSION, max_size=5)
    for i, distance in enumerate(distances or []):
        window.push(i, distance)
    return window


def test_low_score_is_aligned() -> None:
    narrator = DriftNarrator()
    narrative = narrator.narrate(SESSION, 1, _score(39.9), _window(), [], "ALLOW", None)
    assert narrative.summary == "Action aligns with stated intent."
    assert narrative.detail is None
    assert narrative.trigger is None


def test_elevated_stabilising_slope() -> None:
    narrator = DriftNarrator()
    narrative = narrator.narrate(SESSION, 1, _score(50.0, slope=-0.1), _window(), [], "WARN", None)
    assert "stabilising" in narrative.summary
    assert narrative.detail is None


def test_elevated_rising_slope() -> None:
    narrator = DriftNarrator()
    window = _window([0.1, 0.2, 0.3, 0.4])
    narrative = narrator.narrate(SESSION, 4, _score(64.0, slope=0.1), window, [], "WARN", None)
    assert "rising over" in narrative.summary
    assert narrative.detail is not None
    assert "consecutive steps" in narrative.detail


def test_significant_escalating_drift() -> None:
    narrator = DriftNarrator()
    narrative = narrator.narrate(SESSION, 5, _score(70.0, slope=0.2), _window(), [], "ESCALATE", 2)
    assert "requires review" in narrative.summary
    assert narrative.detail is not None
    assert "step 2" in narrative.detail


def test_block_tier() -> None:
    narrator = DriftNarrator()
    window = _window([0.1, 0.2, 0.3, 0.4, 0.5])
    narrative = narrator.narrate(SESSION, 6, _score(90.0, slope=0.3), window, [], "BLOCK", 2)
    assert "Execution blocked" in narrative.summary
    assert narrative.detail is not None
    assert "Downstream actions prevented" in narrative.detail


def test_boundary_scores_never_raise() -> None:
    narrator = DriftNarrator()
    for boundary in (0.0, 39.9, 40.0, 64.0, 65.0, 84.0, 85.0, 100.0):
        narrative = narrator.narrate(
            SESSION, 1, _score(boundary), SlidingWindow(SESSION, max_size=2), [], "ALLOW", None
        )
        assert narrative.summary


def test_privilege_escalation_trigger() -> None:
    narrator = DriftNarrator()
    node = GraphNode(
        session_id=SESSION,
        node_type=NodeType.TOOL_CALL,
        step_index=1,
        label="grant_admin",
        node_metadata={"edge_types": [EdgeType.ESCALATES_PRIVILEGE.value]},
    )
    narrative = narrator.narrate(SESSION, 1, _score(70.0), _window(), [node], "ESCALATE", 1)
    assert narrative.trigger == "privilege escalation attempt"


def test_contradicts_trigger() -> None:
    narrator = DriftNarrator()
    node = GraphNode(
        session_id=SESSION,
        node_type=NodeType.TOOL_CALL,
        step_index=1,
        label="delete_file",
        node_metadata={
            "edge_types": [EdgeType.CONTRADICTS.value],
            "contradicted_constraint": "never delete files",
        },
    )
    narrative = narrator.narrate(SESSION, 1, _score(70.0), _window(), [node], "ESCALATE", 1)
    assert narrative.trigger == "action contradicts user constraint: 'never delete files'"


def test_tool_result_trigger() -> None:
    narrator = DriftNarrator()
    node = GraphNode(
        session_id=SESSION, node_type=NodeType.TOOL_RESULT, step_index=1, label="fetch result"
    )
    narrative = narrator.narrate(SESSION, 1, _score(70.0), _window(), [node], "ESCALATE", 1)
    assert narrative.trigger == "untrusted external tool result"


def test_sustained_lateral_movement_trigger() -> None:
    narrator = DriftNarrator()
    window = _window([0.1, 0.2, 0.3, 0.4])
    narrative = narrator.narrate(SESSION, 4, _score(70.0), window, [], "ESCALATE", 1)
    assert narrative.trigger == "sustained lateral movement away from stated goal"


def test_fallback_trigger() -> None:
    narrator = DriftNarrator()
    narrative = narrator.narrate(SESSION, 1, _score(70.0), _window(), [], "ESCALATE", 1)
    assert narrative.trigger == "cumulative semantic drift from original intent"


def test_never_raises_on_degenerate_inputs() -> None:
    narrator = DriftNarrator()
    narrative = narrator.narrate(
        "", -1, _score(0.0), SlidingWindow("x", max_size=2), [], "", None
    )
    assert narrative.summary
