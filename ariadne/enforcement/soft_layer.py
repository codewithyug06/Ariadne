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

    def evaluate(self, drift_score: DriftScore) -> tuple[EnforcementAction, str]:
        """Return the action and a human-readable justification."""
        score = drift_score.drift_score
        settings = self._settings

        if score >= settings.drift_score_block:
            action = EnforcementAction.BLOCK
            reason = (
                f"Drift score {score:.1f} at or above block threshold "
                f"{settings.drift_score_block:.0f} (distance {drift_score.raw_distance:.2f}, "
                f"slope {drift_score.slope:+.3f}/step): the run is escalating away from the "
                "user's stated intent."
            )
        elif score >= settings.drift_score_escalate:
            action = EnforcementAction.ESCALATE
            reason = (
                f"Drift score {score:.1f} at or above escalate threshold "
                f"{settings.drift_score_escalate:.0f} (slope {drift_score.slope:+.3f}/step): "
                "human approval required before this action proceeds."
            )
        elif score >= settings.drift_score_warn:
            action = EnforcementAction.WARN
            reason = (
                f"Drift score {score:.1f} at or above warn threshold "
                f"{settings.drift_score_warn:.0f}: action forwarded with a warning annotation."
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
        return {
            "warn": self._settings.drift_score_warn,
            "escalate": self._settings.drift_score_escalate,
            "block": self._settings.drift_score_block,
        }
