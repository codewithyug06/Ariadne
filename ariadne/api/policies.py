# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""CRUD over the hard policy rule set, persisted and applied live."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from ariadne.auth.deps import require_role
from ariadne.auth.org_scope import require_org_scope
from ariadne.auth.security import TokenPayload
from ariadne.db.models import OrgToolOverride, Policy
from ariadne.enforcement.schemas import EnforcementAction, PolicyRule
from ariadne.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/policies", tags=["policies"])

# NOTE on scope: the hard-policy rule set applied at enforcement time
# (HybridEnforcementEngine.hard_layer) is one shared in-process instance for
# the whole deployment (ariadne/main.py's lifespan builds exactly one), same
# as the graph builder and recorder. Persisted Policy *rows* below are fully
# org-scoped — an org only ever sees, creates, or deletes its own rows, and
# a same-named row belonging to another org 404s rather than leaking or
# colliding. Making the runtime rule *evaluation* itself per-org (so Org A's
# policy doesn't apply to Org B's calls) is enforcement-engine work, out of
# scope for the DB/API multi-tenancy foundation this phase covers — tracked
# as a follow-up, not silently dropped.


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
async def upsert_policy(
    payload: PolicyPayload,
    request: Request,
    _identity: object = Depends(require_role("admin")),
    organization_id: str = Depends(require_org_scope),
) -> PolicyPayload:
    engine = request.app.state.engine
    database = request.app.state.database

    engine.hard_layer.add_rule(payload.to_rule())

    async with database.session() as session:
        existing = await session.scalar(select(Policy).where(Policy.name == payload.name))
        if existing is None:
            session.add(
                Policy(
                    name=payload.name,
                    organization_id=organization_id,
                    description=payload.description,
                    action=payload.action.value,
                    enabled=payload.enabled,
                    tool_name_patterns={"patterns": payload.tool_name_patterns},
                    argument_patterns={"patterns": payload.argument_patterns},
                    requires_hitl_token=payload.requires_hitl_token,
                )
            )
        elif existing.organization_id != organization_id:
            # Same name, different tenant: refuse rather than silently take
            # over or leak another org's row (name is a shared namespace —
            # see the module-level note above).
            raise HTTPException(
                status_code=409, detail=f"policy name {payload.name!r} is already in use"
            )
        else:
            existing.description = payload.description
            existing.action = payload.action.value
            existing.enabled = payload.enabled
            existing.tool_name_patterns = {"patterns": payload.tool_name_patterns}
            existing.argument_patterns = {"patterns": payload.argument_patterns}
            existing.requires_hitl_token = payload.requires_hitl_token

    logger.info(
        "policies.upserted",
        rule=payload.name,
        action=payload.action.value,
        organization_id=organization_id,
    )
    return payload


@router.delete(
    "/{name}",
    status_code=204,
    summary="Delete a rule",
    response_class=Response,
    response_model=None,
)
async def delete_policy(
    name: str,
    request: Request,
    _identity: object = Depends(require_role("admin")),
    organization_id: str = Depends(require_org_scope),
) -> None:
    engine = request.app.state.engine
    database = request.app.state.database

    async with database.session() as session:
        # A persisted row owned by a different org must never be touched or
        # even acknowledged as existing — treat it exactly like "no such
        # rule" for this caller.
        foreign = await session.scalar(
            select(Policy).where(Policy.name == name, Policy.organization_id != organization_id)
        )
        if foreign is not None:
            raise HTTPException(status_code=404, detail=f"no active rule named {name!r}")
        await session.execute(
            delete(Policy).where(
                Policy.name == name, Policy.organization_id == organization_id
            )
        )

    # Built-in default rules (e.g. payment_requires_hitl) live only in the
    # in-process hard layer, never persisted as a Policy row — removability
    # is judged by whether the engine had a rule of this name, same as
    # before org-scoping existed.
    removed = engine.hard_layer.remove_rule(name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"no active rule named {name!r}")
    logger.info("policies.deleted", rule=name, organization_id=organization_id)


class ToolOverridePayload(BaseModel):
    """A pinned tool-risk override as the dashboard/API sends it."""

    tool_name: str = Field(min_length=1, max_length=255)
    risk_override: float = Field(ge=0.0, le=100.0)


class ToolOverrideResponse(ToolOverridePayload):
    id: str
    created_by: str


class ToolOverrideListResponse(BaseModel):
    items: list[ToolOverrideResponse]


@router.post(
    "/tool-overrides",
    response_model=ToolOverrideResponse,
    status_code=201,
    summary="Pin a tool's contextual risk score for this org (Feature 10)",
)
async def create_tool_override(
    payload: ToolOverridePayload,
    request: Request,
    identity: TokenPayload | None = Depends(require_role("admin")),
    organization_id: str = Depends(require_org_scope),
) -> ToolOverrideResponse:
    database = request.app.state.database
    # Machine callers authenticated via the static X-API-Key have no JWT
    # identity (see require_role's docstring) -- attribute those to a fixed
    # sentinel rather than leaving created_by empty.
    created_by = identity.user_id if identity is not None else "api-key"

    async with database.session() as session:
        existing = await session.scalar(
            select(OrgToolOverride).where(
                OrgToolOverride.organization_id == organization_id,
                OrgToolOverride.tool_name == payload.tool_name,
            )
        )
        if existing is not None:
            existing.risk_override = payload.risk_override
            existing.created_by = created_by
            row = existing
        else:
            row = OrgToolOverride(
                organization_id=organization_id,
                tool_name=payload.tool_name,
                risk_override=payload.risk_override,
                created_by=created_by,
            )
            session.add(row)
        await session.flush()
        response = ToolOverrideResponse(
            id=row.id,
            tool_name=row.tool_name,
            risk_override=row.risk_override,
            created_by=row.created_by,
        )

    logger.info(
        "policies.tool_override_upserted",
        tool_name=payload.tool_name,
        organization_id=organization_id,
    )
    return response


@router.get(
    "/tool-overrides",
    response_model=ToolOverrideListResponse,
    summary="List this org's pinned tool-risk overrides (Feature 10)",
)
async def list_tool_overrides(
    request: Request,
    organization_id: str = Depends(require_org_scope),
) -> ToolOverrideListResponse:
    database = request.app.state.database
    async with database.session() as session:
        result = await session.execute(
            select(OrgToolOverride).where(OrgToolOverride.organization_id == organization_id)
        )
        rows = list(result.scalars().all())
    return ToolOverrideListResponse(
        items=[
            ToolOverrideResponse(
                id=row.id,
                tool_name=row.tool_name,
                risk_override=row.risk_override,
                created_by=row.created_by,
            )
            for row in rows
        ]
    )


@router.delete(
    "/tool-overrides/{override_id}",
    status_code=204,
    summary="Delete a pinned tool-risk override (Feature 10)",
    response_class=Response,
    response_model=None,
)
async def delete_tool_override(
    override_id: str,
    request: Request,
    _identity: TokenPayload | None = Depends(require_role("admin")),
    organization_id: str = Depends(require_org_scope),
) -> None:
    database = request.app.state.database
    async with database.session() as session:
        row = await session.get(OrgToolOverride, override_id)
        # A row belonging to a different org, or no row at all, must be
        # treated identically -- 404, never leaking existence -- matching
        # delete_policy's cross-org handling above.
        if row is None or row.organization_id != organization_id:
            raise HTTPException(
                status_code=404, detail=f"no tool override with id {override_id!r}"
            )
        await session.delete(row)

    logger.info(
        "policies.tool_override_deleted",
        override_id=override_id,
        organization_id=organization_id,
    )


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
