# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Drift extrapolation engine — a purely deterministic linear projection.

This module projects the current drift trajectory forward using the slope
`TrajectoryScorer` has already fitted. It is NOT a trained model: there is no
learning, no historical corpus, nothing probabilistic beyond "if this line
keeps going, where does it end up." The honesty requirement is the whole
point: when the fit quality (R-squared) is too low to trust the trend, the
active predictor returns `None` rather than a confident-looking number.

`RiskPredictor` is a scaffold-only Protocol so a future trained model
(`XGBoostPredictor`) can be swapped in later, once Feature 7's
`TrajectoryRecord` table has accumulated enough labelled data, without
changing any downstream caller.
"""

from __future__ import annotations

from typing import Literal, Protocol

import numpy as np
from pydantic import BaseModel

from ariadne.config import Settings, get_settings
from ariadne.drift.schemas import DriftScore
from ariadne.drift.window import SlidingWindow

#: Default projection horizon when the caller does not supply one and
#: Settings.projection_steps_ahead is unavailable. Kept in sync with
#: Settings.projection_steps_ahead's own default.
DEFAULT_STEPS_AHEAD: list[int] = [1, 3]

#: An R-squared at or above this is treated as a well-established trend
#: worth calling "high" confidence rather than merely "moderate."
HIGH_CONFIDENCE_R2 = 0.90


class DriftProjection(BaseModel):
    """A linear extrapolation of the current drift trajectory.

    `confidence` and `basis` exist so an operator (or the dashboard) never has
    to take the projected numbers on faith -- the fit quality and the exact
    slope used are always visible alongside the projection itself.
    """

    current_score: float
    projections: dict[int, float]
    confidence: Literal["high", "moderate"]
    basis: str
    label: Literal["Projected if current trend continues"] = (
        "Projected if current trend continues"
    )
    will_cross_warn: bool
    will_cross_block: bool


class RiskPredictor(Protocol):
    """Interface -- swap implementations without changing downstream code."""

    def predict(
        self,
        drift_score: DriftScore,
        window: SlidingWindow,
        steps_ahead: list[int] | None = None,
    ) -> DriftProjection | None: ...


class ExtrapolationPredictor:
    """Active predictor. Purely mathematical -- no model, no training data.

    Projects `drift_score.drift_score + drift_score.slope * n` for each `n`
    in `steps_ahead`, clipped to [0, 100]. Returns None when the window's
    fitted line is not trustworthy enough to extrapolate (R-squared below
    `min_r2`) -- honesty over confidence.
    """

    def __init__(
        self,
        min_r2: float = 0.70,
        warn_threshold: float | None = None,
        block_threshold: float | None = None,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or get_settings()
        self._min_r2 = min_r2
        self._warn_threshold = (
            warn_threshold if warn_threshold is not None else settings.drift_score_warn
        )
        self._block_threshold = (
            block_threshold if block_threshold is not None else settings.drift_score_block
        )
        self._default_steps_ahead = settings.projection_steps_ahead or DEFAULT_STEPS_AHEAD

    def predict(
        self,
        drift_score: DriftScore,
        window: SlidingWindow,
        steps_ahead: list[int] | None = None,
    ) -> DriftProjection | None:
        if drift_score.r_squared < self._min_r2:
            return None

        steps = steps_ahead if steps_ahead is not None else self._default_steps_ahead

        projections: dict[int, float] = {}
        for n in steps:
            projected = drift_score.drift_score + drift_score.slope * n
            projections[n] = float(np.clip(projected, 0.0, 100.0))

        confidence: Literal["high", "moderate"] = (
            "high" if drift_score.r_squared >= HIGH_CONFIDENCE_R2 else "moderate"
        )
        basis = (
            f"{len(window)}-step slope of {drift_score.slope:+.1f}, "
            f"R²={drift_score.r_squared:.2f}"
        )
        will_cross_warn = any(value >= self._warn_threshold for value in projections.values())
        will_cross_block = any(value >= self._block_threshold for value in projections.values())

        return DriftProjection(
            current_score=drift_score.drift_score,
            projections=projections,
            confidence=confidence,
            basis=basis,
            will_cross_warn=will_cross_warn,
            will_cross_block=will_cross_block,
        )


class XGBoostPredictor:
    """NOT IMPLEMENTED -- scaffold only.

    Activate when TrajectoryRecord (Feature 7) has >=1000 human-reviewed
    labeled records with confirmed_attack labels. Calling predict() now
    raises NotImplementedError intentionally.
    """

    def predict(
        self,
        drift_score: DriftScore,
        window: SlidingWindow,
        steps_ahead: list[int] | None = None,
    ) -> DriftProjection | None:
        raise NotImplementedError(
            "XGBoostPredictor requires >=1000 labeled TrajectoryRecords. "
            "TrajectoryRecord table was added in Feature 7. "
            "Use ExtrapolationPredictor until that data exists. "
            "See ariadne/drift/extrapolator.py for the swap interface."
        )
