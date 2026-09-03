# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Soft layer: graduated response to drift scores."""

from __future__ import annotations

import pytest

from ariadne.config import Settings
from ariadne.drift.schemas import DriftScore
from ariadne.enforcement.schemas import EnforcementAction
from ariadne.enforcement.soft_layer import SoftDriftLayer


def score(value: float, slope: float = 0.0, distance: float = 0.5) -> DriftScore:
    return DriftScore(
        session_id="soft-layer-test",
        step_index=1,
        raw_distance=distance,
        slope=slope,
        drift_score=value,
        window_size=5,
    )


@pytest.fixture
def layer(settings: Settings) -> SoftDriftLayer:
    return SoftDriftLayer(settings)


class TestThresholdMapping:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0.0, EnforcementAction.ALLOW),
            (39.9, EnforcementAction.ALLOW),
            (40.0, EnforcementAction.WARN),
            (64.9, EnforcementAction.WARN),
            (65.0, EnforcementAction.ESCALATE),
            (84.9, EnforcementAction.ESCALATE),
            (85.0, EnforcementAction.BLOCK),
            (100.0, EnforcementAction.BLOCK),
        ],
    )
    def test_boundaries_are_inclusive_at_the_lower_edge(
        self, layer: SoftDriftLayer, value: float, expected: EnforcementAction
    ) -> None:
        action, reason = layer.evaluate(score(value))
        assert action is expected
        assert reason


class TestReasons:
    def test_reason_names_the_threshold_that_fired(self, layer: SoftDriftLayer) -> None:
        _, reason = layer.evaluate(score(90.0, slope=0.2))
        assert "85" in reason
        assert "block" in reason.lower()

    def test_reason_includes_slope_and_distance_for_triage(self, layer: SoftDriftLayer) -> None:
        _, reason = layer.evaluate(score(90.0, slope=0.21, distance=0.83))
        assert "+0.210" in reason
        assert "0.83" in reason

    def test_allow_reason_is_still_explanatory(self, layer: SoftDriftLayer) -> None:
        action, reason = layer.evaluate(score(10.0))
        assert action is EnforcementAction.ALLOW
        assert "normal range" in reason


class TestConfigurability:
    def test_custom_thresholds_are_honoured(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        strict = Settings(
            DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path.as_posix()}/t.db",
            DRIFT_SCORE_WARN=10,
            DRIFT_SCORE_ESCALATE=20,
            DRIFT_SCORE_BLOCK=30,
        )
        layer = SoftDriftLayer(strict)
        assert layer.evaluate(score(35.0))[0] is EnforcementAction.BLOCK
        assert layer.evaluate(score(25.0))[0] is EnforcementAction.ESCALATE
        assert layer.evaluate(score(15.0))[0] is EnforcementAction.WARN
        assert layer.evaluate(score(5.0))[0] is EnforcementAction.ALLOW

    def test_thresholds_are_reported_for_the_dashboard(self, layer: SoftDriftLayer) -> None:
        assert layer.thresholds() == {"warn": 40.0, "escalate": 65.0, "block": 85.0}

    def test_out_of_order_thresholds_are_rejected(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A misconfiguration that would make ESCALATE unreachable must not start."""
        with pytest.raises(ValueError, match="warn <= escalate <= block"):
            Settings(
                DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path.as_posix()}/t.db",
                DRIFT_SCORE_WARN=90,
                DRIFT_SCORE_ESCALATE=50,
                DRIFT_SCORE_BLOCK=60,
            )
