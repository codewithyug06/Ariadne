# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Graduated response to semantic drift."""

from __future__ import annotations

from ariadne.config import Settings, get_settings
from ariadne.drift.schemas import DriftScore
from ariadne.enforcement.schemas import EnforcementAction
from ariadne.logging import get_logger

logger = get_logger(__name__)


class SoftDriftLayer:
    """Maps a drift score onto ALLOW / WARN / ESCALATE / BLOCK.

    Graduated rather than binary on purpose: the interesting region is the
    middle, where an action is suspicious enough to record and surface but not
    to refuse. Collapsing that to a single threshold is what makes naive
    filters both noisy and easy to walk past.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        # Mutable overrides applied on top of the Settings defaults — set via
        # PATCH /api/v1/settings/thresholds (ariadne/api/settings.py) and
        # kept in-memory for the life of the process so the hot enforcement
        # path never does a DB round trip per tool call. Persisted to the
        # RuntimeOverride table for durability across restarts (loaded back
        # in ariadne/main.py's lifespan via apply_overrides()).
        self._warn = self._settings.drift_score_warn
        self._escalate = self._settings.drift_score_escalate
        self._block = self._settings.drift_score_block

    def apply_overrides(self, *, warn: float, escalate: float, block: float) -> None:
        if not warn <= escalate <= block:
            raise ValueError(
                f"drift thresholds must satisfy warn <= escalate <= block (got {warn}, "
                f"{escalate}, {block})"
            )
        self._warn, self._escalate, self._block = warn, escalate, block

    def evaluate(
        self, drift_score: DriftScore, risk_aggregate: float | None = None
    ) -> tuple[EnforcementAction, str]:
        """Return the action and a human-readable justification.

        `risk_aggregate` (RiskDimensionScorer's weighted output, see
        ariadne/enforcement/risk_dimensions.py) is folded in via max() rather
        than replacing the drift score: a call can be dangerous on a dimension
        drift never sees at all (e.g. a graph-derived privilege-escalation
        edge), and that has to be able to drive the same threshold ladder
        without semantic drift ever needing to "see" it. Defaulting to None
        keeps every existing call site and test byte-for-byte unchanged.
        """
        score = drift_score.drift_score
        if risk_aggregate is not None:
            score = max(score, risk_aggregate)

        if score >= self._block:
            action = EnforcementAction.BLOCK
            reason = (
                f"Drift score {score:.1f} at or above block threshold "
                f"{self._block:.0f} (distance {drift_score.raw_distance:.2f}, "
                f"slope {drift_score.slope:+.3f}/step): the run is escalating away from the "
                "user's stated intent."
            )
        elif score >= self._escalate:
            action = EnforcementAction.ESCALATE
            reason = (
                f"Drift score {score:.1f} at or above escalate threshold "
                f"{self._escalate:.0f} (slope {drift_score.slope:+.3f}/step): "
                "human approval required before this action proceeds."
            )
        elif score >= self._warn:
            action = EnforcementAction.WARN
            reason = (
                f"Drift score {score:.1f} at or above warn threshold "
                f"{self._warn:.0f}: action forwarded with a warning annotation."
            )
        else:
            action = EnforcementAction.ALLOW
            reason = f"Drift score {score:.1f} within normal range for the stated intent."

        if action is not EnforcementAction.ALLOW:
            logger.info(
                "enforcement.soft_layer_decision",
                session_id=drift_score.session_id,
                step_index=drift_score.step_index,
                action=action.value,
                drift_score=round(score, 2),
                slope=round(drift_score.slope, 4),
                raw_distance=round(drift_score.raw_distance, 4),
            )
        return action, reason

    def thresholds(self) -> dict[str, float]:
        return {"warn": self._warn, "escalate": self._escalate, "block": self._block}
