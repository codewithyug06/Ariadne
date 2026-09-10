# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Google OAuth2 sign-in for dashboard users.

Flow:
  GET /api/v1/auth/google          -- redirect to Google consent screen
  GET /api/v1/auth/google/callback -- exchange code, upsert user + org, redirect to dashboard

Both paths are unauthenticated (registered in main.py's _UNAUTHENTICATED_PATHS).

The redirect_uri is built from DASHBOARD_PUBLIC_URL (default: http://localhost:5173)
rather than the backend base URL so that Vite's /api proxy handles the callback
in development — cookies are then set on the dashboard origin and the normal
refresh-token flow works without cross-origin issues.

In production (behind nginx that proxies /api to the backend), DASHBOARD_PUBLIC_URL
should be the publicly reachable dashboard URL (e.g. https://app.yourcompany.com).

New Google users get a self-provisioned organisation + admin account. Returning
users are looked up by email; their existing org is reused.
"""

from __future__ import annotations

import hmac
import secrets
import time
import uuid
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from ariadne.api.auth import REFRESH_COOKIE
from ariadne.api.organizations import _slugify
from ariadne.auth.api_keys import generate_api_key, hash_api_key
from ariadne.auth.security import hash_password, hash_token, issue_token
from ariadne.db.models import ApiKey, Organization, RefreshToken, User
from ariadne.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth/google", tags=["auth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# In-memory CSRF state store: {state_token: expiry_unix_timestamp}
# A Redis-backed store is preferable at scale; this is safe for single-process deployments.
_pending_states: dict[str, float] = {}
_STATE_TTL = 300  # 5 minutes


def _prune_states() -> None:
    now = time.time()
    stale = [k for k, exp in _pending_states.items() if exp < now]
    for k in stale:
        del _pending_states[k]


@router.get("", summary="Begin Google OAuth2 sign-in")
async def google_login(request: Request) -> RedirectResponse:
    settings = request.app.state.settings
    if not (settings.google_client_id and settings.google_client_secret):
        raise HTTPException(
            status_code=501,
            detail="Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )

    state = secrets.token_urlsafe(32)
    _prune_states()
    _pending_states[state] = time.time() + _STATE_TTL

    dashboard_url = settings.dashboard_public_url
    callback_url = f"{dashboard_url}/api/v1/auth/google/callback"

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    secure = settings.environment == "production"
    response = RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")
    response.set_cookie(
        "g_oauth_state",
        state,
        max_age=_STATE_TTL,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/api/v1/auth/google",
    )
    return response


@router.get("/callback", summary="Google OAuth2 callback — not called directly by the SPA")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    settings = request.app.state.settings
    dashboard_url = settings.dashboard_public_url

    if error:
        return RedirectResponse(f"{dashboard_url}/login?error=google_denied")

    if not code or not state:
        return RedirectResponse(f"{dashboard_url}/login?error=google_invalid")

    # Validate CSRF state: cookie must match query param (prevents login CSRF)
    cookie_state = request.cookies.get("g_oauth_state", "")
    _prune_states()
    state_in_store = state in _pending_states and _pending_states.get(state, 0) >= time.time()
    state_matches = hmac.compare_digest(cookie_state, state)
    if not state_matches or not state_in_store:
        clear = RedirectResponse(f"{dashboard_url}/login?error=google_state_invalid")
        clear.delete_cookie("g_oauth_state", path="/api/v1/auth/google")
        return clear
    del _pending_states[state]

    callback_url = f"{dashboard_url}/api/v1/auth/google/callback"

    # Exchange code for Google tokens
    async with httpx.AsyncClient(timeout=10) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": callback_url,
                "grant_type": "authorization_code",
            },
        )
        if not token_resp.is_success:
            logger.warning("google_auth.token_exchange_failed", status=token_resp.status_code)
            return RedirectResponse(f"{dashboard_url}/login?error=google_token_failed")

        google_access_token = token_resp.json().get("access_token", "")

        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {google_access_token}"},
        )
        if not userinfo_resp.is_success:
            return RedirectResponse(f"{dashboard_url}/login?error=google_userinfo_failed")

        userinfo = userinfo_resp.json()

    email = (userinfo.get("email") or "").lower().strip()
    if not email or not userinfo.get("email_verified", False):
        return RedirectResponse(f"{dashboard_url}/login?error=google_email_unverified")

    database = request.app.state.database

    async with database.session(bypass_rls=True) as session:
        user = await session.scalar(select(User).where(User.email == email))

        if user is None:
            # Self-provision: new org + admin user for first-time Google sign-in
            org_id = uuid.uuid4().hex
            user_id = uuid.uuid4().hex
            display_name = userinfo.get("name") or email.split("@")[0]
            slug = _slugify(display_name)
            raw_key, prefix = generate_api_key(org_id)

            session.add(Organization(id=org_id, name=display_name, slug=slug))
            await session.flush()
            session.add(
                User(
                    id=user_id,
                    organization_id=org_id,
                    email=email,
                    # Google-authed users have no usable password; random token
                    # prevents password login while keeping the hash non-null.
                    password_hash=hash_password(secrets.token_urlsafe(32)),
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
            await session.flush()
            user = await session.get(User, user_id)
            logger.info("google_auth.new_user_provisioned", user_id=user_id, org_id=org_id)
        else:
            logger.info("google_auth.existing_user_login", user_id=user.id)

    # Issue Ariadne access + refresh tokens
    access_token, _ = issue_token(
        settings,
        user_id=user.id,
        role=user.role,
        token_type="access",
        organization_id=user.organization_id,
    )
    refresh_token, refresh_payload = issue_token(
        settings,
        user_id=user.id,
        role=user.role,
        token_type="refresh",
        organization_id=user.organization_id,
    )

    async with database.session(user.organization_id) as session:
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

    expires_in = settings.jwt_access_token_minutes * 60
    redirect_url = (
        f"{dashboard_url}/auth/callback"
        f"#access_token={access_token}&role={user.role}&expires_in={expires_in}"
    )
    secure = settings.environment == "production"
    response = RedirectResponse(redirect_url)
    response.delete_cookie("g_oauth_state", path="/api/v1/auth/google")
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.jwt_refresh_token_days * 86400,
        httponly=True,
        secure=secure,
        samesite="strict" if secure else "lax",
        path="/api/v1/auth",
    )
    return response
