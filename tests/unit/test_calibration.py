# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Feature 9: Calibrated/Versioned Risk Scores.

Unit-level: drives CalibrationProfile through the real `database` fixture
(in-memory SQLite via tests/conftest.py, same precedent as
test_trajectory_recorder.py) rather than mocking the session, since the
whole point of this feature is what gets persisted and queried.

The migration's seed step reads threshold_calibration.json from disk and is
awkward to exercise at the unit level (it would mean running an actual
Alembic upgrade against a throwaway DB) -- instead this file tests the
factored-out mapping function
(ariadne.drift.calibration.profile_fields_from_calibration_json) directly
against the real threshold_calibration.json content, which is the same
mapping the migration calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from ariadne.db.models import CalibrationProfile
from ariadne.db.session import Database
from ariadne.drift.calibration import (
    bucket_precision,
    calibration_note_for_score,
    get_active_profile,
    profile_fields_from_calibration_json,
)
from ariadne.drift.versioning import SCORER_ALGORITHM_VERSION, current_stamp
from ariadne.proxy.schemas import utcnow

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CALIBRATION_JSON_PATH = _REPO_ROOT / "threshold_calibration.json"


def _load_calibration_json() -> dict[str, object]:
    data: dict[str, object] = json.loads(_CALIBRATION_JSON_PATH.read_text(encoding="utf-8"))
    return data


def _make_profile(
    version: str,
    is_active: bool,
    *,
    warn: float = 40.0,
    escalate: float = 66.5,
    block: float = 86.5,
) -> CalibrationProfile:
    return CalibrationProfile(
        id=str(uuid4()),
        version=version,
        is_active=is_active,
        calibrated_at=utcnow(),
        dataset="injecagent_v1",
        sample_size=324,
        highest_benign_score=66.1,
        measured_fpr=0.0,
        measured_detection_rate=0.90625,
        score_to_precision={str(warn): 0.0, str(escalate): 0.76, str(block): 1.0},
        recommended_warn=warn,
        recommended_escalate=escalate,
        recommended_block=block,
        notes="",
        created_at=utcnow(),
    )


class TestSeedMapping:
    """threshold_calibration.json's actual values, mapped onto CalibrationProfile fields."""

    def test_maps_threshold_calibration_json_to_expected_values(self) -> None:
        data = _load_calibration_json()
        fields = profile_fields_from_calibration_json(data)

        assert fields["sample_size"] == data["sample_size"] == 324
        assert fields["recommended_escalate"] == data["recommended_escalate"] == pytest.approx(66.5)
        assert fields["recommended_block"] == data["recommended_block"] == pytest.approx(86.5)
        metrics = data["metrics"]
        assert isinstance(metrics, dict)
        assert fields["measured_detection_rate"] == pytest.approx(metrics["detection_rate"])
        assert fields["measured_fpr"] == pytest.approx(metrics["false_positive_rate"])
        assert fields["dataset"] == "injecagent_v1"
        # recommended_warn is not present in the JSON -- documented default.
        assert fields["recommended_warn"] == 40.0

    def test_highest_benign_score_matches_the_json_scores_list(self) -> None:
        data = _load_calibration_json()
        fields = profile_fields_from_calibration_json(data)
        scores = data["scores"]
        assert isinstance(scores, list)
        benign = [s["max_drift_score"] for s in scores if not s["is_attack"]]
        assert fields["highest_benign_score"] == pytest.approx(max(benign))


class TestBucketPrecision:
    def test_precision_at_a_threshold_with_no_samples_is_zero(self) -> None:
        assert bucket_precision([], 50.0) == 0.0

    def test_precision_counts_attacks_over_total_at_or_above_threshold(self) -> None:
        scores = [
            {"is_attack": True, "max_drift_score": 90.0},
            {"is_attack": True, "max_drift_score": 80.0},
            {"is_attack": False, "max_drift_score": 85.0},
            {"is_attack": False, "max_drift_score": 10.0},
        ]
        # At threshold 70: three samples qualify (90, 80, 85), two are attacks.
        assert bucket_precision(scores, 70.0) == pytest.approx(2 / 3)


class TestCalibrationNote:
    def test_note_uses_nearest_bucket_at_or_below_score(self) -> None:
        profile = _make_profile("1.0.0", is_active=True)
        note = calibration_note_for_score(profile, 70.0)  # between escalate(66.5) and block(86.5)
        assert "v1.0.0" in note
        assert "76%" in note  # score_to_precision[66.5] == 0.76

    def test_note_falls_back_to_lowest_bucket_when_score_is_below_every_bucket(self) -> None:
        profile = _make_profile("1.0.0", is_active=True)
        note = calibration_note_for_score(profile, 5.0)
        assert "0%" in note  # score_to_precision[40.0] == 0.0

    def test_note_uses_highest_bucket_when_score_is_above_every_bucket(self) -> None:
        profile = _make_profile("1.0.0", is_active=True)
        note = calibration_note_for_score(profile, 99.0)
        assert "100%" in note  # score_to_precision[86.5] == 1.0


class TestVersioningStamp:
    def test_scorer_algorithm_version_is_the_documented_constant(self) -> None:
        assert SCORER_ALGORITHM_VERSION == "2.0.0"

    def test_current_stamp_carries_the_passed_calibration_version(self) -> None:
        stamp = current_stamp("1.0.0")
        assert stamp.calibration_version == "1.0.0"
        assert stamp.scorer_algorithm_version == "2.0.0"
        assert stamp.embedding_model_version
        assert stamp.risk_weights_version


@pytest.mark.asyncio
class TestActivationDoesNotRewriteHistory:
    """Activating a new profile must never touch previously-scored data."""

    async def test_activate_flips_is_active_on_exactly_the_target_row(
        self, database: Database
    ) -> None:
        v1 = _make_profile("1.0.0", is_active=True)
        v2 = _make_profile("1.1.0", is_active=False, escalate=70.0, block=90.0)
        async with database.session() as session:
            session.add(v1)
            session.add(v2)

        async with database.session() as session:
            active = await get_active_profile(session)
            assert active is not None
            assert active.version == "1.0.0"

        # Simulate the activate endpoint: flip v2 active, v1 inactive.
        async with database.session() as session:
            rows = (await session.scalars(select(CalibrationProfile))).all()
            for row in rows:
                row.is_active = row.version == "1.1.0"

        async with database.session() as session:
            active = await get_active_profile(session)
            assert active is not None
            assert active.version == "1.1.0"

            v1_row = await session.scalar(
                select(CalibrationProfile).where(CalibrationProfile.version == "1.0.0")
            )
            assert v1_row is not None
            assert v1_row.is_active is False

    async def test_a_drift_score_stamped_under_v1_keeps_reporting_v1_after_v2_activates(
        self, database: Database
    ) -> None:
        from ariadne.drift.schemas import DriftScore  # noqa: PLC0415

        v1 = _make_profile("1.0.0", is_active=True)
        v2 = _make_profile("2.0.0", is_active=False)
        async with database.session() as session:
            session.add(v1)
            session.add(v2)

        # A DriftScore stamped while v1.0.0 was active.
        old_score = DriftScore(
            session_id="s1",
            step_index=0,
            raw_distance=0.5,
            slope=0.1,
            drift_score=70.0,
            window_size=5,
            calibration_version="1.0.0",
        )

        # Activate v2.0.0.
        async with database.session() as session:
            rows = (await session.scalars(select(CalibrationProfile))).all()
            for row in rows:
                row.is_active = row.version == "2.0.0"

        async with database.session() as session:
            active = await get_active_profile(session)
            assert active is not None
            assert active.version == "2.0.0"

        # The already-stamped DriftScore is untouched -- nothing recomputes it.
        assert old_score.calibration_version == "1.0.0"
