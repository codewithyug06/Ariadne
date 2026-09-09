# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
""""Connect your agent": store, test, and describe an org's own MCP tool
server, and give copy-paste connection snippets for common frameworks.

Scope note, read before extending this: ariadne/proxy/mcp_proxy.py's live
`/mcp` endpoint does NOT read `Organization.upstream_mcp_url` yet -- it
still forwards every session to the single global
`settings.upstream_mcp_url`. Wiring per-org upstream routing into the real
interception path is a separate, larger change (it touches
MCPProxy._forward and needs the RLS-aware `Database.session(organization_id)`
threaded through a hot path that currently has no DB access at all). This
module only lets an org record and test its own upstream config ahead of
that wiring -- "Test Connection" is real and useful today; "my tool calls
actually get forwarded there" is not yet true.

Auth headers a customer's tool server needs are encrypted at rest
(Fernet, settings.upstream_encryption_key) because they may contain that
customer's own credentials -- never returned by GET once saved, only
whether they're configured.
"""

from __future__ import annotations

import json

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ariadne.auth.deps import require_role
from ariadne.auth.org_scope import require_org_scope
from ariadne.db.models import ApiKey, Organization
from ariadne.gateway.upstream_client import UpstreamMCPClient
from ariadne.gateway.url_safety import UnsafeUpstreamURLError, validate_public_upstream_url
from ariadne.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/connect", tags=["connect"])
_upstream_client = UpstreamMCPClient()


def _fernet(request: Request) -> Fernet:
    key = request.app.state.settings.upstream_encryption_key
    if not key:
        raise HTTPException(
            status_code=503,
            detail="UPSTREAM_ENCRYPTION_KEY is not configured on this server -- "
            "cannot store upstream auth headers safely.",
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=503, detail=f"UPSTREAM_ENCRYPTION_KEY is not a valid Fernet key: {exc}"
        ) from exc


class UpstreamConfig(BaseModel):
    upstream_mcp_url: str | None
    has_upstream_headers: bool


class SetUpstreamPayload(BaseModel):
    upstream_mcp_url: str = Field(min_length=1, max_length=2048)
    upstream_mcp_headers: dict[str, str] = Field(default_factory=dict)


class TestConnectionPayload(BaseModel):
    upstream_mcp_url: str = Field(min_length=1, max_length=2048)
    upstream_mcp_headers: dict[str, str] = Field(default_factory=dict)


class TestConnectionResult(BaseModel):
    reachable: bool
    latency_ms: float | None
    server_info: dict[str, object] | None
    error: str | None


class SnippetResponse(BaseModel):
    framework: str
    snippet: str


@router.get("/config", response_model=UpstreamConfig, summary="This org's upstream config")
async def get_config(
    request: Request, organization_id: str = Depends(require_org_scope)
) -> UpstreamConfig:
    database = request.app.state.database
    async with database.session(organization_id) as session:
        org = await session.get(Organization, organization_id)
        url = org.upstream_mcp_url if org is not None else None
        has_headers = bool(org.upstream_mcp_headers_encrypted) if org is not None else False
    return UpstreamConfig(upstream_mcp_url=url, has_upstream_headers=has_headers)


@router.put(
    "/upstream",
    response_model=UpstreamConfig,
    summary="Set this org's upstream tool server",
    dependencies=[Depends(require_role("admin"))],
)
async def set_upstream(
    payload: SetUpstreamPayload,
    request: Request,
    organization_id: str = Depends(require_org_scope),
) -> UpstreamConfig:
    database = request.app.state.database
    encrypted: str | None = None
    if payload.upstream_mcp_headers:
        fernet = _fernet(request)
        encrypted = fernet.encrypt(json.dumps(payload.upstream_mcp_headers).encode()).decode()

    async with database.session(organization_id) as session:
        org = await session.get(Organization, organization_id)
        if org is None:
            raise HTTPException(status_code=404, detail=f"no organization {organization_id!r}")
        org.upstream_mcp_url = payload.upstream_mcp_url
        org.upstream_mcp_headers_encrypted = encrypted

    logger.info("connect.upstream_set", organization_id=organization_id)
    return UpstreamConfig(
        upstream_mcp_url=payload.upstream_mcp_url, has_upstream_headers=encrypted is not None
    )


@router.post(
    "/upstream/test",
    response_model=TestConnectionResult,
    summary="Test reachability of a (possibly unsaved) upstream URL",
    dependencies=[Depends(require_role("admin"))],
)
async def test_upstream(
    payload: TestConnectionPayload, organization_id: str = Depends(require_org_scope)
) -> TestConnectionResult:
    try:
        await validate_public_upstream_url(payload.upstream_mcp_url)
    except UnsafeUpstreamURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = await _upstream_client.test_connection(
        payload.upstream_mcp_url, payload.upstream_mcp_headers
    )
    return TestConnectionResult(
        reachable=result.reachable,
        latency_ms=result.latency_ms,
        server_info=result.server_info,
        # Never echo the raw exception text: even after blocking private/
        # loopback addresses, distinguishing "connection refused" from
        # "timed out" from a TLS error is itself a usable oracle for what's
        # sitting behind a given hostname.
        error=("unreachable" if not result.reachable and result.error else None),
    )


def _mask_prefix(prefix: str) -> str:
    return f"{prefix}{'•' * 12}"


_SNIPPETS = {
    "n8n": (
        "MCP Client Tool node configuration:\n"
        "  SSE URL: {gateway_url}/mcp\n"
        "  Headers:\n"
        "    X-Api-Key: {api_key}\n"
        "    X-Ariadne-Session-Id: ={{{{ $workflow.id }}}}-={{{{ $runIndex }}}}\n"
    ),
    "langgraph": (
        "import httpx\n\n"
        'async with httpx.AsyncClient(base_url="{gateway_url}") as client:\n'
        "    response = await client.post(\n"
        '        "/mcp",\n'
        '        json={{"jsonrpc": "2.0", "id": 1, "method": "tools/call", ...}},\n'
        '        headers={{"X-Api-Key": "{api_key}"}},\n'
        "    )\n"
    ),
    "claude_desktop": (
        "{{\n"
        '  "mcpServers": {{\n'
        '    "ariadne": {{\n'
        '      "url": "{gateway_url}/mcp",\n'
        '      "headers": {{"X-Api-Key": "{api_key}"}}\n'
        "    }}\n"
        "  }}\n"
        "}}\n"
    ),
}


@router.get(
    "/snippet", response_model=SnippetResponse, summary="Connection snippet for a framework"
)
async def get_snippet(
    request: Request,
    framework: str = "n8n",
    organization_id: str = Depends(require_org_scope),
) -> SnippetResponse:
    database = request.app.state.database
    async with database.session(organization_id) as session:
        key_row = await session.scalar(
            select(ApiKey)
            .where(ApiKey.organization_id == organization_id, ApiKey.revoked_at.is_(None))
            .order_by(ApiKey.created_at.desc())
        )

    api_key_display = (
        _mask_prefix(key_row.prefix)
        if key_row is not None
        else "<create an API key first: POST /api/v1/keys>"
    )
    gateway_url = request.app.state.settings.public_url or str(request.base_url).rstrip("/")
    template = _SNIPPETS.get(framework, _SNIPPETS["n8n"])
    return SnippetResponse(
        framework=framework,
        snippet=template.format(gateway_url=gateway_url, api_key=api_key_display),
    )
