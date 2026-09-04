# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Alert history and the human-in-the-loop pending-approval queue."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from ariadne.auth.org_scope import require_org_scope
from ariadne.db.models import Alert

router = APIRouter(tags=["alerts"])


class AlertItem(BaseModel):
    alert_id: str
    session_id: str
    step_index: int
    tool_name: str
    action: str
    reason: str
    drift_score: float | None
    node_id: str | None
    acknowledged: bool
    created_at: str


class AlertListResponse(BaseModel):
    items: list[AlertItem]
    total: int
    limit: int
    offset: int


class PendingApproval(BaseModel):
    approval_id: str
    session_id: str
    step_index: int
    tool_name: str
    arguments: dict[str, object]
    reason: str
    drift_score: float | None
    triggered_rule: str | None
    node_id: str | None
    opened_at: str


@router.get("/alerts", response_model=AlertListResponse, summary="Alert history")
async def list_alerts(
    request: Request,
    acknowledged: bool | None = Query(default=None),
    action: Literal["WARN", "ESCALATE", "BLOCK"] | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    organization_id: str = Depends(require_org_scope),
) -> AlertListResponse:
    database = request.app.state.database
    async with database.session() as session:
        query = select(Alert).where(Alert.organization_id == organization_id)
        count_query = (
            select(func.count()).select_from(Alert).where(Alert.organization_id == organization_id)
        )
        if acknowledged is not None:
            query = query.where(Alert.acknowledged == acknowledged)
            count_query = count_query.where(Alert.acknowledged == acknowledged)
        if action is not None:
            query = query.where(Alert.action == action)
            count_query = count_query.where(Alert.action == action)
        total = await session.scalar(count_query) or 0
        query = query.order_by(Alert.created_at.desc()).limit(limit).offset(offset)
        rows = (await session.execute(query)).scalars().all()

    return AlertListResponse(
        items=[
            AlertItem(
                alert_id=row.alert_id,
                session_id=row.session_id,
                step_index=row.step_index,
                tool_name=row.tool_name,
                action=row.action,
                reason=row.reason,
                drift_score=row.drift_score,
                node_id=row.node_id,
                acknowledged=row.acknowledged,
                created_at=row.created_at.isoformat(),
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/alerts/{alert_id}", response_model=AlertItem, summary="Acknowledge an alert")
async def acknowledge_alert(
    alert_id: str, request: Request, organization_id: str = Depends(require_org_scope)
) -> AlertItem:
    database = request.app.state.database
    async with database.session() as session:
        row = await session.get(Alert, alert_id)
        if row is None or row.organization_id != organization_id:
            raise HTTPException(status_code=404, detail=f"no alert {alert_id!r}")
        row.acknowledged = True
        return AlertItem(
            alert_id=row.alert_id,
            session_id=row.session_id,
            step_index=row.step_index,
            tool_name=row.tool_name,
            action=row.action,
            reason=row.reason,
            drift_score=row.drift_score,
            node_id=row.node_id,
            acknowledged=row.acknowledged,
            created_at=row.created_at.isoformat(),
        )


@router.get(
    "/hitl/pending",
    response_model=list[PendingApproval],
    summary="ESCALATE decisions currently waiting on a human",
)
async def list_pending_approvals(request: Request) -> list[PendingApproval]:
    proxy = request.app.state.proxy
    return [PendingApproval(**entry) for entry in proxy.approvals.list_pending()]
