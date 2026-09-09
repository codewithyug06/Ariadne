# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Per-org usage quotas: sessions/month and tool-calls/month.

Limits live in `Organization.settings` (the existing JSON column, no
schema change) under `max_sessions_per_month` / `max_tool_calls_per_month`.
A missing key means unlimited -- not zero, which would instantly block
every existing org the moment this ships.

Usage is counted live (`SELECT count(*) FROM runs/events WHERE
organization_id = ... AND <timestamp column> >= <month start>`) rather
than tracked in a separate counter table -- both columns already exist,
and a separate counter invites drift from the source of truth. `runs` has
an index on `started_at` (ix_runs_started_at); `events` has none on
`timestamp`, so counting events per-org would be a sequential scan on
every tool call without caching -- the short-TTL cache below exists
specifically for that column, mirroring the identical pattern already in
ariadne/proxy/interceptor.py's `_calibration_cache` /
`_tool_override_cache`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select

from ariadne.db.models import Event, Organization, Run
from ariadne.db.session import Database

#: Matches _CALIBRATION_CACHE_TTL_SECONDS in interceptor.py -- same
#: reasoning: short enough that a just-raised limit takes effect quickly,
#: long enough to keep a busy org off the count query on every call.
_USAGE_CACHE_TTL_SECONDS = 30.0

SESSIONS_LIMIT_KEY = "max_sessions_per_month"
TOOL_CALLS_LIMIT_KEY = "max_tool_calls_per_month"


@dataclass(frozen=True)
class QuotaCheckResult:
    allowed: bool
    #: None when allowed, or when no limit is configured for this org.
    limit: int | None
    #: Usage count at the time of this check (pre-increment -- the call/
    #: session that triggered this check hasn't been recorded yet).
    used: int
    period_start: datetime


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class QuotaEnforcer:
    """Checks org usage against configured monthly limits.

    Constructed once per process (mirrors TrajectoryRecorder's lifecycle,
    see MCPProxy.__init__) and shared across all sessions/requests.
    """

    def __init__(self, database: Database) -> None:
        self._db = database
        self._session_count_cache: dict[str, tuple[float, int]] = {}
        self._tool_call_count_cache: dict[str, tuple[float, int]] = {}

    async def _limits(self, organization_id: str) -> dict[str, int]:
        async with self._db.session(organization_id) as session:
            org = await session.get(Organization, organization_id)
        if org is None:
            return {}
        settings = org.settings or {}
        limits: dict[str, int] = {}
        for key in (SESSIONS_LIMIT_KEY, TOOL_CALLS_LIMIT_KEY):
            value = settings.get(key)
            if isinstance(value, int) and value >= 0:
                limits[key] = value
        return limits

    async def _session_count_this_month(self, organization_id: str) -> int:
        now = time.monotonic()
        cached = self._session_count_cache.get(organization_id)
        if cached is not None and now - cached[0] < _USAGE_CACHE_TTL_SECONDS:
            return cached[1]

        period_start = _month_start(datetime.now(UTC))
        async with self._db.session(organization_id) as session:
            count = await session.scalar(
                select(func.count())
                .select_from(Run)
                .where(Run.organization_id == organization_id, Run.started_at >= period_start)
            )
        result = int(count or 0)
        self._session_count_cache[organization_id] = (now, result)
        return result

    async def _tool_call_count_this_month(self, organization_id: str) -> int:
        now = time.monotonic()
        cached = self._tool_call_count_cache.get(organization_id)
        if cached is not None and now - cached[0] < _USAGE_CACHE_TTL_SECONDS:
            return cached[1]

        period_start = _month_start(datetime.now(UTC))
        async with self._db.session(organization_id) as session:
            count = await session.scalar(
                select(func.count())
                .select_from(Event)
                .where(
                    Event.organization_id == organization_id,
                    Event.timestamp >= period_start,
                )
            )
        result = int(count or 0)
        self._tool_call_count_cache[organization_id] = (now, result)
        return result

    async def check_session_quota(self, organization_id: str) -> QuotaCheckResult:
        """Call before creating a new session (MCPProxy.handle's "initialize" branch)."""
        period_start = _month_start(datetime.now(UTC))
        limits = await self._limits(organization_id)
        limit = limits.get(SESSIONS_LIMIT_KEY)
        if limit is None:
            return QuotaCheckResult(True, None, 0, period_start)
        used = await self._session_count_this_month(organization_id)
        return QuotaCheckResult(used < limit, limit, used, period_start)

    async def check_tool_call_quota(self, organization_id: str) -> QuotaCheckResult:
        """Call before running a tool call (MCPProxy._handle_tool_call, before intercept)."""
        period_start = _month_start(datetime.now(UTC))
        limits = await self._limits(organization_id)
        limit = limits.get(TOOL_CALLS_LIMIT_KEY)
        if limit is None:
            return QuotaCheckResult(True, None, 0, period_start)
        used = await self._tool_call_count_this_month(organization_id)
        return QuotaCheckResult(used < limit, limit, used, period_start)
