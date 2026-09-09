# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""One-off: prove the RLS policies from migration f6a7b8c9d0e1 actually
enforce cross-org isolation at the database level.

`pytest` cannot prove this: the test suite (and this whole project's local
dev/CI Postgres connection) authenticates as the `postgres` superuser, and
superusers bypass RLS unconditionally regardless of policy or FORCE. This
script instead connects as a dedicated, restricted role
(`ariadne_verify`, NOSUPERUSER NOBYPASSRLS -- provisioned separately, see
the docker exec command in the PR/commit this ships with) and shows that a
raw, unscoped `SELECT * FROM runs` run as that role returns only the one
org whose `app.current_org_id` was set for that session.

    DATABASE_URL=postgresql+asyncpg://ariadne_verify:verifypass@localhost:5432/ariadne \\
        python scripts/verify_rls.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ariadne.config import get_settings


async def main_async() -> int:
    settings = get_settings()
    if not settings.database_url.startswith("postgresql"):
        print("DATABASE_URL must point at Postgres for this check", file=sys.stderr)
        return 1

    engine = create_async_engine(settings.database_url)
    org_a = uuid.uuid4().hex
    org_b = uuid.uuid4().hex
    session_a = f"verify-rls-a-{uuid.uuid4().hex[:8]}"
    session_b = f"verify-rls-b-{uuid.uuid4().hex[:8]}"

    failures: list[str] = []

    async with engine.begin() as conn:
        # Seed as this same restricted role, scoped to each org in turn --
        # INSERT is governed by the same USING clause (no WITH CHECK given
        # in the migration, so it applies to both reads and writes).
        await conn.execute(
            text("SELECT set_config('app.current_org_id', :org, true)"), {"org": org_a}
        )
        await conn.execute(
            text(
                "INSERT INTO runs (session_id, organization_id, started_at, total_steps, "
                "final_status, intent_summary, intent_goal, max_drift_score, blocked_count, "
                "escalated_count, warned_count, agent_framework, run_metadata) "
                "VALUES (:sid, :org, now(), 0, 'CLEAN', 'verify', 'verify', 0, 0, 0, 0, "
                "'verify', '{}')"
            ),
            {"sid": session_a, "org": org_a},
        )

    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.current_org_id', :org, true)"), {"org": org_b}
        )
        await conn.execute(
            text(
                "INSERT INTO runs (session_id, organization_id, started_at, total_steps, "
                "final_status, intent_summary, intent_goal, max_drift_score, blocked_count, "
                "escalated_count, warned_count, agent_framework, run_metadata) "
                "VALUES (:sid, :org, now(), 0, 'CLEAN', 'verify', 'verify', 0, 0, 0, 0, "
                "'verify', '{}')"
            ),
            {"sid": session_b, "org": org_b},
        )

    # The actual proof: scope the session to org A, then run a raw,
    # unqualified SELECT with no WHERE clause at all.
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.current_org_id', :org, true)"), {"org": org_a}
        )
        rows = (await conn.execute(text("SELECT session_id, organization_id FROM runs"))).all()
        seen_orgs = {row.organization_id for row in rows}
        seen_sessions = {row.session_id for row in rows}
        if session_b in seen_sessions:
            failures.append("org A's session saw org B's row -- RLS is NOT enforcing")
        if session_a not in seen_sessions:
            failures.append("org A's session could not see its OWN row -- policy is too strict")
        if seen_orgs - {org_a} - {"00000000-0000-0000-0000-000000000000"}:
            # LEGACY_ORG_ID rows (from other tests/seed data) are expected
            # noise, not a failure -- flag anything else.
            unexpected = seen_orgs - {org_a, "00000000-0000-0000-0000-000000000000"}
            failures.append(f"org A's session saw rows from unexpected orgs: {unexpected}")

    # Symmetric check: org B must not see org A's row either.
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.current_org_id', :org, true)"), {"org": org_b}
        )
        rows = (await conn.execute(text("SELECT session_id FROM runs"))).all()
        seen_sessions = {row.session_id for row in rows}
        if session_a in seen_sessions:
            failures.append("org B's session saw org A's row -- RLS is NOT enforcing")
        if session_b not in seen_sessions:
            failures.append("org B's session could not see its OWN row -- policy is too strict")

    # bypass_rls check: must see both.
    async with engine.begin() as conn:
        await conn.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))
        rows = (await conn.execute(text("SELECT session_id FROM runs"))).all()
        seen_sessions = {row.session_id for row in rows}
        if session_a not in seen_sessions or session_b not in seen_sessions:
            failures.append("bypass_rls=True did not see both orgs' rows")

    # Cleanup, using bypass so the delete can reach both rows regardless.
    async with engine.begin() as conn:
        await conn.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))
        await conn.execute(
            text("DELETE FROM runs WHERE session_id IN (:a, :b)"),
            {"a": session_a, "b": session_b},
        )

    await engine.dispose()

    if failures:
        print("RLS VERIFICATION FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("RLS verification passed: org A and org B sessions each see only their own rows,")
    print("neither sees the other's, and bypass_rls sees both.")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
