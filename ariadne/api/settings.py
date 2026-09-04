# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Read-only system config + the one admin-editable knob: drift thresholds.

Everything else on Settings is process-level (DATABASE_URL, embedding
device, ...) and changing it live without a restart would be unsound, so
only warn/escalate/block get a write path here. See
ariadne/enforcement/soft_layer.py::apply_overrides and the RuntimeOverride
table in ariadne/db/models.py for how the value survives a restart.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, model_validator
from sqlalchemy import select

from ariadne.auth.deps import require_role
from ariadne.db.models import RuntimeOverride
from ariadne.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

_OVERRIDE_KEYS = ("drift_score_warn", "drift_score_escalate", "drift_score_block")


class SettingsSummary(BaseModel):
    """Non-secret config surfaced to the dashboard's Settings page."""

    environment: str
    embedding_model: str
    embedding_device: str
    graph_backend: str
    hard_layer_backend: str
    fail_mode: str
    upstream_mcp_url: str
    cors_origins: list[str]
    rate_limit_per_minute: int
    drift_thresholds: dict[str, float]
    # Where an agent orchestrator should point to reach this instance's /mcp
    # proxy. None when ARIADNE_PUBLIC_URL isn't configured — the dashboard
    # shows a setup hint rather than guessing a URL from its own domain.
    mcp_url: str | None


class ThresholdPayload(BaseModel):
    warn: float
    escalate: float
    block: float

    @model_validator(mode="after")
    def _ordered(self) -> ThresholdPayload:
        if not self.warn <= self.escalate <= self.block:
            raise ValueError("thresholds must satisfy warn <= escalate <= block")
        return self


@router.get("", response_model=SettingsSummary, summary="Current non-secret configuration")
async def get_settings_summary(request: Request) -> SettingsSummary:
    settings = request.app.state.settings
    return SettingsSummary(
        environment=settings.environment,
        embedding_model=settings.embedding_model,
        embedding_device=settings.embedding_device,
        graph_backend=settings.graph_backend,
        hard_layer_backend=settings.hard_layer_backend,
        fail_mode=settings.fail_mode.value,
        upstream_mcp_url=settings.upstream_mcp_url,
        cors_origins=settings.cors_origins,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        drift_thresholds=request.app.state.engine.soft_layer.thresholds(),
        mcp_url=f"{settings.public_url.rstrip('/')}/mcp" if settings.public_url else None,
    )


@router.patch(
    "/thresholds",
    response_model=dict[str, float],
    summary="Override the drift WARN/ESCALATE/BLOCK thresholds",
)
async def update_thresholds(
    payload: ThresholdPayload,
    request: Request,
    _identity: object = Depends(require_role("admin")),
) -> dict[str, float]:
    engine = request.app.state.engine
    database = request.app.state.database
    try:
        engine.soft_layer.apply_overrides(
            warn=payload.warn, escalate=payload.escalate, block=payload.block
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    values = {
        "drift_score_warn": payload.warn,
        "drift_score_escalate": payload.escalate,
        "drift_score_block": payload.block,
    }
    async with database.session() as session:
        for key, value in values.items():
            row = await session.get(RuntimeOverride, key)
            if row is None:
                session.add(RuntimeOverride(key=key, value=str(value)))
            else:
                row.value = str(value)

    logger.info("settings.thresholds_overridden", **values)
    thresholds: dict[str, float] = engine.soft_layer.thresholds()
    return thresholds


async def load_persisted_overrides(app_state: object) -> None:
    """Re-apply an admin's threshold override at startup, if one was saved."""
    database = app_state.database  # type: ignore[attr-defined]
    engine = app_state.engine  # type: ignore[attr-defined]
    async with database.session() as session:
        rows = (
            (
                await session.execute(
                    select(RuntimeOverride).where(RuntimeOverride.key.in_(_OVERRIDE_KEYS))
                )
            )
            .scalars()
            .all()
        )
    if len(rows) != len(_OVERRIDE_KEYS):
        return  # partial or absent — fall back to Settings defaults
    values = {row.key: float(row.value) for row in rows}
    engine.soft_layer.apply_overrides(
        warn=values["drift_score_warn"],
        escalate=values["drift_score_escalate"],
        block=values["drift_score_block"],
    )
