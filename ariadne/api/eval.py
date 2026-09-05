# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Feature 5A: policy backtesting API -- dispatch, poll, and read reports."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ariadne.audit.recorder import AuditRecorder
from ariadne.auth.org_scope import require_org_scope
from ariadne.eval.backtester import (
    BacktestReport,
    BacktestRunFilter,
    PolicyBacktester,
    ProposedPolicy,
)
from ariadne.eval.job_runner import enqueue_backtest, get_job_status
from ariadne.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/eval", tags=["eval"])

#: job_id -> finished BacktestReport, so GET .../report can hand back the
#: typed model rather than whatever generic "result" get_job_status returns.
#: Populated by the same wrapper coroutine passed to enqueue_backtest, so it
#: is filled the instant the job (in-process or arq) actually completes.
_REPORTS: dict[str, BacktestReport] = {}


class BacktestRequest(BaseModel):
    proposed_policy: ProposedPolicy
    run_filter: BacktestRunFilter = BacktestRunFilter()


class BacktestJobResponse(BaseModel):
    job_id: str


@router.post("/backtest", response_model=BacktestJobResponse, summary="Dispatch a policy backtest")
async def post_backtest(
    body: BacktestRequest,
    request: Request,
    organization_id: str = Depends(require_org_scope),
) -> BacktestJobResponse:
    recorder: AuditRecorder = request.app.state.recorder
    settings = request.app.state.settings
    backtester = PolicyBacktester(recorder, settings)

    async def _run() -> dict[str, Any]:
        # `job_id` is a closure over the enclosing scope's name, resolved
        # only when this coroutine actually runs -- by then enqueue_backtest
        # below has already returned and assigned it. In-process dispatch
        # schedules this via asyncio.create_task, which never executes
        # synchronously inside enqueue_backtest itself, so the name is always
        # bound by the time the task body runs.
        report = await backtester.run_backtest(
            job_id, organization_id, body.proposed_policy, body.run_filter
        )
        _REPORTS[job_id] = report
        return report.model_dump(mode="json")

    job_id = await enqueue_backtest(
        _run,
        settings,
        arq_args=(
            organization_id,
            body.proposed_policy.model_dump_json(),
            body.run_filter.model_dump_json(),
        ),
    )
    return BacktestJobResponse(job_id=job_id)


@router.get("/backtest/{job_id}", summary="Poll a backtest job's status")
async def get_backtest_status(job_id: str, request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return await get_job_status(job_id, settings)


@router.get(
    "/backtest/{job_id}/report",
    response_model=None,
    summary="Read a completed backtest report (JSON or Markdown)",
)
async def get_backtest_report(
    job_id: str,
    request: Request,
    format: str = Query(default="json"),
) -> BacktestReport | PlainTextResponse:
    settings = request.app.state.settings
    status = await get_job_status(job_id, settings)

    report = _REPORTS.get(job_id)
    if report is None and status.get("status") == "complete" and status.get("result"):
        # arq-dispatched job: the report never passed through this process's
        # _REPORTS dict, so reconstruct it from the job result payload.
        report = BacktestReport.model_validate(status["result"])

    if report is None:
        if status.get("status") in ("pending", "running"):
            raise HTTPException(status_code=409, detail=f"backtest {job_id!r} is still {status['status']}")
        raise HTTPException(status_code=404, detail=f"no completed backtest report for {job_id!r}")

    if format == "markdown":
        return PlainTextResponse(_render_markdown(report), media_type="text/markdown; charset=utf-8")
    return report


def _render_markdown(report: BacktestReport) -> str:
    lines = [
        f"# Policy Backtest Report ({report.job_id})",
        "",
        f"Runs analyzed: **{report.runs_analyzed}**",
        "",
        "| Metric | Baseline | Proposed | Delta |",
        "|---|---|---|---|",
        (
            f"| Detection rate | {report.baseline_detection_rate:.1%} | "
            f"{report.proposed_detection_rate:.1%} | {report.detection_rate_delta:+.1%} |"
        ),
        (
            f"| False positive rate | {report.baseline_fpr:.1%} | "
            f"{report.proposed_fpr:.1%} | {report.fpr_delta:+.1%} |"
        ),
        f"| Blocks | {report.baseline_blocks} | {report.proposed_blocks} | |",
        f"| Escalations | {report.baseline_escalations} | {report.proposed_escalations} | |",
        "",
        f"**Recommendation: {report.recommendation}**",
        "",
        report.recommendation_reason,
        "",
        f"Changed runs: {len(report.changed_runs)}",
    ]
    return "\n".join(lines)


@router.post(
    "/simulate-run/{session_id}",
    summary="Synchronous single-run policy simulation (no job queue -- one run is fast)",
)
async def post_simulate_run(
    session_id: str,
    body: ProposedPolicy,
    request: Request,
    organization_id: str = Depends(require_org_scope),
) -> dict[str, Any]:
    recorder: AuditRecorder = request.app.state.recorder
    settings = request.app.state.settings
    backtester = PolicyBacktester(recorder, settings)
    return await backtester.simulate_run(session_id, organization_id, body)
