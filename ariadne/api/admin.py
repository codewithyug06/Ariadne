# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Admin-only endpoints over the data flywheel's trajectory records (Feature 7).

Export/label/stats for the raw material a future supervised-training
pipeline would consume. No ML happens here -- pure org-scoped read/write over
TrajectoryRecord rows.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select, update

from ariadne.auth.deps import require_role
from ariadne.auth.org_scope import require_org_scope
from ariadne.db.models import CalibrationProfile, TrajectoryRecord
from ariadne.drift.calibration import (
    DEFAULT_DATASET_NAME,
    get_active_profile,
    profile_fields_from_calibration_json,
)
from ariadne.logging import get_logger
from ariadne.proxy.schemas import utcnow

logger = get_logger(__name__)

router = APIRouter(
    prefix="/admin/trajectories",
    tags=["admin"],
    dependencies=[Depends(require_role("admin"))],
)

#: Feature 9 (calibrated/versioned risk scores) admin routes live on this
#: same admin.py module rather than a new file, for consistency with
#: Feature 7's trajectory routes above -- both are small admin-only route
#: sets over a single table, and admin.py is already the established home
#: for "admin-only, not org-scoped-business-logic" endpoints in this API.
calibration_router = APIRouter(
    prefix="/admin/calibration",
    tags=["admin"],
    dependencies=[Depends(require_role("admin"))],
)


class LabelRequest(BaseModel):
    confirmed_attack: bool
    label_source: str


class LabelResponse(BaseModel):
    id: str
    confirmed_attack: bool | None
    label_source: str | None
    labeled_at: str | None


class TrajectoryStatsResponse(BaseModel):
    total: int
    by_confirmed_attack: dict[str, int]
    by_label_source: dict[str, int]
    by_final_enforcement_action: dict[str, int]


def _row_to_jsonl_dict(row: TrajectoryRecord) -> dict[str, object]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "session_id": row.session_id,
        "agent_identity": row.agent_identity,
        "step_count": row.step_count,
        "drift_curve": row.drift_curve,
        "slope_curve": row.slope_curve,
        "r2_curve": row.r2_curve,
        "final_enforcement_action": row.final_enforcement_action,
        "first_divergence_step": row.first_divergence_step,
        "root_cause_trigger": row.root_cause_trigger,
        "blast_radius_count": row.blast_radius_count,
        "intent_score": row.intent_score,
        "tool_score": row.tool_score,
        "privilege_score": row.privilege_score,
        "identity_score": row.identity_score,
        "data_score": row.data_score,
        "confirmed_attack": row.confirmed_attack,
        "label_source": row.label_source,
        "labeled_at": row.labeled_at.isoformat() if row.labeled_at else None,
        "calibration_version": row.calibration_version,
        "scoring_algorithm_version": row.scoring_algorithm_version,
        "created_at": row.created_at.isoformat(),
    }


@router.get(
    "/export",
    summary="Export this org's trajectory records as JSONL",
    response_class=StreamingResponse,
)
async def export_trajectories(
    request: Request, organization_id: str = Depends(require_org_scope)
) -> StreamingResponse:
    database = request.app.state.database

    async def _stream() -> AsyncIterator[bytes]:
        async with database.session() as session:
            result = await session.execute(
                select(TrajectoryRecord)
                .where(TrajectoryRecord.organization_id == organization_id)
                .order_by(TrajectoryRecord.created_at)
            )
            for row in result.scalars():
                yield (json.dumps(_row_to_jsonl_dict(row)) + "\n").encode("utf-8")

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@router.post(
    "/{trajectory_id}/label",
    response_model=LabelResponse,
    summary="Set the confirmed-attack label on one trajectory record",
)
async def label_trajectory(
    trajectory_id: str,
    body: LabelRequest,
    request: Request,
    organization_id: str = Depends(require_org_scope),
) -> LabelResponse:
    database = request.app.state.database
    async with database.session() as session:
        row = await session.scalar(
            select(TrajectoryRecord).where(
                TrajectoryRecord.id == trajectory_id,
                TrajectoryRecord.organization_id == organization_id,
            )
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"no trajectory record {trajectory_id!r}")
        row.confirmed_attack = body.confirmed_attack
        row.label_source = body.label_source
        row.labeled_at = utcnow()
        await session.flush()
        response = LabelResponse(
            id=row.id,
            confirmed_attack=row.confirmed_attack,
            label_source=row.label_source,
            labeled_at=row.labeled_at.isoformat() if row.labeled_at else None,
        )

    logger.info(
        "admin.trajectory_labeled",
        organization_id=organization_id,
        trajectory_id=trajectory_id,
        confirmed_attack=body.confirmed_attack,
        label_source=body.label_source,
    )
    return response


@router.get(
    "/stats",
    response_model=TrajectoryStatsResponse,
    summary="Counts of trajectory records grouped by label state and outcome",
)
async def trajectory_stats(
    request: Request, organization_id: str = Depends(require_org_scope)
) -> TrajectoryStatsResponse:
    database = request.app.state.database
    async with database.session() as session:
        total = int(
            await session.scalar(
                select(func.count())
                .select_from(TrajectoryRecord)
                .where(TrajectoryRecord.organization_id == organization_id)
            )
            or 0
        )

        by_confirmed_attack: dict[str, int] = {}
        confirmed_rows = await session.execute(
            select(TrajectoryRecord.confirmed_attack, func.count())
            .where(TrajectoryRecord.organization_id == organization_id)
            .group_by(TrajectoryRecord.confirmed_attack)
        )
        for confirmed_attack, count in confirmed_rows.all():
            key = "null" if confirmed_attack is None else str(confirmed_attack).lower()
            by_confirmed_attack[key] = int(count)

        by_label_source: dict[str, int] = {}
        label_rows = await session.execute(
            select(TrajectoryRecord.label_source, func.count())
            .where(TrajectoryRecord.organization_id == organization_id)
            .group_by(TrajectoryRecord.label_source)
        )
        for label_source, count in label_rows.all():
            key = label_source if label_source is not None else "null"
            by_label_source[key] = int(count)

        by_action: dict[str, int] = {}
        action_rows = await session.execute(
            select(TrajectoryRecord.final_enforcement_action, func.count())
            .where(TrajectoryRecord.organization_id == organization_id)
            .group_by(TrajectoryRecord.final_enforcement_action)
        )
        for action, count in action_rows.all():
            by_action[str(action)] = int(count)

    return TrajectoryStatsResponse(
        total=total,
        by_confirmed_attack=by_confirmed_attack,
        by_label_source=by_label_source,
        by_final_enforcement_action=by_action,
    )


# ---------------------------------------------------------------------------
# Feature 9: Calibrated/Versioned Risk Scores
# ---------------------------------------------------------------------------


class CalibrationProfileResponse(BaseModel):
    id: str
    version: str
    is_active: bool
    calibrated_at: str
    dataset: str
    sample_size: int
    highest_benign_score: float
    measured_fpr: float
    measured_detection_rate: float
    score_to_precision: dict[str, float]
    recommended_warn: float
    recommended_escalate: float
    recommended_block: float
    notes: str
    created_at: str


def _to_profile_response(row: CalibrationProfile) -> CalibrationProfileResponse:
    return CalibrationProfileResponse(
        id=row.id,
        version=row.version,
        is_active=row.is_active,
        calibrated_at=row.calibrated_at.isoformat(),
        dataset=row.dataset,
        sample_size=row.sample_size,
        highest_benign_score=row.highest_benign_score,
        measured_fpr=row.measured_fpr,
        measured_detection_rate=row.measured_detection_rate,
        score_to_precision=row.score_to_precision,
        recommended_warn=row.recommended_warn,
        recommended_escalate=row.recommended_escalate,
        recommended_block=row.recommended_block,
        notes=row.notes,
        created_at=row.created_at.isoformat(),
    )


class RecalibrateRequest(BaseModel):
    version: str
    #: Cases sampled per InjecAgent file, mirroring
    #: scripts/calibrate_thresholds.py's --limit. Defaults far lower than
    #: that script's own default (40) because this runs synchronously inside
    #: an HTTP request against the live embedder/scorer pipeline -- a full
    #: 40-per-file run is a multi-minute batch job, appropriate for the CLI
    #: script's own use (a deliberate offline recalibration run) but not for
    #: an API call. Operators wanting the full sweep should keep using
    #: scripts/calibrate_thresholds.py directly and label the result's
    #: version via this endpoint's dataset conventions, or pass a larger
    #: `limit` here if they're prepared for the wait.
    limit: int = 10
    max_fpr: float = 0.05
    dataset: str = DEFAULT_DATASET_NAME
    notes: str = ""


@calibration_router.get(
    "",
    response_model=list[CalibrationProfileResponse],
    summary="List all calibration profiles/versions",
)
async def list_calibration_profiles(request: Request) -> list[CalibrationProfileResponse]:
    database = request.app.state.database
    async with database.session() as session:
        rows = await session.scalars(
            select(CalibrationProfile).order_by(CalibrationProfile.created_at.desc())
        )
        return [_to_profile_response(row) for row in rows.all()]


@calibration_router.get(
    "/active",
    response_model=CalibrationProfileResponse,
    summary="Currently active calibration profile",
)
async def get_active_calibration_profile(request: Request) -> CalibrationProfileResponse:
    database = request.app.state.database
    async with database.session() as session:
        profile = await get_active_profile(session)
        if profile is None:
            raise HTTPException(status_code=404, detail="no active calibration profile")
        return _to_profile_response(profile)


@calibration_router.post(
    "/recalibrate",
    response_model=CalibrationProfileResponse,
    summary="Run threshold calibration and store a new (inactive) version",
)
async def recalibrate(body: RecalibrateRequest, request: Request) -> CalibrationProfileResponse:
    """Runs scripts/calibrate_thresholds.py's own collect()/sweep() functions
    directly against the live pipeline (real embedder, real scorer, real
    graph) rather than duplicating its methodology -- that script is a thin
    CLI wrapper (argparse + file I/O) around collect()/sweep(), both already
    written as importable async/plain functions, so importing and calling
    them here is the cleanest way to reuse its logic without shelling out to
    a subprocess or reimplementing the grid search.

    Never auto-activates: the new profile is stored with is_active=False so
    an operator reviews it (GET /admin/calibration) before promoting it via
    POST /admin/calibration/{version}/activate.
    """
    from pathlib import Path  # noqa: PLC0415

    from eval.injecagent_adapter import load_cases  # noqa: PLC0415
    from scripts.calibrate_thresholds import (  # noqa: PLC0415
        CONTROLS,
        collect,
        sweep,
    )

    database = request.app.state.database
    async with database.session() as session:
        existing = await session.scalar(
            select(CalibrationProfile).where(CalibrationProfile.version == body.version)
        )
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"calibration profile version {body.version!r} already exists",
            )

    injecagent_dir = Path("external/InjecAgent/data")
    files = [
        injecagent_dir / "test_cases_dh_base.json",
        injecagent_dir / "test_cases_dh_enhanced.json",
        injecagent_dir / "test_cases_ds_base.json",
        injecagent_dir / "test_cases_ds_enhanced.json",
    ]
    scenarios = []
    for path in files:
        if path.exists():
            scenarios.extend(load_cases(path, body.limit))
    scenarios.extend(CONTROLS)

    if not scenarios:
        raise HTTPException(
            status_code=422,
            detail="no calibration scenarios available (missing external/InjecAgent/data)",
        )

    scores = await collect(request.app.state.settings, scenarios)
    escalate, block, metrics = sweep(scores, body.max_fpr)

    attack_count = sum(1 for s in scores if s.is_attack)
    calibration_json_shape = {
        "sample_size": len(scores),
        "attack_count": attack_count,
        "benign_count": len(scores) - attack_count,
        "recommended_escalate": escalate,
        "recommended_block": block,
        "metrics": metrics,
        "scores": [
            {"name": s.name, "is_attack": s.is_attack, "max_drift_score": s.max_drift_score}
            for s in scores
        ],
    }
    fields = profile_fields_from_calibration_json(calibration_json_shape, dataset=body.dataset)

    row = CalibrationProfile(
        id=str(uuid4()),
        version=body.version,
        is_active=False,
        calibrated_at=utcnow(),
        notes=body.notes,
        created_at=utcnow(),
        **fields,
    )
    async with database.session() as session:
        session.add(row)
        await session.flush()
        response = _to_profile_response(row)

    logger.info(
        "admin.calibration_recalibrated",
        version=body.version,
        sample_size=fields["sample_size"],
        recommended_escalate=fields["recommended_escalate"],
        recommended_block=fields["recommended_block"],
    )
    return response


@calibration_router.post(
    "/{version}/activate",
    response_model=CalibrationProfileResponse,
    summary="Activate one calibration profile version",
)
async def activate_calibration_profile(
    version: str, request: Request
) -> CalibrationProfileResponse:
    """Sets is_active=True on `version` and False on every other row, in a
    single transaction. Never touches previously-written AuditEvents or
    DriftScores -- those keep reporting whichever calibration_version they
    were stamped with at write time (see ariadne/proxy/interceptor.py); only
    future scoring picks up the newly active profile.
    """
    database = request.app.state.database
    async with database.session() as session:
        target = await session.scalar(
            select(CalibrationProfile).where(CalibrationProfile.version == version)
        )
        if target is None:
            raise HTTPException(
                status_code=404, detail=f"no calibration profile version {version!r}"
            )

        await session.execute(
            update(CalibrationProfile)
            .where(CalibrationProfile.id != target.id)
            .values(is_active=False)
        )
        target.is_active = True
        await session.flush()
        response = _to_profile_response(target)

    logger.info("admin.calibration_activated", version=version)
    return response
