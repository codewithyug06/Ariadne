# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Durable audit trail. Writes happen off the interception hot path."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update

from ariadne.audit.schemas import AuditEvent, RunSummary
from ariadne.config import Settings, get_settings
from ariadne.db.models import LEGACY_ORG_ID, Alert, Event, Run
from ariadne.db.session import Database
from ariadne.logging import get_logger
from ariadne.proxy.schemas import utcnow

logger = get_logger(__name__)

#: Bound on unwritten events. Past this, the recorder drops the oldest rather
#: than growing without limit or blocking the proxy — enforcement continues
#: even if the audit sink stalls, and the drop is logged.
QUEUE_MAX_SIZE = 10_000


class AuditRecorder:
    """Queues audit records and drains them into the database in the background."""

    def __init__(self, database: Database, settings: Settings | None = None) -> None:
        self._db = database
        self._settings = settings or get_settings()
        self._queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
        self._task: asyncio.Task[None] | None = None
        self._dropped = 0

    # ---- Lifecycle --------------------------------------------------------

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._drain(), name="ariadne-audit-drain")
            logger.info("audit.recorder_started", queue_max_size=QUEUE_MAX_SIZE)

    async def stop(self) -> None:
        """Flush everything queued, then stop the drain task."""
        if self._task is None:
            return
        await self._queue.join()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("audit.recorder_stopped", dropped_events=self._dropped)

    # ---- Enqueue (hot path — never blocks, never raises) ------------------

    def record_event(self, event: AuditEvent, organization_id: str = LEGACY_ORG_ID) -> None:
        self._enqueue("event", (organization_id, event))

    def record_run_start(self, summary: RunSummary, organization_id: str = LEGACY_ORG_ID) -> None:
        self._enqueue("run_start", (organization_id, summary))

    def record_run_end(self, summary: RunSummary, organization_id: str = LEGACY_ORG_ID) -> None:
        self._enqueue("run_end", (organization_id, summary))

    def record_alert(
        self,
        session_id: str,
        step_index: int,
        tool_name: str,
        action: str,
        reason: str,
        drift_score: float | None = None,
        node_id: str | None = None,
        organization_id: str = LEGACY_ORG_ID,
    ) -> None:
        self._enqueue(
            "alert",
            (
                organization_id,
                Alert(
                    alert_id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    session_id=session_id,
                    step_index=step_index,
                    tool_name=tool_name,
                    action=action,
                    reason=reason,
                    drift_score=drift_score,
                    node_id=node_id,
                ),
            ),
        )

    def _enqueue(self, kind: str, payload: Any) -> None:
        try:
            self._queue.put_nowait((kind, payload))
        except asyncio.QueueFull:
            self._dropped += 1
            logger.error("audit.queue_full", kind=kind, dropped_total=self._dropped)

    # ---- Drain ------------------------------------------------------------

    async def _drain(self) -> None:
        while True:
            kind, payload = await self._queue.get()
            try:
                await self._write(kind, payload)
            except asyncio.CancelledError:
                self._queue.task_done()
                raise
            except Exception as exc:  # noqa: BLE001 - the drain loop must survive
                logger.error(
                    "audit.write_failed",
                    kind=kind,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            finally:
                self._queue.task_done()

    async def _write(self, kind: str, payload: Any) -> None:
        async with self._db.session() as session:
            if kind == "event":
                organization_id, event = payload
                session.add(_to_event_row(event, organization_id))
            elif kind == "run_start":
                organization_id, summary = payload
                # A reconnect can replay the handshake; the first record wins.
                existing = await session.scalar(
                    select(Run.session_id).where(Run.session_id == summary.session_id)
                )
                if existing is None:
                    session.add(_to_run_row(summary, organization_id))
            elif kind == "run_end":
                _organization_id, summary = payload
                values: dict[str, Any] = {
                    "ended_at": summary.ended_at or utcnow(),
                    "total_steps": summary.total_steps,
                    "final_status": summary.final_status,
                    "max_drift_score": summary.max_drift_score,
                    "blocked_count": summary.blocked_count,
                    "escalated_count": summary.escalated_count,
                    "warned_count": summary.warned_count,
                    "intent_summary": summary.intent_summary,
                }
                if summary.agent_id is not None:
                    values["agent_id"] = summary.agent_id
                await session.execute(
                    update(Run).where(Run.session_id == summary.session_id).values(**values)
                )
            elif kind == "alert":
                _organization_id, alert = payload
                session.add(alert)

    # ---- Reads ------------------------------------------------------------

    async def flush(self) -> None:
        """Wait until every queued record has been written. Used by tests and exports."""
        await self._queue.join()

    async def get_run(self, session_id: str, organization_id: str = LEGACY_ORG_ID) -> Run | None:
        async with self._db.session() as session:
            result = await session.execute(
                select(Run).where(
                    Run.session_id == session_id, Run.organization_id == organization_id
                )
            )
            return result.scalar_one_or_none()

    async def list_runs(
        self, limit: int = 50, offset: int = 0, organization_id: str = LEGACY_ORG_ID
    ) -> tuple[list[Run], int]:
        async with self._db.session() as session:
            total = await session.scalar(
                select(func.count())
                .select_from(Run)
                .where(Run.organization_id == organization_id)
            )
            result = await session.execute(
                select(Run)
                .where(Run.organization_id == organization_id)
                .order_by(Run.started_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all()), int(total or 0)

    async def list_runs_filtered(
        self,
        organization_id: str,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        agent_id: str | None = None,
        final_status: list[str] | None = None,
        limit: int = 1000,
    ) -> list[Run]:
        """Filtered run listing for the policy backtester (Feature 5A).

        A separate method from list_runs rather than adding optional filter
        params to it: list_runs is paginated (limit/offset + total count) for
        the dashboard's run list, while this is an unpaginated bulk pull
        (limit only, no offset/total) for feeding a backtest analysis loop.
        """
        async with self._db.session() as session:
            statement = select(Run).where(Run.organization_id == organization_id)
            if date_from is not None:
                statement = statement.where(Run.started_at >= date_from)
            if date_to is not None:
                statement = statement.where(Run.started_at <= date_to)
            if agent_id is not None:
                statement = statement.where(Run.agent_id == agent_id)
            if final_status:
                statement = statement.where(Run.final_status.in_(final_status))
            statement = statement.order_by(Run.started_at.desc()).limit(limit)
            result = await session.execute(statement)
            return list(result.scalars().all())

    async def get_events(
        self, session_id: str, organization_id: str = LEGACY_ORG_ID
    ) -> list[Event]:
        async with self._db.session() as session:
            result = await session.execute(
                select(Event)
                .where(
                    Event.session_id == session_id,
                    Event.organization_id == organization_id,
                )
                .order_by(Event.step_index, Event.timestamp)
            )
            return list(result.scalars().all())

    async def list_alerts(
        self,
        limit: int = 50,
        unacknowledged_only: bool = False,
        organization_id: str = LEGACY_ORG_ID,
    ) -> list[Alert]:
        async with self._db.session() as session:
            statement = (
                select(Alert)
                .where(Alert.organization_id == organization_id)
                .order_by(Alert.created_at.desc())
                .limit(limit)
            )
            if unacknowledged_only:
                statement = statement.where(Alert.acknowledged.is_(False))
            result = await session.execute(statement)
            return list(result.scalars().all())

    @property
    def dropped_events(self) -> int:
        return self._dropped

    @property
    def pending(self) -> int:
        return self._queue.qsize()


def _to_event_row(event: AuditEvent, organization_id: str = LEGACY_ORG_ID) -> Event:
    payload = dict(event.payload)
    if event.narrative is not None:
        payload["narrative"] = event.narrative
    if event.projection is not None:
        payload["projection"] = event.projection
    if event.scoring_version is not None:
        payload["scoring_version"] = event.scoring_version
    if event.calibration_note is not None:
        payload["calibration_note"] = event.calibration_note
    return Event(
        event_id=event.event_id,
        organization_id=organization_id,
        session_id=event.session_id,
        step_index=event.step_index,
        tool_name=event.tool_name,
        enforcement_action=event.enforcement_action,
        reason=event.reason,
        triggered_rule=event.triggered_rule,
        drift_score=event.drift_score,
        slope=event.slope,
        raw_distance=event.raw_distance,
        node_id=event.node_id,
        latency_ms=event.latency_ms,
        payload_json=payload,
        timestamp=event.timestamp,
    )


def _to_run_row(summary: RunSummary, organization_id: str = LEGACY_ORG_ID) -> Run:
    return Run(
        session_id=summary.session_id,
        organization_id=organization_id,
        started_at=summary.started_at,
        total_steps=summary.total_steps,
        final_status=summary.final_status,
        intent_summary=summary.intent_summary,
        intent_goal=summary.intent_summary,
        max_drift_score=summary.max_drift_score,
        agent_id=summary.agent_id,
    )
