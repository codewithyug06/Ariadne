# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Password hashing and JWT issuance/verification for dashboard user sessions.

Deliberately separate from ariadne/config.py::api_keys: API keys authenticate
machine callers (the orchestrator hitting /mcp), tokens issued here
authenticate a human sitting at the dashboard. The two are checked by
different paths in main.py::require_api_key.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import bcrypt
import jwt

from ariadne.config import Settings

TokenType = Literal["access", "refresh"]


class InvalidTokenError(Exception):
    """Raised for any token that fails to verify: expired, malformed, wrong type."""


@dataclass(slots=True, frozen=True)
class TokenPayload:
    user_id: str
    role: str
    token_type: TokenType
    jti: str
    expires_at: datetime


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        # Malformed stored hash — never let a crash here become an auth bypass.
        return False


def new_token_id() -> str:
    return uuid.uuid4().hex


def issue_token(
    settings: Settings, *, user_id: str, role: str, token_type: TokenType
) -> tuple[str, TokenPayload]:
    """Mint a signed JWT. Returns the encoded string and its decoded payload."""
    now = datetime.now(UTC)
    lifetime = (
        timedelta(minutes=settings.jwt_access_token_minutes)
        if token_type == "access"  # noqa: S105 - a token kind label, not a secret
        else timedelta(days=settings.jwt_refresh_token_days)
    )
    expires_at = now + lifetime
    jti = new_token_id()
    claims = {
        "sub": user_id,
        "role": role,
        "type": token_type,
        "jti": jti,
        "iat": now,
        "exp": expires_at,
    }
    encoded = jwt.encode(claims, settings.jwt_secret_key, algorithm="HS256")
    return encoded, TokenPayload(
        user_id=user_id, role=role, token_type=token_type, jti=jti, expires_at=expires_at
    )


def verify_token(settings: Settings, token: str, *, expected_type: TokenType) -> TokenPayload:
    try:
        claims = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if claims.get("type") != expected_type:
        raise InvalidTokenError(f"expected a {expected_type} token, got {claims.get('type')!r}")
    return TokenPayload(
        user_id=str(claims["sub"]),
        role=str(claims["role"]),
        token_type=expected_type,
        jti=str(claims["jti"]),
        expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
    )


def hash_token(token: str) -> str:
    """Hash a refresh token before storing it — the DB row is not the credential."""
    return bcrypt.hashpw(token.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_token_hash(token: str, token_hash: str) -> bool:
    try:
        return bcrypt.checkpw(token.encode("utf-8"), token_hash.encode("ascii"))
    except ValueError:
        return False


def generate_secret() -> str:
    """For `ariadne generate-secret` / documentation, not called at runtime."""
    return secrets.token_urlsafe(32)
