# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Org-scoped machine API key management."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from ariadne.auth.api_keys import generate_api_key, hash_api_key
from ariadne.auth.deps import require_role
from ariadne.auth.org_scope import require_org_scope
from ariadne.db.models import ApiKey
from ariadne.logging import get_logger
from ariadne.proxy.schemas import utcnow

logger = get_logger(__name__)

router = APIRouter(
    prefix="/keys",
    tags=["keys"],
    dependencies=[Depends(require_role("admin"))],
)


class ApiKeyItem(BaseModel):
    id: str
    prefix: str
    last_used_at: str | None
    rate_limit_override: int | None
    revoked_at: str | None
    created_at: str


class CreatedApiKeyResponse(BaseModel):
    key: ApiKeyItem
    raw_key: str


def _to_item(row: ApiKey) -> ApiKeyItem:
    return ApiKeyItem(
        id=row.id,
        prefix=row.prefix,
        last_used_at=row.last_used_at.isoformat() if row.last_used_at else None,
        rate_limit_override=row.rate_limit_override,
        revoked_at=row.revoked_at.isoformat() if row.revoked_at else None,
        created_at=row.created_at.isoformat(),
    )


@router.get("", response_model=list[ApiKeyItem], summary="List this org's API keys")
async def list_keys(
    request: Request, organization_id: str = Depends(require_org_scope)
) -> list[ApiKeyItem]:
    database = request.app.state.database
    async with database.session() as session:
        rows = (
            (
                await session.execute(
                    select(ApiKey)
                    .where(ApiKey.organization_id == organization_id)
                    .order_by(ApiKey.created_at)
                )
            )
            .scalars()
            .all()
        )
    return [_to_item(row) for row in rows]


@router.post(
    "", response_model=CreatedApiKeyResponse, status_code=201, summary="Create a new API key"
)
async def create_key(
    request: Request, organization_id: str = Depends(require_org_scope)
) -> CreatedApiKeyResponse:
    database = request.app.state.database
    raw_key, prefix = generate_api_key(organization_id)
    row = ApiKey(
        id=uuid.uuid4().hex,
        organization_id=organization_id,
        key_hash=hash_api_key(raw_key),
        prefix=prefix,
    )
    async with database.session() as session:
        session.add(row)

    logger.info("keys.created", organization_id=organization_id, key_id=row.id)
    return CreatedApiKeyResponse(key=_to_item(row), raw_key=raw_key)


@router.post(
    "/{key_id}/rotate",
    response_model=CreatedApiKeyResponse,
    summary="Revoke a key and issue its replacement atomically",
)
async def rotate_key(
    key_id: str, request: Request, organization_id: str = Depends(require_org_scope)
) -> CreatedApiKeyResponse:
    database = request.app.state.database
    raw_key, prefix = generate_api_key(organization_id)
    new_row = ApiKey(
        id=uuid.uuid4().hex,
        organization_id=organization_id,
        key_hash=hash_api_key(raw_key),
        prefix=prefix,
    )
    async with database.session() as session:
        old = await session.scalar(
            select(ApiKey).where(
                ApiKey.id == key_id, ApiKey.organization_id == organization_id
            )
        )
        if old is None:
            raise HTTPException(status_code=404, detail=f"no api key {key_id!r}")
        old.revoked_at = utcnow()
        session.add(new_row)

    logger.info("keys.rotated", organization_id=organization_id, old_key_id=key_id, new_key_id=new_row.id)
    return CreatedApiKeyResponse(key=_to_item(new_row), raw_key=raw_key)


@router.delete(
    "/{key_id}",
    status_code=204,
    summary="Revoke an API key",
    response_class=Response,
    response_model=None,
)
async def revoke_key(
    key_id: str, request: Request, organization_id: str = Depends(require_org_scope)
) -> None:
    database = request.app.state.database
    async with database.session() as session:
        row = await session.scalar(
            select(ApiKey).where(
                ApiKey.id == key_id, ApiKey.organization_id == organization_id
            )
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"no api key {key_id!r}")
        row.revoked_at = utcnow()

    logger.info("keys.revoked", organization_id=organization_id, key_id=key_id)
