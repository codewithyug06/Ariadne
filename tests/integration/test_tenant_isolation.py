# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Phase 1 multi-tenancy: Org B must never see, edit, or infer Org A's data.

Every cross-org access below must 404 — never 403, never any response shape
that differs from "this session/node/policy simply doesn't exist" — so that
guessing another org's session_id or node_id cannot be used as an existence
oracle.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest_asyncio

from ariadne.auth.api_keys import generate_api_key, hash_api_key
from ariadne.config import Settings
from ariadne.db.models import ApiKey, Organization
from ariadne.drift.embedder import ActionEmbedder
from ariadne.main import create_app
from tests.conftest import DeterministicEmbedder, create_mock_upstream
from tests.integration.conftest import Stack


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
    # Auth must actually be required for the DB-backed ApiKey lookup in
    # main.py::require_api_key to run at all — a bogus legacy fallback key
    # is enough to flip `auth_required` on without ever being presented.
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


async def _seed_org_a_run(pair: TenantPair, session_id: str) -> None:
    stack = pair.stack
    headers = pair.headers("a")
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
    end = await stack.client.post(
        f"/mcp/sessions/{session_id}/end", headers=headers
    )
    assert end.status_code == 200


class TestApiKeyAuth:
    async def test_valid_key_authenticates(self, tenants: TenantPair) -> None:
        response = await tenants.stack.client.get(
            "/api/v1/runs", headers=tenants.headers("a")
        )
        assert response.status_code == 200

    async def test_unknown_key_is_rejected(self, tenants: TenantPair) -> None:
        response = await tenants.stack.client.get(
            "/api/v1/runs", headers={"X-Api-Key": "ariadne_live_org_totallyfake_nope"}
        )
        assert response.status_code == 401

    async def test_revoked_key_is_rejected(self, tenants: TenantPair) -> None:
        from sqlalchemy import select  # noqa: PLC0415

        from ariadne.proxy.schemas import utcnow  # noqa: PLC0415

        database = tenants.stack.app.state.database
        async with database.session() as session:
            row = await session.scalar(
                select(ApiKey).where(ApiKey.organization_id == tenants.org_a_id)
            )
            assert row is not None
            row.revoked_at = utcnow()

        response = await tenants.stack.client.get(
            "/api/v1/runs", headers=tenants.headers("a")
        )
        assert response.status_code == 401


class TestRunIsolation:
    async def test_org_b_cannot_read_org_a_run(self, tenants: TenantPair) -> None:
        session_id = f"tenant-test-{uuid.uuid4()}"
        await _seed_org_a_run(tenants, session_id)

        as_a = await tenants.stack.client.get(
            f"/api/v1/runs/{session_id}", headers=tenants.headers("a")
        )
        assert as_a.status_code == 200

        as_b = await tenants.stack.client.get(
            f"/api/v1/runs/{session_id}", headers=tenants.headers("b")
        )
        assert as_b.status_code == 404

    async def test_org_b_run_list_excludes_org_a(self, tenants: TenantPair) -> None:
        session_id = f"tenant-test-{uuid.uuid4()}"
        await _seed_org_a_run(tenants, session_id)

        listing = await tenants.stack.client.get("/api/v1/runs", headers=tenants.headers("b"))
        assert listing.status_code == 200
        assert all(item["session_id"] != session_id for item in listing.json()["items"])

    async def test_org_b_cannot_read_org_a_graph(self, tenants: TenantPair) -> None:
        session_id = f"tenant-test-{uuid.uuid4()}"
        await _seed_org_a_run(tenants, session_id)

        as_b = await tenants.stack.client.get(
            f"/api/v1/runs/{session_id}/graph", headers=tenants.headers("b")
        )
        assert as_b.status_code == 404

        as_a = await tenants.stack.client.get(
            f"/api/v1/runs/{session_id}/graph", headers=tenants.headers("a")
        )
        assert as_a.status_code == 200

    async def test_org_b_cannot_read_org_a_report(self, tenants: TenantPair) -> None:
        session_id = f"tenant-test-{uuid.uuid4()}"
        await _seed_org_a_run(tenants, session_id)

        as_b = await tenants.stack.client.get(
            f"/api/v1/runs/{session_id}/report", headers=tenants.headers("b")
        )
        assert as_b.status_code == 404

    async def test_org_b_root_cause_and_blast_radius_by_node_id_guessing(
        self, tenants: TenantPair
    ) -> None:
        """Even with a real node_id from Org A's graph, Org B gets nothing back."""
        session_id = f"tenant-test-{uuid.uuid4()}"
        await _seed_org_a_run(tenants, session_id)

        graph = (
            await tenants.stack.client.get(
                f"/api/v1/runs/{session_id}/graph", headers=tenants.headers("a")
            )
        ).json()
        node_id = graph["nodes"][0]["id"]

        root_cause = await tenants.stack.client.get(
            f"/api/v1/runs/{session_id}/root-cause",
            params={"node_id": node_id},
            headers=tenants.headers("b"),
        )
        assert root_cause.status_code == 404

        blast = await tenants.stack.client.get(
            f"/api/v1/runs/{session_id}/blast-radius",
            params={"node_id": node_id},
            headers=tenants.headers("b"),
        )
        assert blast.status_code == 200
        assert blast.json()["affected_node_ids"] == []


class TestGraphStoreIsolation:
    async def test_store_returns_nothing_cross_org(self, tenants: TenantPair) -> None:
        session_id = f"tenant-test-{uuid.uuid4()}"
        await _seed_org_a_run(tenants, session_id)

        builder = tenants.stack.app.state.graph_builder
        as_a = await builder.session_graph(session_id, tenants.org_a_id)
        as_b = await builder.session_graph(session_id, tenants.org_b_id)

        assert as_a.nodes
        assert as_b.nodes == []
        assert as_b.edges == []


class TestPolicyIsolation:
    async def test_org_b_cannot_delete_org_a_policy(self, tenants: TenantPair) -> None:
        name = f"tenant-policy-{uuid.uuid4().hex[:8]}"
        created = await tenants.stack.client.post(
            "/api/v1/policies",
            json={"name": name, "description": "org a rule", "action": "BLOCK"},
            headers=tenants.headers("a"),
        )
        assert created.status_code == 201

        deleted_by_b = await tenants.stack.client.delete(
            f"/api/v1/policies/{name}", headers=tenants.headers("b")
        )
        assert deleted_by_b.status_code == 404

        deleted_by_a = await tenants.stack.client.delete(
            f"/api/v1/policies/{name}", headers=tenants.headers("a")
        )
        assert deleted_by_a.status_code == 204

    async def test_org_b_cannot_create_same_named_policy(self, tenants: TenantPair) -> None:
        name = f"tenant-policy-{uuid.uuid4().hex[:8]}"
        first = await tenants.stack.client.post(
            "/api/v1/policies",
            json={"name": name, "description": "org a rule", "action": "BLOCK"},
            headers=tenants.headers("a"),
        )
        assert first.status_code == 201

        second = await tenants.stack.client.post(
            "/api/v1/policies",
            json={"name": name, "description": "org b rule", "action": "WARN"},
            headers=tenants.headers("b"),
        )
        assert second.status_code == 409


class TestApiKeyManagement:
    async def test_org_scoped_key_listing(self, tenants: TenantPair) -> None:
        listing_a = await tenants.stack.client.get("/api/v1/keys", headers=tenants.headers("a"))
        assert listing_a.status_code == 200
        assert len(listing_a.json()) == 1

        created = await tenants.stack.client.post("/api/v1/keys", headers=tenants.headers("a"))
        assert created.status_code == 201
        assert created.json()["raw_key"].startswith("ariadne_live_org_")

        listing_b = await tenants.stack.client.get("/api/v1/keys", headers=tenants.headers("b"))
        assert listing_b.status_code == 200
        assert len(listing_b.json()) == 1  # unaffected by Org A's create

    async def test_org_b_cannot_revoke_org_a_key(self, tenants: TenantPair) -> None:
        listing_a = (
            await tenants.stack.client.get("/api/v1/keys", headers=tenants.headers("a"))
        ).json()
        key_id = listing_a[0]["id"]

        revoked_by_b = await tenants.stack.client.delete(
            f"/api/v1/keys/{key_id}", headers=tenants.headers("b")
        )
        assert revoked_by_b.status_code == 404
