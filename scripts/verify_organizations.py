# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""One-off: prove org signup and org deletion (ariadne/api/organizations.py)
work through the real HTTP routes against Postgres.

tests/unit/test_organizations.py already covers slug derivation and the
delete-sweep logic directly against SQLite. This script is the second
layer, same split as scripts/verify_rls.py / verify_rls_app.py and
verify_quotas.py: proving the actual HTTP call path -- an unauthenticated
POST /api/v1/orgs creating a real tenant, that tenant's own key then being
usable against an org-scoped route, and DELETE /api/v1/orgs/current
actually removing rows from every org-scoped table, not just the
`organizations` row -- against a real Postgres-backed app, through the
restricted (NOSUPERUSER NOBYPASSRLS) ariadne_verify role so RLS is live.

    DATABASE_URL=postgresql+asyncpg://ariadne_verify:verifypass@localhost:5432/ariadne \\
        python scripts/verify_organizations.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid

import httpx
from sqlalchemy import select

from ariadne.config import Settings
from ariadne.db.models import Organization, Run, User
from ariadne.main import create_app


async def main_async() -> int:
    database_url = Settings(_env_file=None).database_url
    if not database_url.startswith("postgresql"):
        print("DATABASE_URL must point at Postgres for this check", file=sys.stderr)
        return 1

    settings = Settings(
        _env_file=None,
        DATABASE_URL=database_url,
        UPSTREAM_MCP_URL="http://upstream.test/mcp",
        EMBEDDING_DEVICE="cpu",
        OLLAMA_URL="http://localhost:1",
        ARCADEDB_URL=None,
        OPA_URL=None,
        HITL_WEBHOOK_URL=None,
        LOG_LEVEL="WARNING",
        ARIADNE_API_KEYS=["unused-legacy-fallback"],
    )

    app = create_app(settings)
    failures: list[str] = []
    email = f"verify-{uuid.uuid4().hex[:8]}@example.com"

    async with app.router.lifespan_context(app):
        database = app.state.database

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://ariadne.test"
        ) as client:
            signup_response = await client.post(
                "/api/v1/orgs",
                json={
                    "organization_name": "Verify Org",
                    "admin_email": email,
                    "admin_password": "correct horse battery staple",
                },
            )
            if signup_response.status_code != 201:
                failures.append(
                    f"signup failed: {signup_response.status_code} {signup_response.text}"
                )
                return _report(failures)

            body = signup_response.json()
            org_id = body["organization"]["id"]
            raw_key = body["api_key"]
            print(
                f"  (confirmed: signup created org {org_id!r}, "
                f"slug {body['organization']['slug']!r})"
            )

            duplicate_response = await client.post(
                "/api/v1/orgs",
                json={
                    "organization_name": "Verify Org Again",
                    "admin_email": email,
                    "admin_password": "another password entirely",
                },
            )
            if duplicate_response.status_code != 409:
                failures.append(
                    f"duplicate-email signup should be 409, got {duplicate_response.status_code}"
                )
            else:
                print("  (confirmed: duplicate admin_email signup rejected with 409)")

            runs_response = await client.get("/api/v1/runs", headers={"X-Api-Key": raw_key})
            if runs_response.status_code != 200:
                failures.append(
                    f"fresh org's own key could not call an org-scoped route: "
                    f"{runs_response.status_code} {runs_response.text}"
                )
            else:
                print("  (confirmed: the new org's own API key works against an org-scoped route)")

            async with database.session(org_id) as session:
                session.add(
                    Run(
                        session_id=str(uuid.uuid4()),
                        organization_id=org_id,
                        total_steps=1,
                        final_status="CLEAN",
                        intent_summary="t",
                        intent_goal="t",
                        max_drift_score=0.0,
                        blocked_count=0,
                        escalated_count=0,
                        warned_count=0,
                        agent_framework="test",
                        run_metadata={},
                    )
                )

            delete_response = await client.delete(
                "/api/v1/orgs/current", headers={"X-Api-Key": raw_key}
            )
            if delete_response.status_code != 204:
                failures.append(
                    f"delete failed: {delete_response.status_code} {delete_response.text}"
                )
            else:
                print("  (confirmed: DELETE /api/v1/orgs/current returned 204)")

        async with database.session(bypass_rls=True) as session:
            if await session.get(Organization, org_id) is not None:
                failures.append("organizations row still present after delete")
            if (
                await session.scalar(select(User).where(User.organization_id == org_id))
            ) is not None:
                failures.append("users row still present after delete")
            if (await session.scalar(select(Run).where(Run.organization_id == org_id))) is not None:
                failures.append("runs row still present after delete")
            if not any("still present" in f for f in failures):
                print("  (confirmed: organizations/users/runs rows all gone after delete)")

    if failures:
        return _report(failures)

    print(
        "Organization lifecycle verification passed: signup, duplicate-email rejection,\n"
        "the new key working against an org-scoped route, and full delete sweep all behave\n"
        "as documented on the real /api/v1/orgs routes against Postgres."
    )
    return 0


def _report(failures: list[str]) -> int:
    print("ORGANIZATION LIFECYCLE VERIFICATION FAILED:")
    for f in failures:
        print(f"  - {f}")
    return 1


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
