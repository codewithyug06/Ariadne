# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""FastAPI dependencies for route-level role checks.

ariadne/main.py::require_api_key already verifies the token and stashes the
decoded payload on `request.state.user` for any dashboard (JWT) caller —
these dependencies just read that and enforce a minimum role. A machine
caller authenticated via the static X-API-Key has no `request.state.user` at
all, so it's treated as admin-equivalent: it already passed the coarser
API-key gate machine-to-machine traffic has always used.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request

from ariadne.auth.security import TokenPayload

ROLE_RANK = {"viewer": 0, "admin": 1}


def require_role(minimum: str) -> Callable[[Request], Coroutine[Any, Any, TokenPayload | None]]:
    async def _check(request: Request) -> TokenPayload | None:
        identity: TokenPayload | None = getattr(request.state, "user", None)
        if identity is None:
            # No dashboard JWT on this request — either auth is fully
            # disabled (dev, no api_keys/jwt_secret_key configured) or this
            # is a machine caller that already cleared the static API key.
            return None
        if ROLE_RANK.get(identity.role, -1) < ROLE_RANK.get(minimum, 99):
            raise HTTPException(
                status_code=403, detail=f"requires the {minimum!r} role, has {identity.role!r}"
            )
        return identity

    return _check
