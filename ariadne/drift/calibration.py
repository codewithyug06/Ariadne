# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Feature 9: the calibration service over CalibrationProfile rows.

Wraps the existing scripts/calibrate_thresholds.py methodology and
threshold_calibration.json data source as a versioned, queryable service.
Neither of those two files' content is modified by this module -- it only
reads the JSON shape they already produce and maps it onto CalibrationProfile
columns.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ariadne.db.models import CalibrationProfile
from ariadne.logging import get_logger

logger = get_logger(__name__)

#: threshold_calibration.json (and scripts/calibrate_thresholds.py's --output)
#: don't calibrate a WARN cutoff -- only ESCALATE/BLOCK are grid-searched.
#: WARN stays at Ariadne's long-standing documented default (see
#: Settings.drift_score_warn) rather than being invented from data that
#: doesn't inform it.
DEFAULT_RECOMMENDED_WARN = 40.0

#: scripts/calibrate_thresholds.py's docstring/module identifies the dataset
#: it grid-searches over as InjecAgent attack cases plus Ariadne's own
#: red-team control scenarios (tests/red_team/scenarios/controls.py). There
#: is no explicit "dataset name" field in its output JSON, so this is the
#: documented sensible default used to seed/label CalibrationProfile rows
#: built from that script's output.
DEFAULT_DATASET_NAME = "injecagent_v1"


def bucket_precision(scores: list[dict[str, Any]], threshold: float) -> float:
    """Precision of "score >= threshold" as an attack-detector, over `scores`.

    `scores` is the same list shape calibrate_thresholds.py writes to its
    output JSON: [{"name": ..., "is_attack": bool, "max_drift_score": float}].
    Precision here is attacks-at-or-above / samples-at-or-above -- "if this
    cutoff fires, how often is it actually an attack" -- which is what an
    operator reading a calibration_note cares about, distinct from
    detection_rate/FPR (which are about attacks/benigns as the denominator).
    """
    at_or_above = [s for s in scores if s.get("max_drift_score", 0.0) >= threshold]
    if not at_or_above:
        return 0.0
    attacks = sum(1 for s in at_or_above if s.get("is_attack"))
    return attacks / len(at_or_above)


def profile_fields_from_calibration_json(
    data: dict[str, Any],
    *,
    dataset: str = DEFAULT_DATASET_NAME,
    recommended_warn: float = DEFAULT_RECOMMENDED_WARN,
) -> dict[str, Any]:
    """Map a calibrate_thresholds.py-shaped JSON payload onto CalibrationProfile fields.

    Used both by the seed migration (against threshold_calibration.json) and
    by the /admin/calibration/recalibrate endpoint (against a freshly
    computed result) so both paths agree on exactly one mapping.
    """
    scores: list[dict[str, Any]] = data.get("scores", [])
    benign_scores = [
        float(s["max_drift_score"]) for s in scores if not s.get("is_attack") and "max_drift_score" in s
    ]
    metrics = data.get("metrics", {})
    escalate = float(data["recommended_escalate"])
    block = float(data["recommended_block"])

    return {
        "dataset": dataset,
        "sample_size": int(data.get("sample_size", len(scores))),
        "highest_benign_score": max(benign_scores) if benign_scores else 0.0,
        "measured_fpr": float(metrics.get("false_positive_rate", 0.0)),
        "measured_detection_rate": float(metrics.get("detection_rate", 0.0)),
        "score_to_precision": {
            str(recommended_warn): bucket_precision(scores, recommended_warn),
            str(escalate): bucket_precision(scores, escalate),
            str(block): bucket_precision(scores, block),
        },
        "recommended_warn": recommended_warn,
        "recommended_escalate": escalate,
        "recommended_block": block,
    }


async def get_active_profile(
    session: AsyncSession, organization_id: str | None = None
) -> CalibrationProfile | None:
    """The currently-active calibration profile.

    `organization_id` is accepted but unused: no org-specific calibration
    exists yet (calibration is a single global setting today). Org-specific
    calibration pinning -- letting Org A stay on v1.0.0 while Org B adopts
    v1.1.0 -- is a documented future extension (would need a
    (organization_id, is_active) row per org rather than one global active
    row), not built as part of Feature 9.
    """
    del organization_id  # documented no-op, see docstring
    result: CalibrationProfile | None = await session.scalar(
        select(CalibrationProfile).where(CalibrationProfile.is_active.is_(True))
    )
    return result


def calibration_note_for_score(profile: CalibrationProfile, score: float) -> str:
    """Human-readable calibration context for one raw drift score.

    Finds the nearest bucket key in `profile.score_to_precision` at-or-below
    `score` (falling back to the lowest bucket if the score is below every
    bucket) and formats
    "Calibration v{version} — {precision%} detection at this level ({fpr%} FPR measured)".
    Bucket keys are stored as strings (JSON object keys) -- see
    profile_fields_from_calibration_json above -- so they're parsed back to
    float here for the at-or-below comparison.
    """
    buckets = sorted(float(key) for key in profile.score_to_precision)
    if not buckets:
        chosen = 0.0
    else:
        at_or_below = [b for b in buckets if b <= score]
        chosen = at_or_below[-1] if at_or_below else buckets[0]
    precision = float(profile.score_to_precision.get(str(chosen), 0.0))
    return (
        f"Calibration v{profile.version} — {precision * 100:.0f}% detection at this level "
        f"({profile.measured_fpr * 100:.0f}% FPR measured)"
    )
