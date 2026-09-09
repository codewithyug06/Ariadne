# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Per-org usage quotas (ariadne/billing/quotas.py).

Unit-level against the real `database` fixture (in-memory SQLite), same
style as test_trajectory_recorder.py -- the whole point of this module is
what it counts and compares, so a real session round-trip over real Run/
Event rows is more honest than mocking the session. RLS itself is
Postgres-only and covered separately (scripts/verify_rls*.py); this suite
never touches it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from ariadne.billing.quotas import (
    SESSIONS_LIMIT_KEY,
    TOOL_CALLS_LIMIT_KEY,
    QuotaEnforcer,
)
from ariadne.db.models import Event, Organization, Run
from ariadne.db.session import Database
from ariadne.proxy.schemas import utcnow


async def _make_org(database: Database, org_id: str, settings: dict[str, object]) -> None:
    async with database.session(org_id) as session:
        session.add(Organization(id=org_id, name="t", slug=f"t-{org_id[:8]}", settings=settings))


async def _add_run(database: Database, org_id: str, started_at: datetime) -> None:
    async with database.session(org_id) as session:
        session.add(
            Run(
                session_id=str(uuid.uuid4()),
                organization_id=org_id,
                started_at=started_at,
                total_steps=0,
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


async def _add_event(database: Database, org_id: str, timestamp: datetime) -> None:
    async with database.session(org_id) as session:
        session.add(
            Event(
                event_id=str(uuid.uuid4()),
                organization_id=org_id,
                session_id=str(uuid.uuid4()),
                step_index=0,
                tool_name="t",
                enforcement_action="ALLOW",
                reason="t",
                latency_ms=0.0,
                payload_json={},
                timestamp=timestamp,
            )
        )


class TestNoLimitConfigured:
    async def test_missing_key_means_unlimited(self, database: Database) -> None:
        org_id = str(uuid.uuid4())
        await _make_org(database, org_id, settings={})
        enforcer = QuotaEnforcer(database)

        result = await enforcer.check_session_quota(org_id)
        assert result.allowed
        assert result.limit is None

    async def test_unknown_org_means_unlimited_not_blocked(self, database: Database) -> None:
        # An org that doesn't exist yet (or was never seeded settings) must
        # never be treated as quota-zero -- fail open, not closed, on
        # missing config.
        enforcer = QuotaEnforcer(database)
        result = await enforcer.check_tool_call_quota(str(uuid.uuid4()))
        assert result.allowed
        assert result.limit is None


class TestSessionQuota:
    async def test_under_limit_is_allowed(self, database: Database) -> None:
        org_id = str(uuid.uuid4())
        await _make_org(database, org_id, settings={SESSIONS_LIMIT_KEY: 5})
        now = utcnow()
        for _ in range(3):
            await _add_run(database, org_id, now)

        enforcer = QuotaEnforcer(database)
        result = await enforcer.check_session_quota(org_id)
        assert result.allowed
        assert result.limit == 5
        assert result.used == 3

    async def test_at_limit_is_blocked(self, database: Database) -> None:
        org_id = str(uuid.uuid4())
        await _make_org(database, org_id, settings={SESSIONS_LIMIT_KEY: 2})
        now = utcnow()
        for _ in range(2):
            await _add_run(database, org_id, now)

        enforcer = QuotaEnforcer(database)
        result = await enforcer.check_session_quota(org_id)
        assert not result.allowed
        assert result.used == 2
        assert result.limit == 2

    async def test_zero_limit_blocks_immediately(self, database: Database) -> None:
        org_id = str(uuid.uuid4())
        await _make_org(database, org_id, settings={SESSIONS_LIMIT_KEY: 0})

        enforcer = QuotaEnforcer(database)
        result = await enforcer.check_session_quota(org_id)
        assert not result.allowed
        assert result.limit == 0

    async def test_runs_from_last_month_do_not_count(self, database: Database) -> None:
        org_id = str(uuid.uuid4())
        await _make_org(database, org_id, settings={SESSIONS_LIMIT_KEY: 1})
        last_month = utcnow() - timedelta(days=40)
        await _add_run(database, org_id, last_month)

        enforcer = QuotaEnforcer(database)
        result = await enforcer.check_session_quota(org_id)
        assert result.allowed
        assert result.used == 0

    async def test_other_orgs_runs_do_not_count(self, database: Database) -> None:
        org_a = str(uuid.uuid4())
        org_b = str(uuid.uuid4())
        await _make_org(database, org_a, settings={SESSIONS_LIMIT_KEY: 1})
        await _make_org(database, org_b, settings={})
        now = utcnow()
        for _ in range(5):
            await _add_run(database, org_b, now)

        enforcer = QuotaEnforcer(database)
        result = await enforcer.check_session_quota(org_a)
        assert result.allowed
        assert result.used == 0


class TestToolCallQuota:
    async def test_under_limit_is_allowed(self, database: Database) -> None:
        org_id = str(uuid.uuid4())
        await _make_org(database, org_id, settings={TOOL_CALLS_LIMIT_KEY: 10})
        now = utcnow()
        for _ in range(4):
            await _add_event(database, org_id, now)

        enforcer = QuotaEnforcer(database)
        result = await enforcer.check_tool_call_quota(org_id)
        assert result.allowed
        assert result.used == 4

    async def test_over_limit_is_blocked(self, database: Database) -> None:
        org_id = str(uuid.uuid4())
        await _make_org(database, org_id, settings={TOOL_CALLS_LIMIT_KEY: 3})
        now = utcnow()
        for _ in range(3):
            await _add_event(database, org_id, now)

        enforcer = QuotaEnforcer(database)
        result = await enforcer.check_tool_call_quota(org_id)
        assert not result.allowed

    async def test_negative_limit_in_settings_is_ignored_as_unlimited(
        self, database: Database
    ) -> None:
        # Defensive: malformed/legacy settings data shouldn't be able to
        # produce a nonsensical negative limit that blocks everything.
        org_id = str(uuid.uuid4())
        await _make_org(database, org_id, settings={TOOL_CALLS_LIMIT_KEY: -1})

        enforcer = QuotaEnforcer(database)
        result = await enforcer.check_tool_call_quota(org_id)
        assert result.allowed
        assert result.limit is None


class TestCaching:
    async def test_result_is_cached_within_ttl(self, database: Database) -> None:
        org_id = str(uuid.uuid4())
        await _make_org(database, org_id, settings={SESSIONS_LIMIT_KEY: 10})
        now = utcnow()
        await _add_run(database, org_id, now)

        enforcer = QuotaEnforcer(database)
        first = await enforcer.check_session_quota(org_id)
        assert first.used == 1

        # A second run lands, but the cached count should still be used
        # within the TTL window -- proves the cache is actually consulted,
        # not just present and unused.
        await _add_run(database, org_id, now)
        second = await enforcer.check_session_quota(org_id)
        assert second.used == 1

    async def test_different_orgs_have_independent_caches(self, database: Database) -> None:
        org_a = str(uuid.uuid4())
        org_b = str(uuid.uuid4())
        await _make_org(database, org_a, settings={SESSIONS_LIMIT_KEY: 10})
        await _make_org(database, org_b, settings={SESSIONS_LIMIT_KEY: 10})
        now = utcnow()
        await _add_run(database, org_a, now)
        await _add_run(database, org_b, now)
        await _add_run(database, org_b, now)

        enforcer = QuotaEnforcer(database)
        a_result = await enforcer.check_session_quota(org_a)
        b_result = await enforcer.check_session_quota(org_b)
        assert a_result.used == 1
        assert b_result.used == 2
