# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""One-off: prove the running application -- not raw SQL -- actually
enforces RLS end-to-end through real HTTP routes.

verify_rls.py proves the policy expression itself is correct with hand-
written SQL. It never touches Database.session(), a route, or any of the
~54 call sites the RLS sweep edited. This script closes that gap: it
builds the real FastAPI app (ariadne.main.create_app), points it at
Postgres through the restricted `ariadne_verify` role (NOSUPERUSER
NOBYPASSRLS -- see scripts/verify_rls.py's docstring for how that role is
provisioned), and drives it exactly like
tests/integration/test_tenant_isolation.py does over real HTTP, except
against Postgres with RLS live instead of pytest's per-test SQLite
sandbox (tests/conftest.py's `settings` fixture hardcodes
DATABASE_URL to an isolated tmp-file SQLite db regardless of the
environment -- deliberate test isolation, not something to route around,
which is exactly why this needs its own script).

Two checks:

  1. A basic org-scoped read works through the restricted role -- proves
     the RLS mechanism doesn't just fail closed on every query.
  2. Org B creating a policy with the same `name` as Org A's still
     returns a clean 409, not an IntegrityError -- `policies` is
     deliberately excluded from the RLS table list (see migration
     f6a7b8c9d0e1's docstring: its global `name` primary key collided
     with RLS's SELECT-hiding, turning the app's own conflict check into
     an unhandled 500 when this table *was* included -- found by an
     earlier run of this exact script, fixed by excluding it). This
     check now guards against that regression coming back.

    DATABASE_URL=postgresql+asyncpg://ariadne_verify:verifypass@localhost:5432/ariadne \\
        python scripts/verify_rls_app.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid

import httpx

from ariadne.auth.api_keys import generate_api_key, hash_api_key
from ariadne.config import Settings
from ariadne.db.models import ApiKey, Organization
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
        ARIADNE_API_KEYS=["unused-legacy-fallback"],  # flips auth_required on
    )

    app = create_app(settings)
    failures: list[str] = []

    async with app.router.lifespan_context(app):
        database = app.state.database
        org_a_id = uuid.uuid4().hex
        org_b_id = uuid.uuid4().hex
        raw_a, prefix_a = generate_api_key(org_a_id)
        raw_b, prefix_b = generate_api_key(org_b_id)

        async with database.session(bypass_rls=True) as session:
            session.add(Organization(id=org_a_id, name="Verify A", slug=f"verify-a-{org_a_id[:8]}"))
            session.add(Organization(id=org_b_id, name="Verify B", slug=f"verify-b-{org_b_id[:8]}"))
            # Explicit flush before the FK-dependent ApiKey inserts --
            # without it, SQLAlchemy's automatic cross-table flush ordering
            # (no ORM relationship() configured between these two, just raw
            # FK columns) can emit the api_keys batch before the
            # organizations rows are visible to it. Real call sites never
            # hit this: every production path inserts one row per request,
            # never Organization+ApiKey together in one flush.
            await session.flush()
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

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://ariadne.test"
        ) as client:
            # Check 1: org-scoped route works at all under a real HTTP
            # round trip through the restricted role.
            listing = await client.get("/api/v1/runs", headers={"X-Api-Key": raw_a})
            if listing.status_code != 200:
                failures.append(
                    f"GET /api/v1/runs as org A returned {listing.status_code}, expected 200 "
                    "-- a basic org-scoped read is broken under RLS"
                )

            # Check 2: the documented policies.name global-PK tradeoff.
            name = f"verify-rls-app-{uuid.uuid4().hex[:8]}"
            created = await client.post(
                "/api/v1/policies",
                json={"name": name, "description": "org a rule", "action": "BLOCK"},
                headers={"X-Api-Key": raw_a},
            )
            if created.status_code != 201:
                failures.append(
                    f"org A policy create returned {created.status_code}, expected 201"
                )

            try:
                collided = await client.post(
                    "/api/v1/policies",
                    json={"name": name, "description": "org b rule", "action": "WARN"},
                    headers={"X-Api-Key": raw_b},
                )
            except Exception as exc:  # noqa: BLE001 - a raise here IS the regression
                failures.append(
                    f"org B's same-named policy create raised {exc!r} instead of "
                    "returning a clean 409 -- the `policies` RLS exclusion in migration "
                    "f6a7b8c9d0e1 may have regressed"
                )
            else:
                if collided.status_code != 409:
                    failures.append(
                        f"org B's same-named policy create returned {collided.status_code}, "
                        "expected 409"
                    )
                else:
                    print("  (confirmed: policies name-collision still returns a clean 409)")

            # Cleanup org A's row so repeat runs don't accumulate.
            await client.delete(f"/api/v1/policies/{name}", headers={"X-Api-Key": raw_a})

    if failures:
        print("APP-LEVEL RLS VERIFICATION FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("App-level RLS verification passed: real HTTP routes through the restricted role")
    print("behave as documented (org-scoped reads work, policies' RLS exclusion still")
    print("returns a clean 409 on a name collision instead of the IntegrityError regression).")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
