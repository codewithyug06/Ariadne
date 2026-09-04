# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Aggregate trends over runs/events/alerts — the dashboard's Analytics page.

Aggregation happens in Python rather than DB-specific date-truncation SQL so
the same query works unmodified against SQLite (dev/default) and Postgres
(scripts/backup_db.sh and the README's scaling path) — see
ariadne/db/models.py's use of the generic SQLAlchemy JSON type for the same
portability reason.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from ariadne.db.models import Event, Run

router = APIRouter(prefix="/analytics", tags=["analytics"])


class DailyVolume(BaseModel):
    date: str
    total: int
    allowed: int
    warned: int
    escalated: int
    blocked: int


class TriggeredRule(BaseModel):
    rule: str
    count: int


class AnalyticsSummary(BaseModel):
    since: str
    until: str
    total_runs: int
    total_events: int
    decisions_by_action: dict[str, int]
    drift_score_buckets: dict[str, int]
    top_triggered_rules: list[TriggeredRule]
    daily_volume: list[DailyVolume]


_DRIFT_BUCKETS = [(0, 20), (20, 40), (40, 66.5), (66.5, 86.5), (86.5, 101)]
_DRIFT_LABELS = ["0-20", "20-40", "40-warn", "warn-block", "86.5+"]


@router.get("/summary", response_model=AnalyticsSummary, summary="Trends over a time window")
async def analytics_summary(
    request: Request,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
) -> AnalyticsSummary:
    database = request.app.state.database
    now = datetime.now(UTC)
    window_until = until or now
    window_since = since or (window_until - timedelta(days=30))

    async with database.session() as session:
        runs = (
            (
                await session.execute(
                    select(Run).where(
                        Run.started_at >= window_since, Run.started_at <= window_until
                    )
                )
            )
            .scalars()
            .all()
        )
        session_ids = [run.session_id for run in runs]
        events = []
        if session_ids:
            events = (
                (await session.execute(select(Event).where(Event.session_id.in_(session_ids))))
                .scalars()
                .all()
            )

    decisions_by_action: Counter[str] = Counter(event.enforcement_action for event in events)
    triggered_rules: Counter[str] = Counter(
        event.triggered_rule for event in events if event.triggered_rule
    )
    drift_buckets: Counter[str] = Counter()
    for event in events:
        if event.drift_score is None:
            continue
        for (low, high), label in zip(_DRIFT_BUCKETS, _DRIFT_LABELS, strict=True):
            if low <= event.drift_score < high:
                drift_buckets[label] += 1
                break

    by_day: dict[str, Counter[str]] = defaultdict(Counter)
    for run in runs:
        day = run.started_at.date().isoformat()
        by_day[day]["total"] += 1
        by_day[day][run.final_status] += 1

    daily_volume = [
        DailyVolume(
            date=day,
            total=counts["total"],
            allowed=counts.get("CLEAN", 0),
            warned=counts.get("WARNED", 0),
            escalated=counts.get("ESCALATED", 0),
            blocked=counts.get("BLOCKED", 0),
        )
        for day, counts in sorted(by_day.items())
    ]

    return AnalyticsSummary(
        since=window_since.isoformat(),
        until=window_until.isoformat(),
        total_runs=len(runs),
        total_events=len(events),
        decisions_by_action=dict(decisions_by_action),
        drift_score_buckets={label: drift_buckets.get(label, 0) for label in _DRIFT_LABELS},
        top_triggered_rules=[
            TriggeredRule(rule=rule, count=count)
            for rule, count in triggered_rules.most_common(10)
        ],
        daily_volume=daily_volume,
    )
