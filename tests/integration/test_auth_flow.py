# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""End-to-end: bootstrap admin, log in, hit a protected route, RBAC on writes."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio

from ariadne.config import Settings
from tests.integration.conftest import Stack


@pytest_asyncio.fixture
async def auth_stack(settings: Settings) -> AsyncIterator[Stack]:
    """A stack with JWT auth actually configured and an admin bootstrapped."""
    import httpx  # noqa: PLC0415

    from ariadne.drift.embedder import ActionEmbedder  # noqa: PLC0415
    from ariadne.main import create_app  # noqa: PLC0415
    from tests.conftest import DeterministicEmbedder, create_mock_upstream  # noqa: PLC0415

    auth_settings = settings.model_copy(
        update={
            "jwt_secret_key": "test-only-secret-do-not-use-in-production",
            "admin_email": "admin@example.com",
            "admin_password": "correct-horse-battery-staple",
        }
    )

    upstream = create_mock_upstream()
    backend = DeterministicEmbedder(auth_settings.embedding_dimension)
    ActionEmbedder.reset()
    ActionEmbedder._instance = ActionEmbedder(  # noqa: SLF001
        backend=backend, settings=auth_settings
    )

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
            yield Stack(
                app=app, client=client, upstream=upstream, embedder=backend, settings=auth_settings
            )
        await upstream_client.aclose()
    ActionEmbedder.reset()


class TestLoginFlow:
    async def test_unauthenticated_request_is_rejected(self, auth_stack: Stack) -> None:
        response = await auth_stack.client.get("/api/v1/runs")
        assert response.status_code == 401

    async def test_health_stays_open(self, auth_stack: Stack) -> None:
        response = await auth_stack.client.get("/health")
        assert response.status_code == 200

    async def test_bootstrapped_admin_can_log_in(self, auth_stack: Stack) -> None:
        response = await auth_stack.client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["role"] == "admin"
        assert body["access_token"]
        assert "ariadne_refresh" in response.cookies

    async def test_wrong_password_is_rejected(self, auth_stack: Stack) -> None:
        response = await auth_stack.client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "not-the-password"},
        )
        assert response.status_code == 401

    async def test_access_token_reaches_a_protected_route(self, auth_stack: Stack) -> None:
        login = await auth_stack.client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
        )
        token = login.json()["access_token"]

        response = await auth_stack.client.get(
            "/api/v1/runs", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200

    async def test_me_reports_the_logged_in_identity(self, auth_stack: Stack) -> None:
        login = await auth_stack.client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
        )
        token = login.json()["access_token"]

        response = await auth_stack.client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["email"] == "admin@example.com"

    async def test_refresh_cookie_rotates_and_issues_a_new_access_token(
        self, auth_stack: Stack
    ) -> None:
        login = await auth_stack.client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
        )
        first_access_token = login.json()["access_token"]

        refreshed = await auth_stack.client.post("/api/v1/auth/refresh")
        assert refreshed.status_code == 200
        assert refreshed.json()["access_token"] != first_access_token

        # The rotated-away original refresh cookie is now dead.
        stale = await auth_stack.client.post(
            "/api/v1/auth/refresh", cookies={"ariadne_refresh": login.cookies["ariadne_refresh"]}
        )
        assert stale.status_code == 401

    async def test_logout_revokes_the_refresh_token(self, auth_stack: Stack) -> None:
        await auth_stack.client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
        )
        logout = await auth_stack.client.post("/api/v1/auth/logout")
        assert logout.status_code == 204

        refreshed = await auth_stack.client.post("/api/v1/auth/refresh")
        assert refreshed.status_code == 401


class TestRoleBasedAccess:
    async def test_viewer_cannot_write_a_policy(self, auth_stack: Stack) -> None:
        import uuid  # noqa: PLC0415

        from ariadne.auth.security import hash_password  # noqa: PLC0415
        from ariadne.db.models import User  # noqa: PLC0415

        async with auth_stack.app.state.database.session() as session:
            session.add(
                User(
                    id=uuid.uuid4().hex,
                    email="viewer@example.com",
                    password_hash=hash_password("viewer-password"),
                    role="viewer",
                )
            )

        login = await auth_stack.client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "viewer-password"},
        )
        token = login.json()["access_token"]

        response = await auth_stack.client.post(
            "/api/v1/policies",
            json={"name": "viewer-attempt", "action": "BLOCK", "tool_name_patterns": ["x"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    async def test_admin_can_write_a_policy(self, auth_stack: Stack) -> None:
        login = await auth_stack.client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
        )
        token = login.json()["access_token"]

        response = await auth_stack.client.post(
            "/api/v1/policies",
            json={"name": "admin-write", "action": "BLOCK", "tool_name_patterns": ["x"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 201


class TestPasswordChange:
    async def test_wrong_current_password_is_rejected(self, auth_stack: Stack) -> None:
        login = await auth_stack.client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
        )
        token = login.json()["access_token"]

        response = await auth_stack.client.patch(
            "/api/v1/auth/password",
            json={"current_password": "not-the-password", "new_password": "brand-new-password"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401

    async def test_successful_change_invalidates_other_sessions(self, auth_stack: Stack) -> None:
        login = await auth_stack.client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
        )
        token = login.json()["access_token"]

        response = await auth_stack.client.patch(
            "/api/v1/auth/password",
            json={
                "current_password": "correct-horse-battery-staple",
                "new_password": "brand-new-password",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 204

        # The refresh cookie from the login before the password change is
        # now dead — the point of revoking every RefreshToken on change.
        stale_refresh = await auth_stack.client.post(
            "/api/v1/auth/refresh", cookies={"ariadne_refresh": login.cookies["ariadne_refresh"]}
        )
        assert stale_refresh.status_code == 401

        relogin = await auth_stack.client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "brand-new-password"},
        )
        assert relogin.status_code == 200


class TestTeamManagement:
    async def _admin_token(self, auth_stack: Stack) -> str:
        login = await auth_stack.client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "correct-horse-battery-staple"},
        )
        token: str = login.json()["access_token"]
        return token

    async def test_admin_can_add_and_list_a_teammate(self, auth_stack: Stack) -> None:
        token = await self._admin_token(auth_stack)

        created = await auth_stack.client.post(
            "/api/v1/users",
            json={"email": "teammate@example.com", "role": "viewer"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert created.status_code == 201
        assert created.json()["temporary_password"]

        listing = await auth_stack.client.get(
            "/api/v1/users", headers={"Authorization": f"Bearer {token}"}
        )
        emails = [row["email"] for row in listing.json()]
        assert "teammate@example.com" in emails

    async def test_non_admin_is_blocked_from_every_users_route(self, auth_stack: Stack) -> None:
        import uuid

        from ariadne.auth.security import hash_password
        from ariadne.db.models import User

        async with auth_stack.app.state.database.session() as session:
            session.add(
                User(
                    id=uuid.uuid4().hex,
                    email="viewer2@example.com",
                    password_hash=hash_password("viewer-password"),
                    role="viewer",
                )
            )

        login = await auth_stack.client.post(
            "/api/v1/auth/login",
            json={"email": "viewer2@example.com", "password": "viewer-password"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        assert (await auth_stack.client.get("/api/v1/users", headers=headers)).status_code == 403
        assert (
            await auth_stack.client.post(
                "/api/v1/users", json={"email": "x@example.com", "role": "viewer"}, headers=headers
            )
        ).status_code == 403
        assert (
            await auth_stack.client.post(
                "/api/v1/users/some-id/reset-password", headers=headers
            )
        ).status_code == 403
        assert (
            await auth_stack.client.delete("/api/v1/users/some-id", headers=headers)
        ).status_code == 403

    async def test_cannot_delete_the_last_admin(self, auth_stack: Stack) -> None:
        token = await self._admin_token(auth_stack)
        me = await auth_stack.client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        admin_id = me.json()["id"]

        response = await auth_stack.client.delete(
            f"/api/v1/users/{admin_id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 409

    async def test_admin_can_delete_a_non_admin_teammate(self, auth_stack: Stack) -> None:
        token = await self._admin_token(auth_stack)
        headers = {"Authorization": f"Bearer {token}"}

        created = await auth_stack.client.post(
            "/api/v1/users", json={"email": "throwaway@example.com", "role": "viewer"}, headers=headers
        )
        user_id = created.json()["user"]["id"]

        response = await auth_stack.client.delete(f"/api/v1/users/{user_id}", headers=headers)
        assert response.status_code == 204
