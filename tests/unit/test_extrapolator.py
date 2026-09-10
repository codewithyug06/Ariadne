# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the drift extrapolation engine (Feature 8)."""

from __future__ import annotations

import pytest

from ariadne.config import Settings, get_settings
from ariadne.drift.extrapolator import (
    DriftProjection,
    ExtrapolationPredictor,
    XGBoostPredictor,
)
from ariadne.drift.schemas import DriftScore
from ariadne.drift.window import SlidingWindow

SESSION = "session-1"


def _score(
    drift_score: float = 50.0,
    slope: float = 5.0,
    r_squared: float = 0.95,
    window_size: int = 5,
) -> DriftScore:
    return DriftScore(
        session_id=SESSION,
        step_index=5,
        raw_distance=0.5,
        slope=slope,
        drift_score=drift_score,
        window_size=window_size,
        r_squared=r_squared,
    )


def _window(size: int = 5) -> SlidingWindow:
    window = SlidingWindow(SESSION, max_size=size)
    for i in range(size):
        window.push(i, 0.1 * i)
    return window


def _settings() -> Settings:
    return get_settings()


def test_low_r_squared_returns_none() -> None:
    predictor = ExtrapolationPredictor(min_r2=0.70, settings=_settings())
    score = _score(r_squared=0.5)
    assert predictor.predict(score, _window()) is None


def test_r_squared_at_threshold_or_above_projects() -> None:
    predictor = ExtrapolationPredictor(min_r2=0.70, settings=_settings())
    score = _score(r_squared=0.70)
    result = predictor.predict(score, _window())
    assert result is not None


def test_flat_slope_projections_stay_near_current_score() -> None:
    predictor = ExtrapolationPredictor(min_r2=0.70, settings=_settings())
    score = _score(drift_score=50.0, slope=0.01, r_squared=0.95)
    result = predictor.predict(score, _window())
    assert result is not None
    for value in result.projections.values():
        assert value == pytest.approx(50.0, abs=0.5)


def test_rising_slope_increases_at_one_and_three_steps() -> None:
    predictor = ExtrapolationPredictor(min_r2=0.70, settings=_settings())
    score = _score(drift_score=50.0, slope=8.0, r_squared=0.95)
    result = predictor.predict(score, _window(), steps_ahead=[1, 3])
    assert result is not None
    assert result.projections[1] == pytest.approx(58.0)
    assert result.projections[3] == pytest.approx(74.0)
    assert result.projections[3] > result.projections[1] > result.current_score


def test_will_cross_block_true_only_when_projection_reaches_block() -> None:
    settings = _settings()
    predictor = ExtrapolationPredictor(
        min_r2=0.70, warn_threshold=40.0, block_threshold=86.5, settings=settings
    )

    # Projected values reach WARN (>=40) but stay below BLOCK (<86.5).
    warn_only = _score(drift_score=50.0, slope=2.0, r_squared=0.95)
    result_warn = predictor.predict(warn_only, _window(), steps_ahead=[1, 3])
    assert result_warn is not None
    assert result_warn.will_cross_warn is True
    assert result_warn.will_cross_block is False

    # Projected values reach BLOCK.
    block_case = _score(drift_score=80.0, slope=10.0, r_squared=0.95)
    result_block = predictor.predict(block_case, _window(), steps_ahead=[1, 3])
    assert result_block is not None
    assert result_block.will_cross_block is True


def test_projections_clipped_to_zero_and_one_hundred() -> None:
    predictor = ExtrapolationPredictor(min_r2=0.70, settings=_settings())
    score = _score(drift_score=95.0, slope=1000.0, r_squared=0.95)
    result = predictor.predict(score, _window(), steps_ahead=[1, 3])
    assert result is not None
    for value in result.projections.values():
        assert 0.0 <= value <= 100.0
        assert value == pytest.approx(100.0)

    negative_score = _score(drift_score=5.0, slope=-1000.0, r_squared=0.95)
    result_neg = predictor.predict(negative_score, _window(), steps_ahead=[1, 3])
    assert result_neg is not None
    for value in result_neg.projections.values():
        assert 0.0 <= value <= 100.0
        assert value == pytest.approx(0.0)


def test_confidence_high_vs_moderate() -> None:
    predictor = ExtrapolationPredictor(min_r2=0.70, settings=_settings())
    high = predictor.predict(_score(r_squared=0.95), _window())
    moderate = predictor.predict(_score(r_squared=0.75), _window())
    assert high is not None and high.confidence == "high"
    assert moderate is not None and moderate.confidence == "moderate"


def test_xgboost_predictor_raises_not_implemented() -> None:
    predictor = XGBoostPredictor()
    with pytest.raises(NotImplementedError):
        predictor.predict(_score(), _window())


def test_projection_model_fields_present() -> None:
    predictor = ExtrapolationPredictor(min_r2=0.70, settings=_settings())
    result = predictor.predict(_score(), _window())
    assert isinstance(result, DriftProjection)
    assert result.label == "Projected if current trend continues"
    assert "R²=" in result.basis
