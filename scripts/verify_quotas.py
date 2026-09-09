# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""One-off: prove per-org quota enforcement (ariadne/billing/quotas.py)
works through the real /mcp JSON-RPC endpoint against Postgres.

tests/unit/test_quotas.py already covers the counting/limit-comparison
logic in isolation against SQLite (fast, runs in CI). This script is the
second layer, same split as scripts/verify_rls.py / verify_rls_app.py:
proving the actual HTTP call path -- require_org_scope resolving the
caller's org, MCPProxy.handle's "initialize" branch checking the quota
before starting a session, the JSON-RPC error shape reaching the client
-- behaves as documented, against a real Postgres-backed app.

Sets max_sessions_per_month=0 on a fresh org (blocks immediately, no
need to actually burn quota first) and confirms the very first
`initialize` call is rejected with JSONRPCErrorCode.ARIADNE_QUOTA_EXCEEDED
(-32005), then confirms an org with no configured limit is unaffected.

    DATABASE_URL=postgresql+asyncpg://ariadne_verify:verifypass@localhost:5432/ariadne \\
        python scripts/verify_quotas.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid

import httpx

from ariadne.auth.api_keys import generate_api_key, hash_api_key
from ariadne.billing.quotas import SESSIONS_LIMIT_KEY
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
        ARIADNE_API_KEYS=["unused-legacy-fallback"],
    )

    app = create_app(settings)
    failures: list[str] = []

    async with app.router.lifespan_context(app):
        database = app.state.database
        blocked_org_id = uuid.uuid4().hex
        unlimited_org_id = uuid.uuid4().hex
        raw_blocked, prefix_blocked = generate_api_key(blocked_org_id)
        raw_unlimited, prefix_unlimited = generate_api_key(unlimited_org_id)

        async with database.session(bypass_rls=True) as session:
            session.add(
                Organization(
                    id=blocked_org_id,
                    name="Quota Blocked",
                    slug=f"quota-blocked-{blocked_org_id[:8]}",
                    settings={SESSIONS_LIMIT_KEY: 0},
                )
            )
            session.add(
                Organization(
                    id=unlimited_org_id,
                    name="Quota Unlimited",
                    slug=f"quota-unlimited-{unlimited_org_id[:8]}",
                )
            )
            await session.flush()
            session.add(
                ApiKey(
                    id=uuid.uuid4().hex,
                    organization_id=blocked_org_id,
                    key_hash=hash_api_key(raw_blocked),
                    prefix=prefix_blocked,
                )
            )
            session.add(
                ApiKey(
                    id=uuid.uuid4().hex,
                    organization_id=unlimited_org_id,
                    key_hash=hash_api_key(raw_unlimited),
                    prefix=prefix_unlimited,
                )
            )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://ariadne.test"
        ) as client:
            blocked_response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 0,
                    "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "userRequest": "test"},
                },
                headers={
                    "X-Api-Key": raw_blocked,
                    "X-Ariadne-Session-Id": f"quota-verify-{uuid.uuid4().hex[:8]}",
                },
            )
            body = blocked_response.json()
            error = body.get("error")
            if error is None:
                failures.append(
                    f"org with max_sessions_per_month=0 was allowed to initialize: {body!r}"
                )
            elif error.get("code") != -32005:
                failures.append(
                    f"quota-blocked org's initialize failed with the wrong error code: {error!r} "
                    "(expected -32005 / ARIADNE_QUOTA_EXCEEDED)"
                )
            else:
                print(
                    f"  (confirmed: quota-blocked org's initialize rejected with "
                    f"{error['message']!r})"
                )

            unlimited_response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 0,
                    "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "userRequest": "test"},
                },
                headers={
                    "X-Api-Key": raw_unlimited,
                    "X-Ariadne-Session-Id": f"quota-verify-{uuid.uuid4().hex[:8]}",
                },
            )
            # Only asserting it wasn't blocked *by quota* -- there's no real
            # upstream MCP server at upstream.test, so the request
            # legitimately fails past that point with ARIADNE_UPSTREAM_ERROR
            # once the quota check (correctly) lets it through. That failure
            # is expected and out of scope for this check.
            unlimited_body = unlimited_response.json()
            unlimited_error = unlimited_body.get("error")
            if unlimited_error is not None and unlimited_error.get("code") == -32005:
                failures.append(
                    f"org with no configured quota was rejected by quota: {unlimited_error!r}"
                )
            else:
                print("  (confirmed: org with no configured quota is not blocked by quota)")

    if failures:
        print("QUOTA VERIFICATION FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("Quota verification passed: a zero-quota org is rejected on the real /mcp endpoint,")
    print("an unlimited org is unaffected.")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
