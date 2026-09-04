# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Admin-only team management: add/remove teammates, reset a locked-out password.

No SMTP is configured in this build, so there is no email-invite or
forgot-password flow — an admin hands a generated temporary password to the
new teammate directly, the same out-of-band handoff the initial
ARIADNE_ADMIN_PASSWORD bootstrap already relies on. Documented as a known
limitation in the README rather than silently missing.
"""

from __future__ import annotations

import secrets
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select

from ariadne.auth.deps import require_role
from ariadne.auth.security import hash_password
from ariadne.db.models import User
from ariadne.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_role("admin"))])


class UserItem(BaseModel):
    id: str
    email: str
    role: Literal["admin", "viewer"]
    created_at: str
    last_login_at: str | None


class CreateUserPayload(BaseModel):
    email: EmailStr
    role: Literal["admin", "viewer"] = "viewer"


class CreatedUserResponse(BaseModel):
    user: UserItem
    temporary_password: str


class ResetPasswordResponse(BaseModel):
    temporary_password: str


def _to_item(user: User) -> UserItem:
    return UserItem(
        id=user.id,
        email=user.email,
        role=user.role,
        created_at=user.created_at.isoformat(),
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
    )


@router.get("", response_model=list[UserItem], summary="List teammates")
async def list_users(request: Request) -> list[UserItem]:
    database = request.app.state.database
    async with database.session() as session:
        rows = (await session.execute(select(User).order_by(User.created_at))).scalars().all()
    return [_to_item(row) for row in rows]


@router.post("", response_model=CreatedUserResponse, status_code=201, summary="Add a teammate")
async def create_user(payload: CreateUserPayload, request: Request) -> CreatedUserResponse:
    database = request.app.state.database
    temporary_password = secrets.token_urlsafe(12)
    user = User(
        id=uuid.uuid4().hex,
        email=payload.email.lower(),
        password_hash=hash_password(temporary_password),
        role=payload.role,
    )
    async with database.session() as session:
        existing = await session.scalar(select(User).where(User.email == user.email))
        if existing is not None:
            raise HTTPException(status_code=409, detail="a user with this email already exists")
        session.add(user)

    logger.info("users.created", user_id=user.id, role=user.role)
    return CreatedUserResponse(user=_to_item(user), temporary_password=temporary_password)


@router.post(
    "/{user_id}/reset-password",
    response_model=ResetPasswordResponse,
    summary="Generate a new temporary password for a locked-out teammate",
)
async def reset_password(user_id: str, request: Request) -> ResetPasswordResponse:
    database = request.app.state.database
    temporary_password = secrets.token_urlsafe(12)
    async with database.session() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail=f"no user {user_id!r}")
        user.password_hash = hash_password(temporary_password)

    logger.info("users.password_reset_by_admin", user_id=user_id)
    return ResetPasswordResponse(temporary_password=temporary_password)


@router.delete(
    "/{user_id}",
    status_code=204,
    summary="Remove a teammate",
    response_class=Response,
    response_model=None,
)
async def delete_user(user_id: str, request: Request) -> None:
    database = request.app.state.database
    async with database.session() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail=f"no user {user_id!r}")
        if user.role == "admin":
            admin_count = await session.scalar(
                select(func.count()).select_from(User).where(User.role == "admin")
            )
            if (admin_count or 0) <= 1:
                raise HTTPException(
                    status_code=409, detail="cannot remove the last remaining admin account"
                )
        await session.delete(user)

    logger.info("users.deleted", user_id=user_id)
