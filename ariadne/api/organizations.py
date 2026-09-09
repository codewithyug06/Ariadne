# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Org lifecycle: self-serve signup and org deletion.

Invite already exists as users.py::create_user (org-scoped, admin-only,
temporary-password handoff) -- not duplicated here.

Deletion has no FK-level CASCADE to lean on: only api_keys.organization_id
is a real ForeignKey to organizations.id (see models.py). Every other
org-scoped table (runs, events, alerts, policies, users, refresh_tokens,
agents, trajectory_records, org_tool_overrides) stores organization_id as a
plain indexed string by design (Policy's own docstring explains why: a bare
primary key, not a composite one). So deletion explicitly deletes from
every org-scoped table in one transaction rather than assuming a cascade
that does not exist for most of them.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select

from ariadne.auth.api_keys import generate_api_key, hash_api_key
from ariadne.auth.deps import require_role
from ariadne.auth.org_scope import require_org_scope
from ariadne.auth.security import hash_password
from ariadne.db.models import (
    Agent,
    Alert,
    ApiKey,
    Event,
    Organization,
    OrgToolOverride,
    Policy,
    RefreshToken,
    Run,
    TrajectoryRecord,
    User,
)
from ariadne.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/orgs", tags=["organizations"])

_SLUG_INVALID = re.compile(r"[^a-z0-9]+")


class SignupPayload(BaseModel):
    organization_name: str = Field(min_length=1, max_length=255)
    admin_email: EmailStr
    admin_password: str = Field(min_length=8, max_length=256)


class SignupOrganization(BaseModel):
    id: str
    name: str
    slug: str


class SignupUser(BaseModel):
    id: str
    email: str
    role: str


class SignupResponse(BaseModel):
    organization: SignupOrganization
    user: SignupUser
    api_key: str


def _slugify(name: str) -> str:
    base = _SLUG_INVALID.sub("-", name.lower()).strip("-")[:64] or "org"
    return f"{base}-{uuid.uuid4().hex[:8]}"


@router.post(
    "",
    response_model=SignupResponse,
    status_code=201,
    summary="Self-serve organization signup",
)
async def signup(payload: SignupPayload, request: Request) -> SignupResponse:
    """Unauthenticated by design (main.py's _UNAUTHENTICATED_PATHS) -- this is
    how a brand-new tenant gets its first admin and API key. Protected from
    abuse by the app-wide rate limiter (main.py's SlowAPIMiddleware, keyed by
    presented API key or falling back to remote address for this exact
    no-credential case)."""
    database = request.app.state.database
    org_id = uuid.uuid4().hex
    user_id = uuid.uuid4().hex
    slug = _slugify(payload.organization_name)
    raw_key, prefix = generate_api_key(org_id)
    email = payload.admin_email.lower()

    async with database.session(bypass_rls=True) as session:
        existing = await session.scalar(select(User).where(User.email == email))
        if existing is not None:
            raise HTTPException(status_code=409, detail="a user with this email already exists")

        session.add(Organization(id=org_id, name=payload.organization_name, slug=slug))
        # FK-dependent rows in the same flush batch need the parent visible
        # first -- no ORM relationship() ties these together (the same trap
        # hit repeatedly in scripts/verify_rls_app.py and verify_quotas.py).
        await session.flush()
        session.add(
            User(
                id=user_id,
                organization_id=org_id,
                email=email,
                password_hash=hash_password(payload.admin_password),
                role="admin",
            )
        )
        session.add(
            ApiKey(
                id=uuid.uuid4().hex,
                organization_id=org_id,
                key_hash=hash_api_key(raw_key),
                prefix=prefix,
            )
        )

    logger.info("organizations.signup", organization_id=org_id, user_id=user_id)
    return SignupResponse(
        organization=SignupOrganization(id=org_id, name=payload.organization_name, slug=slug),
        user=SignupUser(id=user_id, email=email, role="admin"),
        api_key=raw_key,
    )


#: Every table keyed by a plain organization_id column (no FK, no DB-level
#: cascade -- see the module docstring). Deleted in this order for no
#: correctness reason (there's no FK between any of them) but so the audit
#: log below reads test-data-first, tenant-identity-last.
_ORG_SCOPED_MODELS = (
    Alert,
    Event,
    Run,
    RefreshToken,
    User,
    ApiKey,
    Policy,
    Agent,
    TrajectoryRecord,
    OrgToolOverride,
)


@router.delete(
    "/current",
    status_code=204,
    summary="Permanently delete this organization and all of its data",
    response_class=Response,
    response_model=None,
    dependencies=[Depends(require_role("admin"))],
)
async def delete_current_organization(
    request: Request, organization_id: str = Depends(require_org_scope)
) -> None:
    database = request.app.state.database
    async with database.session(bypass_rls=True) as session:
        org = await session.get(Organization, organization_id)
        if org is None:
            raise HTTPException(status_code=404, detail=f"no organization {organization_id!r}")
        for model in _ORG_SCOPED_MODELS:
            await session.execute(delete(model).where(model.organization_id == organization_id))
        await session.delete(org)

    logger.warning("organizations.deleted", organization_id=organization_id)
