# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""CRUD over the hard policy rule set, persisted and applied live."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from ariadne.db.models import Policy
from ariadne.enforcement.schemas import EnforcementAction, PolicyRule
from ariadne.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/policies", tags=["policies"])


class PolicyPayload(BaseModel):
    """A rule as the dashboard's editor sends it."""

    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    action: EnforcementAction = EnforcementAction.BLOCK
    enabled: bool = True
    tool_name_patterns: list[str] = Field(default_factory=list)
    argument_patterns: list[str] = Field(default_factory=list)
    requires_hitl_token: bool = False

    def to_rule(self) -> PolicyRule:
        return PolicyRule(
            name=self.name,
            description=self.description,
            action=self.action,
            enabled=self.enabled,
            tool_name_patterns=self.tool_name_patterns,
            argument_patterns=self.argument_patterns,
            requires_hitl_token=self.requires_hitl_token,
        )


class PolicyListResponse(BaseModel):
    items: list[PolicyPayload]
    backend: str


@router.get("", response_model=PolicyListResponse, summary="List active hard policy rules")
async def list_policies(request: Request) -> PolicyListResponse:
    from ariadne.config import get_settings  # noqa: PLC0415

    engine = request.app.state.engine
    return PolicyListResponse(
        items=[
            PolicyPayload(
                name=rule.name,
                description=rule.description,
                action=rule.action,
                enabled=rule.enabled,
                tool_name_patterns=rule.tool_name_patterns,
                argument_patterns=rule.argument_patterns,
                requires_hitl_token=rule.requires_hitl_token,
            )
            for rule in engine.hard_layer.rules
        ],
        backend=get_settings().hard_layer_backend,
    )


@router.post("", response_model=PolicyPayload, status_code=201, summary="Create or replace a rule")
async def upsert_policy(payload: PolicyPayload, request: Request) -> PolicyPayload:
    engine = request.app.state.engine
    database = request.app.state.database

    engine.hard_layer.add_rule(payload.to_rule())

    async with database.session() as session:
        existing = await session.scalar(select(Policy).where(Policy.name == payload.name))
        if existing is None:
            session.add(
                Policy(
                    name=payload.name,
                    description=payload.description,
                    action=payload.action.value,
                    enabled=payload.enabled,
                    tool_name_patterns={"patterns": payload.tool_name_patterns},
                    argument_patterns={"patterns": payload.argument_patterns},
                    requires_hitl_token=payload.requires_hitl_token,
                )
            )
        else:
            existing.description = payload.description
            existing.action = payload.action.value
            existing.enabled = payload.enabled
            existing.tool_name_patterns = {"patterns": payload.tool_name_patterns}
            existing.argument_patterns = {"patterns": payload.argument_patterns}
            existing.requires_hitl_token = payload.requires_hitl_token

    logger.info("policies.upserted", rule=payload.name, action=payload.action.value)
    return payload


@router.delete(
    "/{name}",
    status_code=204,
    summary="Delete a rule",
    response_class=Response,
    response_model=None,
)
async def delete_policy(name: str, request: Request) -> None:
    engine = request.app.state.engine
    database = request.app.state.database

    removed = engine.hard_layer.remove_rule(name)
    async with database.session() as session:
        await session.execute(delete(Policy).where(Policy.name == name))

    if not removed:
        raise HTTPException(status_code=404, detail=f"no active rule named {name!r}")
    logger.info("policies.deleted", rule=name)


async def load_persisted_policies(app_state: Any) -> int:
    """Re-apply operator-defined rules at startup. Returns how many loaded."""
    database = app_state.database
    engine = app_state.engine
    async with database.session() as session:
        result = await session.execute(select(Policy))
        rules = list(result.scalars().all())

    for row in rules:
        engine.hard_layer.add_rule(
            PolicyRule(
                name=row.name,
                description=row.description,
                action=EnforcementAction(row.action),
                enabled=row.enabled,
                tool_name_patterns=list((row.tool_name_patterns or {}).get("patterns", [])),
                argument_patterns=list((row.argument_patterns or {}).get("patterns", [])),
                requires_hitl_token=row.requires_hitl_token,
            )
        )
    return len(rules)
