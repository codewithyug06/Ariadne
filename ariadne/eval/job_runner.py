# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Backtest job dispatch: arq+Redis when configured, in-process asyncio otherwise.

Matches the OPA/ArcadeDB/Ollama graceful-degradation pattern already used
throughout this codebase (see ariadne.config.Settings.graph_backend) --
REDIS_URL unset or unreachable means every backtest runs synchronously
in-process rather than failing outright.

Job tracking here is a module-level singleton dict, the same tolerance for
single-process simplicity AuditRecorder's in-memory queue accepts: this is
fine for a single Ariadne instance and does not survive a restart. A
multi-instance deployment that wants durable job status needs REDIS_URL
configured (arq persists job state in Redis itself), which is exactly the
degrade-to-worse-but-still-correct path this module is built around.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from ariadne.config import Settings
from ariadne.logging import get_logger

logger = get_logger(__name__)


class _InProcessJob:
    """Tracks one job dispatched via asyncio.create_task rather than arq."""

    __slots__ = ("task", "result", "error")

    def __init__(self, task: asyncio.Task[Any]) -> None:
        self.task = task
        self.result: Any | None = None
        self.error: str | None = None


#: job_id -> tracking record, for jobs dispatched in-process. Jobs dispatched
#: to arq are NOT stored here -- their status lives in Redis and is queried
#: through arq's own API instead (see get_job_status below).
_IN_PROCESS_JOBS: dict[str, _InProcessJob] = {}

#: job_id -> True for jobs we handed off to arq, so get_job_status knows which
#: backend to consult without re-probing Redis on every poll.
_ARQ_JOBS: dict[str, bool] = {}


async def _redis_reachable(settings: Settings) -> bool:
    """Quick ping. Any failure (unset URL, connection refused, timeout) means
    "not reachable" -- never raises.
    """
    if not settings.redis_url:
        return False
    try:
        import redis.asyncio as redis_asyncio  # noqa: PLC0415
    except ImportError:
        logger.info("eval.redis_client_not_installed", fallback="in_process")
        return False

    client = None
    try:
        client = redis_asyncio.from_url(settings.redis_url, socket_connect_timeout=1.0)
        await client.ping()
        return True
    except Exception as exc:  # noqa: BLE001 - any failure means fall back, never raise
        logger.info(
            "eval.redis_unreachable",
            error=str(exc),
            error_type=type(exc).__name__,
            fallback="in_process",
        )
        return False
    finally:
        if client is not None:
            with_close = getattr(client, "aclose", None) or getattr(client, "close", None)
            if with_close is not None:
                try:
                    await with_close()
                except Exception:  # noqa: BLE001 - best-effort cleanup
                    pass


async def enqueue_backtest(
    coro_factory: Callable[[], Awaitable[Any]],
    settings: Settings,
    *,
    arq_args: tuple[Any, ...] = (),
) -> str:
    """Dispatch a backtest job. Returns a job_id usable with get_job_status.

    Tries arq+Redis only when REDIS_URL is set AND a real connection can be
    established; otherwise runs `coro_factory()` immediately as an in-process
    asyncio task.

    `arq_args` are the plain, JSON-serializable positional arguments
    (organization_id, proposed_policy JSON, run_filter JSON) forwarded to
    `ariadne.worker.run_backtest_job` when dispatch goes through arq -- a
    Python closure like `coro_factory` can't cross the Redis wire, so the arq
    path re-derives everything from these instead of calling coro_factory at
    all. The in-process fallback ignores `arq_args` entirely and just calls
    `coro_factory()` directly.
    """
    job_id = uuid.uuid4().hex

    if await _redis_reachable(settings):
        try:
            from arq import create_pool  # noqa: PLC0415
            from arq.connections import RedisSettings  # noqa: PLC0415

            assert settings.redis_url is not None  # noqa: S101 - guarded by _redis_reachable above
            pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            try:
                job = await pool.enqueue_job(
                    "run_backtest_job", job_id, *arq_args, _job_id=job_id
                )
                if job is not None:
                    _ARQ_JOBS[job_id] = True
                    logger.info("eval.backtest_dispatched", job_id=job_id, backend="arq")
                    return job_id
            finally:
                await pool.aclose()
        except Exception as exc:  # noqa: BLE001 - any arq failure falls back in-process
            logger.error(
                "eval.arq_dispatch_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                fallback="in_process",
            )

    task = asyncio.create_task(_run_in_process(job_id, coro_factory), name=f"backtest-{job_id}")
    _IN_PROCESS_JOBS[job_id] = _InProcessJob(task)
    logger.info("eval.backtest_dispatched", job_id=job_id, backend="in_process")
    return job_id


async def _run_in_process(job_id: str, coro_factory: Callable[[], Awaitable[Any]]) -> None:
    record = _IN_PROCESS_JOBS.get(job_id)
    try:
        result = await coro_factory()
        if record is not None:
            record.result = result
    except Exception as exc:  # noqa: BLE001 - captured for get_job_status, never propagated
        logger.error(
            "eval.backtest_job_failed", job_id=job_id, error=str(exc), error_type=type(exc).__name__
        )
        if record is not None:
            record.error = f"{type(exc).__name__}: {exc}"


async def get_job_status(job_id: str, settings: Settings) -> dict[str, Any]:
    """Return {"status", "result", "error"} for a job dispatched by enqueue_backtest."""
    if job_id in _ARQ_JOBS:
        return await _arq_job_status(job_id, settings)

    record = _IN_PROCESS_JOBS.get(job_id)
    if record is None:
        return {"status": "pending", "result": None, "error": "unknown job_id"}
    if not record.task.done():
        return {"status": "running", "result": None, "error": None}
    if record.error is not None:
        return {"status": "failed", "result": None, "error": record.error}
    return {"status": "complete", "result": record.result, "error": None}


async def _arq_job_status(job_id: str, settings: Settings) -> dict[str, Any]:
    try:
        from arq.connections import RedisSettings  # noqa: PLC0415
        from arq.jobs import Job, JobStatus  # noqa: PLC0415
        from arq import create_pool  # noqa: PLC0415

        assert settings.redis_url is not None  # noqa: S101 - only ever set for jobs in _ARQ_JOBS
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            job = Job(job_id, pool)
            status = await job.status()
            if status == JobStatus.complete:
                job_result = await job.result_info()
                result = job_result.result if job_result is not None else None
                return {"status": "complete", "result": result, "error": None}
            if status in (JobStatus.not_found, JobStatus.deferred, JobStatus.queued):
                return {"status": "pending", "result": None, "error": None}
            if status == JobStatus.in_progress:
                return {"status": "running", "result": None, "error": None}
            return {"status": "failed", "result": None, "error": f"arq status={status}"}
        finally:
            await pool.aclose()
    except Exception as exc:  # noqa: BLE001 - Redis can vanish mid-poll
        logger.error("eval.arq_status_failed", job_id=job_id, error=str(exc))
        return {"status": "failed", "result": None, "error": str(exc)}


def reset_for_tests() -> None:
    """Clear module-level job tracking between test runs."""
    _IN_PROCESS_JOBS.clear()
    _ARQ_JOBS.clear()
