# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Trajectory-based drift scoring — Ariadne's core detection algorithm."""

from __future__ import annotations

import numpy as np

from ariadne.config import Settings, get_settings
from ariadne.drift.schemas import DriftScore
from ariadne.drift.window import SlidingWindow
from ariadne.logging import get_logger

logger = get_logger(__name__)

#: Below this many samples a regression line is noise, so slope reports 0.0.
MIN_POINTS_FOR_SLOPE = 3

#: Minimum R-squared for a fitted line to count as a trend at all. Measured on
#: the red-team suite, legitimate lateral exploration fits at ~0.69 while
#: sustained injections fit at ~0.96, so the boundary sits between them rather
#: than being chosen a priori.
MIN_TREND_FIT = 0.70

#: Fallback slope gain, used only when the configured slope threshold is zero.
DEFAULT_SLOPE_GAIN = 13.7


def slope_gain(slope_threshold: float) -> float:
    """Gain that makes DRIFT_SLOPE_THRESHOLD the half-power point of the ramp.

    Derived rather than hard-coded so the configuration knob means something
    concrete: at exactly the configured slope, the trajectory term contributes
    half of its 50-point maximum. ln(3)/t solves 2*(sigmoid(g*t) - 0.5) = 0.5.
    """
    if slope_threshold <= 0.0:
        return DEFAULT_SLOPE_GAIN
    return float(np.log(3.0) / slope_threshold)


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    """Cosine similarity between two 1-D vectors, safe for zero vectors."""
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return float(np.dot(left, right) / (left_norm * right_norm))


def sigmoid(value: float) -> float:
    """Numerically stable logistic function."""
    if value >= 0.0:
        return float(1.0 / (1.0 + np.exp(-value)))
    exp_value = float(np.exp(value))
    return exp_value / (1.0 + exp_value)


def _r_squared(distances: list[float]) -> float:
    """Coefficient of determination of a straight-line fit to the window."""
    x = np.arange(len(distances), dtype=np.float64)
    y = np.asarray(distances, dtype=np.float64)
    total_variance = float(np.sum((y - y.mean()) ** 2))
    if total_variance == 0.0:
        return 0.0
    slope, intercept = np.polyfit(x, y, deg=1)
    residuals = y - (slope * x + intercept)
    return float(max(0.0, 1.0 - float(np.sum(residuals**2)) / total_variance))


class TrajectoryScorer:
    """Scores agent execution drift using the SLOPE of cosine distance over a
    sliding window — not raw per-step distance.

    This catches escalating attack patterns and hallucination cascades that
    individually reasonable steps would never flag. Conversely it forgives the
    single lateral step: a research agent that reads one off-topic document
    produces a high distance with a flat or negative slope, which a per-step
    threshold filter would flag and this scorer does not.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def score(
        self,
        session_id: str,
        intent_embedding: np.ndarray,
        action_embedding: np.ndarray,
        window: SlidingWindow,
        step_index: int,
    ) -> DriftScore:
        """Score one action against the session's intent anchor."""
        # 1. Distance from the intent anchor, clamped to [0, 2] then to [0, 1]
        #    for the composite (embeddings are normalised, so >1 is unusual).
        raw_distance = 1.0 - cosine_similarity(intent_embedding, action_embedding)
        raw_distance = float(np.clip(raw_distance, 0.0, 2.0))

        # 2. Record the sample before fitting, so the current step counts.
        window.push(step_index, raw_distance)

        # 3. Slope over the window is the primary escalation signal.
        slope = self._compute_slope(window.distances)

        # 4. Composite. The slope fed to the composite is discounted by how much
        #    the trend can be trusted (see _slope_confidence); the reported
        #    slope stays raw so the dashboard shows the measurement, not the
        #    weighting.
        confidence = self._slope_confidence(window)
        drift_score = self._composite(raw_distance, slope * confidence)

        score = DriftScore(
            session_id=session_id,
            step_index=step_index,
            raw_distance=raw_distance,
            slope=slope,
            drift_score=drift_score,
            window_size=len(window),
        )
        logger.debug(
            "drift.scored",
            session_id=session_id,
            step_index=step_index,
            raw_distance=round(raw_distance, 4),
            slope=round(slope, 4),
            drift_score=round(drift_score, 2),
            window_size=len(window),
        )
        return score

    def _compute_slope(self, distances: list[float]) -> float:
        """Least-squares slope of distance against position in the window.

        Returns 0.0 with fewer than three points: two points always define a
        line exactly, which would let the very first pair of calls dictate the
        trend and produce false escalations at step 2 of every run.
        """
        if len(distances) < MIN_POINTS_FOR_SLOPE:
            return 0.0
        x = np.arange(len(distances), dtype=np.float64)
        y = np.asarray(distances, dtype=np.float64)
        if float(np.ptp(y)) == 0.0:
            return 0.0
        slope, _intercept = np.polyfit(x, y, deg=1)
        return float(slope)

    def _slope_confidence(self, window: SlidingWindow) -> float:
        """How much of the escalation signal to believe, in [0, 1].

        Two independent discounts, multiplied:

        * **Fill fraction.** A slope fitted to 3 of 5 samples is an early read
          on a trend, not an established one.
        * **Goodness of fit (R-squared).** A sustained escalation is close to
          linear; a single outlier at the window edge produces the same
          positive slope with a visibly worse fit.

        Together these are what separate "step three of a slow-burn injection"
        from "one lateral lookup in an otherwise on-mission run" — which are
        numerically identical to plain regression and must not be treated the
        same. A lone spike still escalates for human review; only a trend that
        is both advanced and well-fitted reaches BLOCK.
        """
        distances = window.distances
        if len(distances) < MIN_POINTS_FOR_SLOPE:
            return 0.0
        fill_fraction = len(distances) / window.max_size
        fit = _r_squared(distances)
        # Below the floor the points do not describe a line at all, so the
        # fitted slope is an artefact of one outlier rather than a trend. A
        # research agent that ranges up, back, and up again lands here; a
        # slow-burn injection does not.
        trend_quality = max(0.0, (fit - MIN_TREND_FIT) / (1.0 - MIN_TREND_FIT))
        return float(np.clip(fill_fraction * trend_quality, 0.0, 1.0))

    def _composite(self, raw_distance: float, slope: float) -> float:
        """50 * distance * (1 + ramp(slope)), clamped to 0-100.

        Slope *amplifies* distance rather than adding to it independently.
        The reason is semantic: an escalating trajectory only matters insofar
        as it escalates **away from the mission**. An agent whose steps climb
        steadily while staying close to the user's intent is making progress,
        not drifting, and an additive term scores that identically to a real
        attack — measured on all-MiniLM-L6-v2 embeddings that was the dominant
        false positive.

        The ramp is a recentred sigmoid, 2*max(0, sigmoid(g*s) - 0.5), so a
        flat or improving trajectory contributes exactly zero rather than the
        0.5 a plain sigmoid returns at zero slope.

        Both spec invariants hold, and more strictly than in the additive form:

        * Distance alone tops out at 50 (ramp 0) — it cannot reach BLOCK.
        * Slope alone tops out at 2 * 50 * distance — with no distance there is
          no score at all.
        """
        distance = float(np.clip(raw_distance, 0.0, 1.0))
        gain = slope_gain(self._settings.drift_slope_threshold)
        ramp = 2.0 * max(0.0, sigmoid(slope * gain) - 0.5)
        return float(np.clip(50.0 * distance * (1.0 + ramp), 0.0, 100.0))

    def is_escalating(self, score: DriftScore) -> bool:
        """True when slope alone exceeds the configured escalation threshold."""
        return score.slope >= self._settings.drift_slope_threshold
