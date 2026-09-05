# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""arq worker entrypoint. Only meaningful when REDIS_URL is configured.

Run via: arq ariadne.worker.WorkerSettings

This module must stay importable even when Redis/arq are not installed or
REDIS_URL is unset -- only actually *running* the worker (`arq
ariadne.worker.WorkerSettings`) requires a real Redis. Kept thin: all the
actual backtest logic lives in ariadne/eval/backtester.py, this just wires a
job function up to arq's pool/queue machinery.
"""

from __future__ import annotations

from typing import Any

try:
    from arq.connections import RedisSettings
except ImportError:  # pragma: no cover - exercised only without the `jobs` extra installed
    RedisSettings = None

from ariadne.audit.recorder import AuditRecorder
from ariadne.config import get_settings
from ariadne.db.session import Database
from ariadne.eval.backtester import (
    BacktestReport,
    BacktestRunFilter,
    PolicyBacktester,
    ProposedPolicy,
)
from ariadne.logging import get_logger

logger = get_logger(__name__)


async def run_backtest_job(
    ctx: dict[str, Any],
    job_id: str,
    organization_id: str,
    proposed_policy_json: str,
    run_filter_json: str,
) -> dict[str, Any]:
    """The arq job function. Re-derives everything it needs from serialized
    parameters (arq jobs cross a Redis wire, so a Python closure/coroutine
    can't ride along) and returns a plain dict (arq stores job results
    pickled; a Pydantic model round-trips fine but a dict keeps this
    independent of the exact serializer arq picks).
    """
    settings = get_settings()
    database = Database(settings)
    recorder = AuditRecorder(database, settings)
    backtester = PolicyBacktester(recorder, settings)

    proposed_policy = ProposedPolicy.model_validate_json(proposed_policy_json)
    run_filter = BacktestRunFilter.model_validate_json(run_filter_json)

    report: BacktestReport = await backtester.run_backtest(
        job_id, organization_id, proposed_policy, run_filter
    )
    await database.close()
    return report.model_dump(mode="json")


async def _startup(ctx: dict[str, Any]) -> None:
    logger.info("ariadne.worker_starting")


async def _shutdown(ctx: dict[str, Any]) -> None:
    logger.info("ariadne.worker_stopping")


def _build_redis_settings() -> Any | None:
    """None when arq isn't installed or REDIS_URL isn't set -- this module
    must stay importable in both of those cases; only actually running the
    worker (`arq ariadne.worker.WorkerSettings`) requires both.
    """
    settings = get_settings()
    if RedisSettings is None or not settings.redis_url:
        return None
    return RedisSettings.from_dsn(settings.redis_url)


class WorkerSettings:
    """arq picks this class up by convention when run as
    `arq ariadne.worker.WorkerSettings`.
    """

    functions = (run_backtest_job,)
    redis_settings = _build_redis_settings()
    on_startup = _startup
    on_shutdown = _shutdown
