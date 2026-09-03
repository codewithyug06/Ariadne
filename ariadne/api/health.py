# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Liveness, readiness and component status."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ariadne import __version__
from ariadne.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    version: str


class ComponentStatus(BaseModel):
    """What is actually live, including which fallbacks are in play."""

    embedder_backend: str
    embedder_degraded: bool
    graph_backend: str
    policy_backend: str
    fail_mode: str
    active_sessions: int
    pending_audit_writes: int
    dropped_audit_events: int
    pending_approvals: int
    stream_subscribers: int
    drift_thresholds: dict[str, float]


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


@router.get("/status", response_model=ComponentStatus, summary="Component status")
async def status(request: Request) -> ComponentStatus:
    state: Any = request.app.state
    settings = get_settings()
    return ComponentStatus(
        embedder_backend=state.embedder.backend,
        embedder_degraded=state.embedder.is_degraded,
        graph_backend=getattr(state.graph_store, "backend", "unknown"),
        policy_backend=settings.hard_layer_backend,
        fail_mode=settings.fail_mode.value,
        active_sessions=len(state.proxy.sessions),
        pending_audit_writes=state.recorder.pending,
        dropped_audit_events=state.recorder.dropped_events,
        pending_approvals=state.proxy.approvals.pending_count,
        stream_subscribers=state.stream_hub.subscriber_count,
        drift_thresholds={
            "warn": settings.drift_score_warn,
            "escalate": settings.drift_score_escalate,
            "block": settings.drift_score_block,
        },
    )
