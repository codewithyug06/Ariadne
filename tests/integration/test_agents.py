# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Feature 3: Agent Entity — resolution, aggregation, and org isolation.

Org isolation follows test_tenant_isolation.py's rule exactly: a cross-org
lookup by id must 404, never 403, and a cross-org list must simply omit the
other org's rows.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest
import pytest_asyncio

from ariadne.auth.api_keys import generate_api_key, hash_api_key
from ariadne.config import Settings
from ariadne.db.models import ApiKey, Organization
from ariadne.drift.embedder import ActionEmbedder
from ariadne.main import create_app
from tests.conftest import DeterministicEmbedder, create_mock_upstream
from tests.integration.conftest import Stack, call_tool


async def init_with_agent(
    stack: Stack,
    session_id: str,
    user_request: str,
    agent_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Handshake variant that lets the caller pin an explicit agent identity."""
    stack.set_anchor_text(user_request)
    params: dict[str, object] = {
        "protocolVersion": "2024-11-05",
        "userRequest": user_request,
    }
    if agent_id is not None:
        params["agent_id"] = agent_id
    return await stack.client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": params},
        headers={**(headers or {}), "X-Ariadne-Session-Id": session_id},
    )


async def end_session(
    stack: Stack, session_id: str, headers: dict[str, str] | None = None
) -> httpx.Response:
    return await stack.client.post(f"/mcp/sessions/{session_id}/end", headers=headers or {})


class TestAgentResolutionAndAggregation:
    async def test_completing_a_run_updates_the_agents_totals(self, stack: Stack) -> None:
        session_id = f"agent-test-{uuid.uuid4()}"
        agent_identity = f"agent-{uuid.uuid4().hex[:8]}"
        stack.on_mission("read the quarterly sales figures")

        await init_with_agent(
            stack, session_id, "read the quarterly sales figures", agent_id=agent_identity
        )
        response = await call_tool(stack, session_id, "read_file", {"path": "sales.csv"})
        assert response.status_code == 200
        ended = await end_session(stack, session_id)
        assert ended.status_code == 200

        listing = await stack.client.get("/api/v1/agents")
        assert listing.status_code == 200
        matches = [
            item for item in listing.json()["items"] if item["agent_identity"] == agent_identity
        ]
        assert len(matches) == 1
        agent = matches[0]
        assert agent["total_runs"] == 1
        assert agent["total_blocked"] == 0
        # avg_drift_score is an EMA seeded from 0.0, so after exactly one run
        # it equals 0.1 * that run's max_drift_score.
        run_detail = (
            await stack.client.get(f"/api/v1/runs/{session_id}")
        ).json()["run"]
        assert agent["avg_drift_score"] == pytest.approx(0.1 * run_detail["max_drift_score"])

    async def test_unrecognized_agent_identity_auto_creates_a_row(self, stack: Stack) -> None:
        session_id = f"agent-test-{uuid.uuid4()}"
        agent_identity = f"agent-{uuid.uuid4().hex[:8]}"
        stack.on_mission("summarise the report")

        await init_with_agent(stack, session_id, "summarise the report", agent_id=agent_identity)
        await end_session(stack, session_id)

        listing = await stack.client.get("/api/v1/agents")
        identities = {item["agent_identity"] for item in listing.json()["items"]}
        assert agent_identity in identities

    async def test_same_identity_across_two_sessions_reuses_the_same_agent_row(
        self, stack: Stack
    ) -> None:
        agent_identity = f"agent-{uuid.uuid4().hex[:8]}"

        session_1 = f"agent-test-{uuid.uuid4()}"
        stack.on_mission("first task")
        await init_with_agent(stack, session_1, "first task", agent_id=agent_identity)
        await end_session(stack, session_1)

        session_2 = f"agent-test-{uuid.uuid4()}"
        stack.on_mission("second task")
        await init_with_agent(stack, session_2, "second task", agent_id=agent_identity)
        await end_session(stack, session_2)

        listing = (await stack.client.get("/api/v1/agents")).json()["items"]
        matches = [item for item in listing if item["agent_identity"] == agent_identity]
        assert len(matches) == 1
        assert matches[0]["total_runs"] == 2

    async def test_list_agents_ordered_by_risk_score_desc(self, stack: Stack) -> None:
        low_identity = f"agent-low-{uuid.uuid4().hex[:8]}"
        high_identity = f"agent-high-{uuid.uuid4().hex[:8]}"

        low_session = f"agent-test-{uuid.uuid4()}"
        stack.on_mission("low risk task")
        await init_with_agent(stack, low_session, "low risk task", agent_id=low_identity)
        stack.set_anchor_text("low risk task")
        await call_tool(stack, low_session, "read_file", {"path": "a.txt"})
        await end_session(stack, low_session)

        high_session = f"agent-test-{uuid.uuid4()}"
        stack.on_mission("high risk task")
        await init_with_agent(stack, high_session, "high risk task", agent_id=high_identity)
        stack.set_anchor_text("high risk task")
        stack.off_mission("delete all production databases", distance=0.98)
        await call_tool(stack, high_session, "delete_all_production_databases")
        await end_session(stack, high_session)

        listing = (await stack.client.get("/api/v1/agents")).json()["items"]
        by_identity = {item["agent_identity"]: item for item in listing}
        assert low_identity in by_identity and high_identity in by_identity
        scores = [item["risk_score"] for item in listing]
        assert scores == sorted(scores, reverse=True)


@dataclass
class TenantPair:
    stack: Stack
    org_a_id: str
    org_a_key: str
    org_b_id: str
    org_b_key: str

    def headers(self, org: str) -> dict[str, str]:
        return {"X-Api-Key": self.org_a_key if org == "a" else self.org_b_key}


@pytest_asyncio.fixture
async def tenants(settings: Settings) -> AsyncIterator[TenantPair]:
    auth_settings = settings.model_copy(update={"api_keys": ["unused-legacy-fallback"]})

    upstream = create_mock_upstream()
    backend = DeterministicEmbedder(auth_settings.embedding_dimension)
    ActionEmbedder.reset()
    ActionEmbedder._instance = ActionEmbedder(backend=backend, settings=auth_settings)  # noqa: SLF001

    app = create_app(auth_settings)

    async with app.router.lifespan_context(app):
        upstream_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=upstream), base_url="http://upstream.test"
        )
        app.state.http_client = upstream_client
        app.state.proxy._client = upstream_client  # noqa: SLF001

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://ariadne.test"
        ) as client:
            stack = Stack(
                app=app, client=client, upstream=upstream, embedder=backend, settings=auth_settings
            )

            database = app.state.database
            org_a_id = uuid.uuid4().hex
            org_b_id = uuid.uuid4().hex
            raw_a, prefix_a = generate_api_key(org_a_id)
            raw_b, prefix_b = generate_api_key(org_b_id)

            async with database.session() as session:
                session.add(Organization(id=org_a_id, name="Org A", slug=f"org-a-{org_a_id[:8]}"))
                session.add(Organization(id=org_b_id, name="Org B", slug=f"org-b-{org_b_id[:8]}"))
                session.add(
                    ApiKey(
                        id=uuid.uuid4().hex,
                        organization_id=org_a_id,
                        key_hash=hash_api_key(raw_a),
                        prefix=prefix_a,
                    )
                )
                session.add(
                    ApiKey(
                        id=uuid.uuid4().hex,
                        organization_id=org_b_id,
                        key_hash=hash_api_key(raw_b),
                        prefix=prefix_b,
                    )
                )

            yield TenantPair(
                stack=stack,
                org_a_id=org_a_id,
                org_a_key=raw_a,
                org_b_id=org_b_id,
                org_b_key=raw_b,
            )

        await upstream_client.aclose()

    ActionEmbedder.reset()


async def _seed_org_a_agent(pair: TenantPair) -> str:
    stack = pair.stack
    headers = pair.headers("a")
    session_id = f"agent-tenant-{uuid.uuid4()}"
    agent_identity = f"agent-{uuid.uuid4().hex[:8]}"
    stack.on_mission("read the quarterly sales figures")

    init = await stack.client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "userRequest": "read the quarterly sales figures",
                "agent_id": agent_identity,
            },
        },
        headers={**headers, "X-Ariadne-Session-Id": session_id},
    )
    assert init.status_code == 200
    stack.set_anchor_text("read the quarterly sales figures")
    result = await stack.client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "read_file", "arguments": {"path": "sales.csv"}},
        },
        headers={**headers, "X-Ariadne-Session-Id": session_id},
    )
    assert result.status_code == 200
    end = await stack.client.post(f"/mcp/sessions/{session_id}/end", headers=headers)
    assert end.status_code == 200

    listing = await stack.client.get("/api/v1/agents", headers=headers)
    matches = [
        item for item in listing.json()["items"] if item["agent_identity"] == agent_identity
    ]
    assert len(matches) == 1
    return str(matches[0]["id"])


class TestAgentTenantIsolation:
    async def test_org_b_gets_404_not_403_on_org_a_agent(self, tenants: TenantPair) -> None:
        agent_id = await _seed_org_a_agent(tenants)

        as_a = await tenants.stack.client.get(
            f"/api/v1/agents/{agent_id}", headers=tenants.headers("a")
        )
        assert as_a.status_code == 200

        as_b = await tenants.stack.client.get(
            f"/api/v1/agents/{agent_id}", headers=tenants.headers("b")
        )
        assert as_b.status_code == 404

    async def test_org_b_agent_list_never_includes_org_a(self, tenants: TenantPair) -> None:
        await _seed_org_a_agent(tenants)

        listing = await tenants.stack.client.get(
            "/api/v1/agents", headers=tenants.headers("b")
        )
        assert listing.status_code == 200
        assert listing.json()["items"] == []

    async def test_org_b_cannot_list_org_a_agents_runs(self, tenants: TenantPair) -> None:
        agent_id = await _seed_org_a_agent(tenants)

        as_b = await tenants.stack.client.get(
            f"/api/v1/agents/{agent_id}/runs", headers=tenants.headers("b")
        )
        assert as_b.status_code == 404
