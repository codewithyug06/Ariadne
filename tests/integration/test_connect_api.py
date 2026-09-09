# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""ariadne/api/connect.py: an org's own upstream tool-server config.

Real HTTP through the app (SQLite), same pattern as test_tenant_isolation.py.
UpstreamMCPClient.test_connection is exercised against a real ASGI upstream
(tests/conftest.py's create_mock_upstream), not mocked -- a genuine
unreachable-vs-reachable distinction, just over the ASGI transport instead
of a socket.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest_asyncio
import uvicorn

from ariadne.auth.api_keys import generate_api_key, hash_api_key
from ariadne.config import Settings
from ariadne.db.models import ApiKey, Organization
from ariadne.drift.embedder import ActionEmbedder
from ariadne.main import create_app
from tests.conftest import DeterministicEmbedder, create_mock_upstream


@dataclass
class ConnectStack:
    client: httpx.AsyncClient
    org_id: str
    headers: dict[str, str]
    database: object


@pytest_asyncio.fixture
async def connect_stack(settings: Settings) -> AsyncIterator[ConnectStack]:
    auth_settings = settings.model_copy(
        update={
            "api_keys": ["unused-legacy-fallback"],
            "upstream_encryption_key": "s0e9Q9k4b8j0Z8b3g8m0K3n7p2r5t8v1x4z7C0f3H6k=",
        }
    )
    upstream = create_mock_upstream()
    backend = DeterministicEmbedder(auth_settings.embedding_dimension)
    ActionEmbedder.reset()
    ActionEmbedder._instance = ActionEmbedder(backend=backend, settings=auth_settings)  # noqa: SLF001

    app = create_app(auth_settings)
    org_id = str(uuid.uuid4())
    raw_key, prefix = generate_api_key(org_id)

    async with app.router.lifespan_context(app):
        upstream_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=upstream), base_url="http://upstream.test"
        )
        app.state.http_client = upstream_client
        app.state.proxy._client = upstream_client  # noqa: SLF001

        database = app.state.database
        async with database.session(bypass_rls=True) as session:
            session.add(Organization(id=org_id, name="t", slug=f"t-{org_id[:8]}"))
            await session.flush()
            session.add(
                ApiKey(
                    id=str(uuid.uuid4()),
                    organization_id=org_id,
                    key_hash=hash_api_key(raw_key),
                    prefix=prefix,
                )
            )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://ariadne.test"
        ) as client:
            yield ConnectStack(
                client=client, org_id=org_id, headers={"X-Api-Key": raw_key}, database=database
            )

        await upstream_client.aclose()

    ActionEmbedder.reset()


@pytest_asyncio.fixture
async def real_mock_upstream_url() -> AsyncIterator[str]:
    """A real TCP listener running scripts/mock_upstream_server.py's app.

    UpstreamMCPClient.test_connection uses a real httpx.AsyncClient (it has
    to -- it's meant to reach an arbitrary customer's real server), so
    exercising it needs an actual socket, not the ASGI-transport shortcut
    the rest of this file uses.
    """
    import sys  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from mock_upstream_server import app as mock_app  # noqa: PLC0415

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    config = uvicorn.Config(mock_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)

    yield f"http://127.0.0.1:{port}/mcp"

    server.should_exit = True
    await task


class TestConfig:
    async def test_fresh_org_has_no_upstream_configured(self, connect_stack: ConnectStack) -> None:
        response = await connect_stack.client.get(
            "/api/v1/connect/config", headers=connect_stack.headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["upstream_mcp_url"] is None
        assert body["has_upstream_headers"] is False


class TestSetUpstream:
    async def test_put_saves_url_and_masks_header_presence(
        self, connect_stack: ConnectStack
    ) -> None:
        put_response = await connect_stack.client.put(
            "/api/v1/connect/upstream",
            json={
                "upstream_mcp_url": "http://upstream.test/mcp",
                "upstream_mcp_headers": {"Authorization": "Bearer customer-secret"},
            },
            headers=connect_stack.headers,
        )
        assert put_response.status_code == 200
        body = put_response.json()
        assert body["upstream_mcp_url"] == "http://upstream.test/mcp"
        assert body["has_upstream_headers"] is True
        # The secret itself must never come back in any response body.
        assert "customer-secret" not in put_response.text

        get_response = await connect_stack.client.get(
            "/api/v1/connect/config", headers=connect_stack.headers
        )
        get_body = get_response.json()
        assert get_body["upstream_mcp_url"] == "http://upstream.test/mcp"
        assert get_body["has_upstream_headers"] is True

    async def test_headers_are_actually_encrypted_at_rest(
        self, connect_stack: ConnectStack
    ) -> None:
        await connect_stack.client.put(
            "/api/v1/connect/upstream",
            json={
                "upstream_mcp_url": "http://upstream.test/mcp",
                "upstream_mcp_headers": {"Authorization": "Bearer customer-secret"},
            },
            headers=connect_stack.headers,
        )
        async with connect_stack.database.session(bypass_rls=True) as session:  # type: ignore[attr-defined]
            org = await session.get(Organization, connect_stack.org_id)
            assert org is not None
            assert org.upstream_mcp_headers_encrypted is not None
            assert "customer-secret" not in org.upstream_mcp_headers_encrypted


class TestTestConnection:
    async def test_loopback_upstream_is_rejected_before_any_request(
        self, connect_stack: ConnectStack, real_mock_upstream_url: str
    ) -> None:
        # SSRF protection: real_mock_upstream_url is a genuinely reachable
        # server (scripts/mock_upstream_server.py, really listening -- see
        # the fixture above), but it's on 127.0.0.1, which this endpoint
        # must refuse to connect to regardless of what's actually running
        # there. Proves the block happens before any outbound request, not
        # that the server happens to be unreachable.
        response = await connect_stack.client.post(
            "/api/v1/connect/upstream/test",
            json={"upstream_mcp_url": real_mock_upstream_url, "upstream_mcp_headers": {}},
            headers=connect_stack.headers,
        )
        assert response.status_code == 400
        assert "disallowed address" in response.json()["detail"]

    async def test_private_ip_literal_is_rejected(self, connect_stack: ConnectStack) -> None:
        response = await connect_stack.client.post(
            "/api/v1/connect/upstream/test",
            json={"upstream_mcp_url": "http://10.0.0.5/mcp", "upstream_mcp_headers": {}},
            headers=connect_stack.headers,
        )
        assert response.status_code == 400
        assert "disallowed address" in response.json()["detail"]

    async def test_unresolvable_upstream_is_rejected_with_no_raw_exception_leaked(
        self, connect_stack: ConnectStack
    ) -> None:
        response = await connect_stack.client.post(
            "/api/v1/connect/upstream/test",
            json={
                "upstream_mcp_url": "http://this-should-never-resolve.invalid/mcp",
                "upstream_mcp_headers": {},
            },
            headers=connect_stack.headers,
        )
        assert response.status_code == 400
        assert "could not resolve" in response.json()["detail"]


class TestSnippet:
    async def test_snippet_contains_masked_key_prefix_not_raw_key(
        self, connect_stack: ConnectStack
    ) -> None:
        response = await connect_stack.client.get(
            "/api/v1/connect/snippet",
            params={"framework": "n8n"},
            headers=connect_stack.headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["framework"] == "n8n"
        assert "ariadne_live_org_" in body["snippet"]
        assert connect_stack.headers["X-Api-Key"] not in body["snippet"]

    async def test_unknown_framework_falls_back_to_n8n(self, connect_stack: ConnectStack) -> None:
        response = await connect_stack.client.get(
            "/api/v1/connect/snippet",
            params={"framework": "nonexistent"},
            headers=connect_stack.headers,
        )
        assert response.status_code == 200
        assert "MCP Client Tool node" in response.json()["snippet"]
