# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Dashboard login: JWT access tokens + a rotated, hashed refresh cookie.

Distinct from ARIADNE_API_KEYS (ariadne/config.py), which authenticate
machine callers hitting /mcp. This is for a human at the dashboard.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update

from ariadne.auth.security import (
    InvalidTokenError,
    hash_password,
    hash_token,
    issue_token,
    verify_password,
    verify_token,
    verify_token_hash,
)
from ariadne.db.models import RefreshToken, User
from ariadne.logging import get_logger
from ariadne.proxy.schemas import utcnow

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "ariadne_refresh"


class LoginPayload(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth2 scheme name, not a secret
    role: str
    expires_in_seconds: int


class MeResponse(BaseModel):
    id: str
    email: str
    role: str


class PasswordChangePayload(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


def _cookie_kwargs(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    secure = settings.environment == "production"
    return {
        "httponly": True,
        "secure": secure,
        "samesite": "strict" if secure else "lax",
        "path": "/api/v1/auth",
    }


async def _issue_session(request: Request, response: Response, user: User) -> AccessTokenResponse:
    settings = request.app.state.settings
    database = request.app.state.database

    access_token, _ = issue_token(
        settings,
        user_id=user.id,
        role=user.role,
        token_type="access",  # noqa: S106
        organization_id=user.organization_id,
    )
    refresh_token, refresh_payload = issue_token(
        settings,
        user_id=user.id,
        role=user.role,
        token_type="refresh",  # noqa: S106
        organization_id=user.organization_id,
    )

    async with database.session() as session:
        session.add(
            RefreshToken(
                id=refresh_payload.jti,
                organization_id=user.organization_id,
                user_id=user.id,
                token_hash=hash_token(refresh_token),
                expires_at=refresh_payload.expires_at,
                revoked=False,
            )
        )

    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.jwt_refresh_token_days * 86400,
        **_cookie_kwargs(request),
    )
    return AccessTokenResponse(
        access_token=access_token,
        role=user.role,
        expires_in_seconds=settings.jwt_access_token_minutes * 60,
    )


@router.post("/login", response_model=AccessTokenResponse, summary="Log in with email/password")
async def login(payload: LoginPayload, request: Request, response: Response) -> AccessTokenResponse:
    database = request.app.state.database
    async with database.session() as session:
        user = await session.scalar(select(User).where(User.email == payload.email.lower()))
        if user is None or not verify_password(payload.password, user.password_hash):
            logger.warning("auth.login_failed", email=payload.email)
            raise HTTPException(status_code=401, detail="invalid email or password")
        user.last_login_at = utcnow()

    logger.info("auth.login_succeeded", user_id=user.id, role=user.role)
    return await _issue_session(request, response, user)


@router.post("/refresh", response_model=AccessTokenResponse, summary="Rotate the refresh cookie")
async def refresh(request: Request, response: Response) -> AccessTokenResponse:
    settings = request.app.state.settings
    database = request.app.state.database
    raw_token = request.cookies.get(REFRESH_COOKIE)
    if not raw_token:
        raise HTTPException(status_code=401, detail="no refresh cookie presented")

    try:
        payload = verify_token(settings, raw_token, expected_type="refresh")
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="invalid or expired refresh token") from exc

    async with database.session() as session:
        row = await session.get(RefreshToken, payload.jti)
        # SQLite round-trips DateTime(timezone=True) columns as naive
        # datetimes via aiosqlite even though they were written aware —
        # normalize before comparing or this crashes with TypeError instead
        # of denying the request.
        expires_at = (
            row.expires_at.replace(tzinfo=UTC) if row and row.expires_at.tzinfo is None
            else (row.expires_at if row else None)
        )
        if (
            row is None
            or row.revoked
            or expires_at is None
            or expires_at < datetime.now(UTC)
            or not verify_token_hash(raw_token, row.token_hash)
        ):
            raise HTTPException(status_code=401, detail="refresh token no longer valid")
        row.revoked = True  # rotate: this token is single-use
        user = await session.get(User, row.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="account no longer exists")

    return await _issue_session(request, response, user)


@router.post(
    "/logout",
    status_code=204,
    summary="Revoke the current refresh token",
    response_class=Response,
    response_model=None,
)
async def logout(request: Request, response: Response) -> None:
    settings = request.app.state.settings
    database = request.app.state.database
    raw_token = request.cookies.get(REFRESH_COOKIE)
    if raw_token:
        try:
            payload = verify_token(settings, raw_token, expected_type="refresh")
        except InvalidTokenError:
            payload = None
        if payload is not None:
            async with database.session() as session:
                row = await session.get(RefreshToken, payload.jti)
                if row is not None:
                    row.revoked = True
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")


@router.get("/me", response_model=MeResponse, summary="Current authenticated user")
async def me(request: Request) -> MeResponse:
    identity = getattr(request.state, "user", None)
    if identity is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    database = request.app.state.database
    async with database.session() as session:
        user = await session.get(User, identity.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="account no longer exists")
        return MeResponse(id=user.id, email=user.email, role=user.role)


@router.patch(
    "/password",
    status_code=204,
    summary="Change your own password",
    response_class=Response,
    response_model=None,
)
async def change_password(payload: PasswordChangePayload, request: Request) -> None:
    identity = getattr(request.state, "user", None)
    if identity is None:
        raise HTTPException(status_code=401, detail="not authenticated")

    database = request.app.state.database
    async with database.session() as session:
        user = await session.get(User, identity.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="account no longer exists")
        if not verify_password(payload.current_password, user.password_hash):
            raise HTTPException(status_code=401, detail="current password is incorrect")
        user.password_hash = hash_password(payload.new_password)
        # Force re-login everywhere else — a changed password should
        # invalidate sessions started under the old one, not just this tab.
        await session.execute(
            update(RefreshToken).where(RefreshToken.user_id == user.id).values(revoked=True)
        )

    logger.info("auth.password_changed", user_id=identity.user_id)


async def bootstrap_admin(app_state: Any) -> bool:
    """Create the first admin account from ARIADNE_ADMIN_EMAIL/PASSWORD.

    Only fires when the users table is empty — never overwrites or recreates
    an existing account, so changing the env vars later has no effect.
    """
    settings = app_state.settings
    if not (settings.admin_email and settings.admin_password):
        return False

    database = app_state.database
    async with database.session() as session:
        existing = await session.scalar(select(User).limit(1))
        if existing is not None:
            return False
        session.add(
            User(
                id=uuid.uuid4().hex,
                email=settings.admin_email.lower(),
                password_hash=hash_password(settings.admin_password),
                role="admin",
            )
        )
    logger.info("auth.admin_bootstrapped", email=settings.admin_email)
    return True
