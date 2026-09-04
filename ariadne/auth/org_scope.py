# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Resolves the caller's organization id for every authenticated request.

Deliberately reads only what ariadne/main.py::require_api_key already
verified and stashed on request.state — never a path/query/body parameter,
which a caller could set to any value it likes. A route that wants "the
caller's org" gets it from here, never from the URL.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from ariadne.db.models import LEGACY_ORG_ID


async def require_org_scope(request: Request) -> str:
    """The authenticated caller's organization id, or 401 if unresolvable."""
    identity = getattr(request.state, "user", None)
    if identity is not None:
        return str(identity.organization_id)

    api_key_org_id = getattr(request.state, "api_key_org_id", None)
    if api_key_org_id is not None:
        return str(api_key_org_id)

    # No dashboard JWT and no machine API key on this request. This only
    # happens when auth is fully disabled (dev, no api_keys/jwt_secret_key
    # configured) — fall back to the Legacy Org rather than 401ing a
    # deployment that never asked for tenancy in the first place.
    if not getattr(request.app.state.settings, "api_keys", None) and not getattr(
        request.app.state.settings, "jwt_secret_key", None
    ):
        return LEGACY_ORG_ID

    raise HTTPException(status_code=401, detail="unable to resolve organization for this request")
