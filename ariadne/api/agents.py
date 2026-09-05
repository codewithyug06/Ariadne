# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Read/write API over aggregated agent entities (Feature 3)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ariadne.auth.org_scope import require_org_scope
from ariadne.db.models import Agent, Run

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentItem(BaseModel):
    id: str
    name: str
    agent_identity: str
    total_runs: int
    total_blocked: int
    total_escalated: int
    avg_drift_score: float
    risk_score: float
    created_at: str
    last_seen_at: str


class AgentListResponse(BaseModel):
    items: list[AgentItem]
    total: int
    limit: int
    offset: int


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    agent_identity: str = Field(min_length=1, max_length=512)


class AgentUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class AgentRunListItem(BaseModel):
    session_id: str
    started_at: str
    ended_at: str | None
    total_steps: int
    final_status: str
    max_drift_score: float
    intent_summary: str
    blocked_count: int
    escalated_count: int
    warned_count: int


class AgentRunListResponse(BaseModel):
    items: list[AgentRunListItem]
    total: int
    limit: int
    offset: int


def _to_item(agent: Agent) -> AgentItem:
    return AgentItem(
        id=agent.id,
        name=agent.name,
        agent_identity=agent.agent_identity,
        total_runs=agent.total_runs,
        total_blocked=agent.total_blocked,
        total_escalated=agent.total_escalated,
        avg_drift_score=agent.avg_drift_score,
        risk_score=agent.risk_score,
        created_at=agent.created_at.isoformat(),
        last_seen_at=agent.last_seen_at.isoformat(),
    )


@router.get("", response_model=AgentListResponse, summary="List agents, riskiest first")
async def list_agents(
    request: Request,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    organization_id: str = Depends(require_org_scope),
) -> AgentListResponse:
    database = request.app.state.database
    async with database.session() as session:
        total = await session.scalar(
            select(func.count())
            .select_from(Agent)
            .where(Agent.organization_id == organization_id)
        )
        result = await session.execute(
            select(Agent)
            .where(Agent.organization_id == organization_id)
            .order_by(Agent.risk_score.desc())
            .limit(limit)
            .offset(offset)
        )
        agents = list(result.scalars().all())
    return AgentListResponse(
        items=[_to_item(agent) for agent in agents],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=AgentItem, status_code=201, summary="Register an agent")
async def create_agent(
    payload: AgentCreateRequest,
    request: Request,
    organization_id: str = Depends(require_org_scope),
) -> AgentItem:
    database = request.app.state.database
    async with database.session() as session:
        existing = await session.scalar(
            select(Agent).where(
                Agent.organization_id == organization_id,
                Agent.agent_identity == payload.agent_identity,
            )
        )
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"agent identity {payload.agent_identity!r} already registered",
            )
        agent = Agent(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            name=payload.name,
            agent_identity=payload.agent_identity,
        )
        session.add(agent)
        await session.flush()
        await session.refresh(agent)
        return _to_item(agent)


@router.get("/{agent_id}", response_model=AgentItem, summary="Agent detail")
async def get_agent(
    agent_id: str, request: Request, organization_id: str = Depends(require_org_scope)
) -> AgentItem:
    database = request.app.state.database
    async with database.session() as session:
        agent = await session.scalar(
            select(Agent).where(
                Agent.id == agent_id, Agent.organization_id == organization_id
            )
        )
    if agent is None:
        raise HTTPException(status_code=404, detail=f"no agent {agent_id!r}")
    return _to_item(agent)


@router.patch("/{agent_id}", response_model=AgentItem, summary="Rename an agent")
async def update_agent(
    agent_id: str,
    payload: AgentUpdateRequest,
    request: Request,
    organization_id: str = Depends(require_org_scope),
) -> AgentItem:
    database = request.app.state.database
    async with database.session() as session:
        agent = await session.scalar(
            select(Agent).where(
                Agent.id == agent_id, Agent.organization_id == organization_id
            )
        )
        if agent is None:
            raise HTTPException(status_code=404, detail=f"no agent {agent_id!r}")
        agent.name = payload.name
        await session.flush()
        await session.refresh(agent)
        return _to_item(agent)


@router.get(
    "/{agent_id}/runs", response_model=AgentRunListResponse, summary="Runs for this agent"
)
async def list_agent_runs(
    agent_id: str,
    request: Request,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    organization_id: str = Depends(require_org_scope),
) -> AgentRunListResponse:
    database = request.app.state.database
    async with database.session() as session:
        agent = await session.scalar(
            select(Agent).where(
                Agent.id == agent_id, Agent.organization_id == organization_id
            )
        )
        if agent is None:
            raise HTTPException(status_code=404, detail=f"no agent {agent_id!r}")

        total = await session.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.agent_id == agent_id, Run.organization_id == organization_id)
        )
        result = await session.execute(
            select(Run)
            .where(Run.agent_id == agent_id, Run.organization_id == organization_id)
            .order_by(Run.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
        runs = list(result.scalars().all())

    return AgentRunListResponse(
        items=[
            AgentRunListItem(
                session_id=run.session_id,
                started_at=run.started_at.isoformat(),
                ended_at=run.ended_at.isoformat() if run.ended_at else None,
                total_steps=run.total_steps,
                final_status=run.final_status,
                max_drift_score=run.max_drift_score,
                intent_summary=run.intent_summary,
                blocked_count=run.blocked_count,
                escalated_count=run.escalated_count,
                warned_count=run.warned_count,
            )
            for run in runs
        ],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )
