# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Behavioural specification for the trajectory scorer.

The three cases below are the contract that distinguishes Ariadne from a
per-step cosine filter. If they regress, the detection thesis is broken even
if every other test still passes.
"""

from __future__ import annotations

import numpy as np
import pytest

from ariadne.config import Settings
from ariadne.drift.scorer import MIN_POINTS_FOR_SLOPE, TrajectoryScorer, cosine_similarity, sigmoid
from ariadne.drift.window import SlidingWindow
from ariadne.enforcement.schemas import EnforcementAction
from ariadne.enforcement.soft_layer import SoftDriftLayer


def _vector_at_distance(anchor: np.ndarray, distance: float, seed: int = 0) -> np.ndarray:
    """Build a unit vector whose cosine distance from `anchor` is exactly `distance`."""
    rng = np.random.default_rng(seed)
    orthogonal = rng.normal(size=anchor.shape).astype(np.float64)
    orthogonal -= anchor * float(np.dot(orthogonal, anchor))
    orthogonal /= np.linalg.norm(orthogonal)
    target_similarity = 1.0 - distance
    vector = target_similarity * anchor + np.sqrt(max(0.0, 1.0 - target_similarity**2)) * orthogonal
    return (vector / np.linalg.norm(vector)).astype(np.float32)


@pytest.fixture
def anchor_vector() -> np.ndarray:
    rng = np.random.default_rng(1234)
    vector = rng.normal(size=384)
    return (vector / np.linalg.norm(vector)).astype(np.float32)


def _run_sequence(
    scorer: TrajectoryScorer,
    anchor: np.ndarray,
    distances: list[float],
    window_size: int = 5,
) -> list[float]:
    window = SlidingWindow("seq", window_size)
    scores: list[float] = []
    for step, distance in enumerate(distances, start=1):
        action = _vector_at_distance(anchor, distance, seed=step)
        score = scorer.score(
            session_id="seq",
            intent_embedding=anchor,
            action_embedding=action,
            window=window,
            step_index=step,
        )
        # The constructed geometry must be accurate, or the case proves nothing.
        assert score.raw_distance == pytest.approx(distance, abs=1e-3)
        scores.append(score.drift_score)
    return scores


def _actions(scores: list[float], settings: Settings) -> list[str]:
    soft = SoftDriftLayer(settings)
    from ariadne.drift.schemas import DriftScore  # noqa: PLC0415

    results = []
    for index, score in enumerate(scores):
        action, _ = soft.evaluate(
            DriftScore(
                session_id="seq",
                step_index=index,
                raw_distance=0.0,
                slope=0.0,
                drift_score=score,
                window_size=5,
            )
        )
        results.append(action.value)
    return results


class TestCoreBehaviouralSpec:
    """The three cases from the design spec."""

    def test_flat_but_distant_sequence_does_not_block(
        self, scorer: TrajectoryScorer, anchor_vector: np.ndarray, settings: Settings
    ) -> None:
        """A research agent exploring laterally: high distance, zero slope.

        A naive per-step filter at threshold 0.5 flags every one of these.
        Ariadne must not block any of them.
        """
        distances = [0.62, 0.60, 0.63, 0.61, 0.62, 0.60]
        scores = _run_sequence(scorer, anchor_vector, distances)

        assert max(scores) < settings.drift_score_block, (
            f"flat trajectory reached {max(scores):.1f}, at or above the "
            f"{settings.drift_score_block:.0f} block threshold"
        )
        assert EnforcementAction.BLOCK.value not in _actions(scores, settings)

    def test_monotonically_escalating_sequence_blocks(
        self, scorer: TrajectoryScorer, anchor_vector: np.ndarray, settings: Settings
    ) -> None:
        """A slow-burn injection: each step further off-mission than the last."""
        distances = [0.15, 0.35, 0.55, 0.75, 0.92, 0.97]
        scores = _run_sequence(scorer, anchor_vector, distances)

        assert max(scores) >= settings.drift_score_block, (
            f"escalating trajectory peaked at {max(scores):.1f}, below the "
            f"{settings.drift_score_block:.0f} block threshold"
        )
        assert EnforcementAction.BLOCK.value in _actions(scores, settings)
        # Scores must rise with the escalation, not merely cross once.
        assert scores[-1] > scores[0]

    def test_spike_then_recovery_does_not_block(
        self, scorer: TrajectoryScorer, anchor_vector: np.ndarray, settings: Settings
    ) -> None:
        """One anomalous step, then back on mission: negative slope must forgive it."""
        distances = [0.12, 0.14, 0.78, 0.20, 0.13, 0.11]
        scores = _run_sequence(scorer, anchor_vector, distances)

        assert max(scores) < settings.drift_score_block
        assert EnforcementAction.BLOCK.value not in _actions(scores, settings)
        # The recovery must actually be scored lower than the spike.
        assert scores[-1] < scores[2]
        # Not blocking must not mean not noticing: the spike itself is still
        # flagged and recorded rather than silently allowed.
        assert _actions(scores, settings)[2] != EnforcementAction.ALLOW.value


class TestSlopeComputation:
    def test_returns_zero_below_minimum_points(self, scorer: TrajectoryScorer) -> None:
        assert scorer._compute_slope([]) == 0.0
        assert scorer._compute_slope([0.5]) == 0.0
        assert scorer._compute_slope([0.1, 0.9]) == 0.0
        assert MIN_POINTS_FOR_SLOPE == 3

    def test_positive_slope_for_rising_distances(self, scorer: TrajectoryScorer) -> None:
        assert scorer._compute_slope([0.1, 0.2, 0.3, 0.4]) == pytest.approx(0.1, abs=1e-9)

    def test_negative_slope_for_falling_distances(self, scorer: TrajectoryScorer) -> None:
        assert scorer._compute_slope([0.4, 0.3, 0.2, 0.1]) == pytest.approx(-0.1, abs=1e-9)

    def test_zero_slope_for_constant_distances(self, scorer: TrajectoryScorer) -> None:
        assert scorer._compute_slope([0.5, 0.5, 0.5, 0.5]) == 0.0


class TestComposite:
    def test_flat_trajectory_cannot_reach_block_on_distance_alone(
        self, scorer: TrajectoryScorer, settings: Settings
    ) -> None:
        """Maximum distance with zero slope must stay below BLOCK by design."""
        assert scorer._composite(1.0, 0.0) < settings.drift_score_block

    def test_bounded_to_range(self, scorer: TrajectoryScorer) -> None:
        assert scorer._composite(0.0, -100.0) >= 0.0
        assert scorer._composite(5.0, 100.0) <= 100.0

    def test_slope_increases_score_at_fixed_distance(self, scorer: TrajectoryScorer) -> None:
        flat = scorer._composite(0.5, 0.0)
        rising = scorer._composite(0.5, 0.2)
        falling = scorer._composite(0.5, -0.2)
        # A recovering trajectory scores the same as a flat one, not less:
        # the slope term is a penalty for escalation, never a discount.
        assert falling == flat < rising

    def test_flat_trajectory_scores_on_distance_alone(self, scorer: TrajectoryScorer) -> None:
        """No slope means no trajectory penalty — this is what kills false positives."""
        assert scorer._composite(0.5, 0.0) == pytest.approx(25.0)
        assert scorer._composite(0.0, 0.0) == pytest.approx(0.0)

    def test_configured_slope_threshold_is_the_half_power_point(
        self, scorer: TrajectoryScorer, settings: Settings
    ) -> None:
        """At exactly DRIFT_SLOPE_THRESHOLD the ramp contributes half its maximum.

        The ramp multiplies distance, so at distance d the score is
        50*d*(1 + 0.5) — half way between the flat score and the doubled one.
        """
        at_threshold = scorer._composite(0.8, settings.drift_slope_threshold)
        assert at_threshold == pytest.approx(50.0 * 0.8 * 1.5, abs=0.5)

    def test_slope_cannot_score_without_distance(self, scorer: TrajectoryScorer) -> None:
        """An escalating trajectory that stays on-mission is progress, not drift."""
        assert scorer._composite(0.0, 5.0) == 0.0
        assert scorer._composite(0.05, 5.0) < 10.0

    def test_maximum_score_needs_both_signals(self, scorer: TrajectoryScorer) -> None:
        assert scorer._composite(1.0, 5.0) == pytest.approx(100.0, abs=0.1)
        assert scorer._composite(1.0, 0.0) == pytest.approx(50.0)


class TestMathHelpers:
    def test_cosine_similarity_of_identical_vectors(self) -> None:
        vector = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        assert cosine_similarity(vector, vector) == pytest.approx(1.0)

    def test_cosine_similarity_of_orthogonal_vectors(self) -> None:
        assert cosine_similarity(
            np.array([1.0, 0.0], dtype=np.float32), np.array([0.0, 1.0], dtype=np.float32)
        ) == pytest.approx(0.0)

    def test_cosine_similarity_handles_zero_vector(self) -> None:
        assert cosine_similarity(np.zeros(3, dtype=np.float32), np.ones(3, dtype=np.float32)) == 0.0

    def test_sigmoid_is_stable_at_extremes(self) -> None:
        assert sigmoid(0.0) == pytest.approx(0.5)
        # Must underflow to zero rather than overflow in exp().
        assert 0.0 <= sigmoid(-800.0) < 1e-100
        assert sigmoid(800.0) == pytest.approx(1.0)


class TestWindowIntegration:
    def test_window_bounds_history(self, scorer: TrajectoryScorer, anchor_vector: np.ndarray) -> None:
        window = SlidingWindow("bounded", max_size=3)
        for step in range(1, 8):
            scorer.score(
                session_id="bounded",
                intent_embedding=anchor_vector,
                action_embedding=_vector_at_distance(anchor_vector, 0.3, seed=step),
                window=window,
                step_index=step,
            )
        assert len(window) == 3
        assert window.step_indices == [5, 6, 7]

    def test_score_records_window_size(
        self, scorer: TrajectoryScorer, anchor_vector: np.ndarray, window: SlidingWindow
    ) -> None:
        score = scorer.score(
            session_id="test-session",
            intent_embedding=anchor_vector,
            action_embedding=_vector_at_distance(anchor_vector, 0.4),
            window=window,
            step_index=1,
        )
        assert score.window_size == 1
        assert score.slope == 0.0
        assert 0.0 <= score.drift_score <= 100.0
