# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Durable audit trail. Writes happen off the interception hot path."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from typing import Any

from sqlalchemy import func, select, update

from ariadne.audit.schemas import AuditEvent, RunSummary
from ariadne.config import Settings, get_settings
from ariadne.db.models import Alert, Event, Run
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

    def record_event(self, event: AuditEvent) -> None:
        self._enqueue("event", event)

    def record_run_start(self, summary: RunSummary) -> None:
        self._enqueue("run_start", summary)

    def record_run_end(self, summary: RunSummary) -> None:
        self._enqueue("run_end", summary)

    def record_alert(
        self,
        session_id: str,
        step_index: int,
        tool_name: str,
        action: str,
        reason: str,
        drift_score: float | None = None,
        node_id: str | None = None,
    ) -> None:
        self._enqueue(
            "alert",
            Alert(
                alert_id=str(uuid.uuid4()),
                session_id=session_id,
                step_index=step_index,
                tool_name=tool_name,
                action=action,
                reason=reason,
                drift_score=drift_score,
                node_id=node_id,
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
                session.add(_to_event_row(payload))
            elif kind == "run_start":
                # A reconnect can replay the handshake; the first record wins.
                existing = await session.scalar(
                    select(Run.session_id).where(Run.session_id == payload.session_id)
                )
                if existing is None:
                    session.add(_to_run_row(payload))
            elif kind == "run_end":
                await session.execute(
                    update(Run)
                    .where(Run.session_id == payload.session_id)
                    .values(
                        ended_at=payload.ended_at or utcnow(),
                        total_steps=payload.total_steps,
                        final_status=payload.final_status,
                        max_drift_score=payload.max_drift_score,
                        blocked_count=payload.blocked_count,
                        escalated_count=payload.escalated_count,
                        warned_count=payload.warned_count,
                        intent_summary=payload.intent_summary,
                    )
                )
            elif kind == "alert":
                session.add(payload)

    # ---- Reads ------------------------------------------------------------

    async def flush(self) -> None:
        """Wait until every queued record has been written. Used by tests and exports."""
        await self._queue.join()

    async def get_run(self, session_id: str) -> Run | None:
        async with self._db.session() as session:
            result = await session.execute(select(Run).where(Run.session_id == session_id))
            return result.scalar_one_or_none()

    async def list_runs(self, limit: int = 50, offset: int = 0) -> tuple[list[Run], int]:
        async with self._db.session() as session:
            total = await session.scalar(select(func.count()).select_from(Run))
            result = await session.execute(
                select(Run).order_by(Run.started_at.desc()).limit(limit).offset(offset)
            )
            return list(result.scalars().all()), int(total or 0)

    async def get_events(self, session_id: str) -> list[Event]:
        async with self._db.session() as session:
            result = await session.execute(
                select(Event)
                .where(Event.session_id == session_id)
                .order_by(Event.step_index, Event.timestamp)
            )
            return list(result.scalars().all())

    async def list_alerts(self, limit: int = 50, unacknowledged_only: bool = False) -> list[Alert]:
        async with self._db.session() as session:
            statement = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
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


def _to_event_row(event: AuditEvent) -> Event:
    return Event(
        event_id=event.event_id,
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
        payload_json=event.payload,
        timestamp=event.timestamp,
    )


def _to_run_row(summary: RunSummary) -> Run:
    return Run(
        session_id=summary.session_id,
        started_at=summary.started_at,
        total_steps=summary.total_steps,
        final_status=summary.final_status,
        intent_summary=summary.intent_summary,
        intent_goal=summary.intent_summary,
        max_drift_score=summary.max_drift_score,
    )
