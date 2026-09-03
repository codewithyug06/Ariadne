# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Audit trail and compliance report types."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ariadne.proxy.schemas import utcnow


class AuditEvent(BaseModel):
    """One durable record of an interception. Written for every tool call."""

    event_id: str
    session_id: str
    step_index: int
    tool_name: str
    enforcement_action: str
    reason: str = ""
    triggered_rule: str | None = None
    drift_score: float | None = None
    slope: float | None = None
    raw_distance: float | None = None
    node_id: str | None = None
    latency_ms: float = 0.0
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utcnow)


class RunSummary(BaseModel):
    """Closing record for a session."""

    session_id: str
    started_at: datetime
    ended_at: datetime | None = None
    total_steps: int = 0
    final_status: str = "CLEAN"
    intent_summary: str = ""
    max_drift_score: float = 0.0
    blocked_count: int = 0
    escalated_count: int = 0
    warned_count: int = 0


class DriftCurvePoint(BaseModel):
    step_index: int
    tool_name: str
    drift_score: float | None
    slope: float | None
    enforcement_action: str


class RootCauseFinding(BaseModel):
    """Backward-walk result for a single BLOCK event."""

    blocked_step_index: int
    blocked_tool_name: str
    blame_chain_node_ids: list[str]
    blame_chain_labels: list[str]
    root_cause_node_id: str | None
    root_cause_step_index: int | None
    root_cause_label: str | None
    blast_radius_node_ids: list[str] = Field(default_factory=list)


class ComplianceArticleMapping(BaseModel):
    """How this run's evidence maps onto an EU AI Act obligation."""

    article: str
    title: str
    obligation: str
    evidence: list[str]
    satisfied: bool


class ComplianceReport(BaseModel):
    """The exportable artefact an auditor actually reads."""

    session_id: str
    generated_at: datetime = Field(default_factory=utcnow)
    ariadne_version: str
    run: RunSummary
    intent: dict[str, Any]
    drift_curve: list[DriftCurvePoint]
    events: list[AuditEvent]
    root_cause_findings: list[RootCauseFinding]
    eu_ai_act_mapping: list[ComplianceArticleMapping]
    agent_framework: str = "unknown"
