# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Read API over runs, their graphs, and their compliance reports."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ariadne.audit.exporter import ComplianceExporter, render_markdown
from ariadne.audit.schemas import AuditEvent, ComplianceReport, RunSummary
from ariadne.auth.org_scope import require_org_scope
from ariadne.graph.schemas import SessionGraph

router = APIRouter(prefix="/runs", tags=["runs"])


class RunListItem(BaseModel):
    session_id: str
    started_at: str
    ended_at: str | None
    total_steps: int
    final_status: str
    max_drift_score: float
    intent_summary: str
    blocked_count: int
    escalated_count: int
    warned_count: int


class RunListResponse(BaseModel):
    items: list[RunListItem]
    total: int
    limit: int
    offset: int


class RunDetailResponse(BaseModel):
    run: RunSummary
    events: list[AuditEvent]
    active: bool


class BlastRadiusResponse(BaseModel):
    node_id: str
    affected_node_ids: list[str]
    affected_labels: list[str]


@router.get("", response_model=RunListResponse, summary="List agent runs")
async def list_runs(
    request: Request,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    organization_id: str = Depends(require_org_scope),
) -> RunListResponse:
    recorder = request.app.state.recorder
    await recorder.flush()
    runs, total = await recorder.list_runs(
        limit=limit, offset=offset, organization_id=organization_id
    )
    return RunListResponse(
        items=[
            RunListItem(
                session_id=run.session_id,
                started_at=run.started_at.isoformat(),
                ended_at=run.ended_at.isoformat() if run.ended_at else None,
                total_steps=run.total_steps,
                final_status=run.final_status,
                max_drift_score=run.max_drift_score,
                intent_summary=run.intent_summary,
                blocked_count=run.blocked_count,
                escalated_count=run.escalated_count,
                warned_count=run.warned_count,
            )
            for run in runs
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{session_id}", response_model=RunDetailResponse, summary="Run detail with events")
async def get_run(
    session_id: str, request: Request, organization_id: str = Depends(require_org_scope)
) -> RunDetailResponse:
    recorder = request.app.state.recorder
    await recorder.flush()
    run = await recorder.get_run(session_id, organization_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no run recorded for session {session_id!r}")
    events = await recorder.get_events(session_id, organization_id)
    from ariadne.audit.exporter import _to_audit_event, _to_run_summary  # noqa: PLC0415

    return RunDetailResponse(
        run=_to_run_summary(run),
        events=[_to_audit_event(event) for event in events],
        active=session_id in request.app.state.proxy.sessions,
    )


@router.get("/{session_id}/graph", response_model=SessionGraph, summary="Provenance graph")
async def get_run_graph(
    session_id: str, request: Request, organization_id: str = Depends(require_org_scope)
) -> SessionGraph:
    graph: SessionGraph = await request.app.state.graph_builder.session_graph(
        session_id, organization_id
    )
    if not graph.nodes:
        raise HTTPException(status_code=404, detail=f"no graph recorded for session {session_id!r}")
    return graph


@router.get(
    "/{session_id}/root-cause",
    response_model=list[dict[str, Any]],
    summary="Backward blame chain from a node",
)
async def get_root_cause(
    session_id: str,
    request: Request,
    node_id: str = Query(description="Node to walk back from — usually a BLOCK node"),
    max_depth: int = Query(default=10, ge=1, le=100),
    organization_id: str = Depends(require_org_scope),
) -> list[dict[str, Any]]:
    chain = await request.app.state.graph_builder.blame_chain(
        node_id, max_depth, organization_id=organization_id
    )
    if not chain:
        raise HTTPException(status_code=404, detail=f"unknown node {node_id!r}")
    return [node.model_dump(mode="json", by_alias=True) for node in chain]


@router.get(
    "/{session_id}/blast-radius",
    response_model=BlastRadiusResponse,
    summary="Forward reachability from a node",
)
async def get_blast_radius(
    session_id: str,
    request: Request,
    node_id: str = Query(description="Node to walk forward from"),
    max_depth: int = Query(default=10, ge=1, le=100),
    organization_id: str = Depends(require_org_scope),
) -> BlastRadiusResponse:
    nodes = await request.app.state.graph_builder.blast_radius(
        node_id, max_depth, organization_id=organization_id
    )
    return BlastRadiusResponse(
        node_id=node_id,
        affected_node_ids=[node.id for node in nodes],
        affected_labels=[node.label for node in nodes],
    )


@router.get(
    "/{session_id}/report",
    summary="Compliance report (JSON or Markdown)",
    response_model=None,
)
async def get_report(
    session_id: str,
    request: Request,
    format: Literal["json", "markdown"] = Query(default="json"),
    organization_id: str = Depends(require_org_scope),
) -> ComplianceReport | PlainTextResponse:
    exporter: ComplianceExporter = request.app.state.exporter
    try:
        report = await exporter.export_run(session_id, organization_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if format == "markdown":
        return PlainTextResponse(
            render_markdown(report),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="ariadne-report-{session_id}.md"'
            },
        )
    return report
