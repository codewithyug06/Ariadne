# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Compliance report generation: JSON for machines, Markdown for auditors."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ariadne import __version__
from ariadne.audit.recorder import AuditRecorder
from ariadne.audit.schemas import (
    AuditEvent,
    ComplianceArticleMapping,
    ComplianceReport,
    DriftCurvePoint,
    RootCauseFinding,
    RunSummary,
)
from ariadne.config import Settings, get_settings
from ariadne.db.models import LEGACY_ORG_ID, Event, Run
from ariadne.graph.builder import ProvenanceGraphBuilder
from ariadne.graph.traversal import find_root_cause
from ariadne.logging import get_logger

logger = get_logger(__name__)


class ComplianceExporter:
    """Turns a run's audit trail and provenance graph into a filed artefact."""

    def __init__(
        self,
        recorder: AuditRecorder,
        graph_builder: ProvenanceGraphBuilder,
        settings: Settings | None = None,
    ) -> None:
        self._recorder = recorder
        self._graph = graph_builder
        self._settings = settings or get_settings()

    async def export_run(
        self, session_id: str, organization_id: str = LEGACY_ORG_ID
    ) -> ComplianceReport:
        """Build the full report for one session."""
        await self._recorder.flush()

        run = await self._recorder.get_run(session_id, organization_id)
        if run is None:
            raise KeyError(f"no run recorded for session {session_id!r}")
        events = await self._recorder.get_events(session_id, organization_id)
        session_graph = await self._graph.session_graph(session_id, organization_id)

        audit_events = [_to_audit_event(event) for event in events]
        drift_curve = [
            DriftCurvePoint(
                step_index=event.step_index,
                tool_name=event.tool_name,
                drift_score=event.drift_score,
                slope=event.slope,
                enforcement_action=event.enforcement_action,
            )
            for event in events
        ]

        findings = await self._root_cause_findings(events, organization_id)
        intent_node = next(
            (node for node in session_graph.nodes if node.node_type.value == "user_request"), None
        )

        report = ComplianceReport(
            session_id=session_id,
            ariadne_version=__version__,
            run=_to_run_summary(run),
            intent=intent_node.payload if intent_node else {"raw_text": run.intent_summary},
            drift_curve=drift_curve,
            events=audit_events,
            root_cause_findings=findings,
            eu_ai_act_mapping=self._map_eu_ai_act(run, audit_events, findings),
            agent_framework=run.agent_framework,
        )
        logger.info(
            "audit.report_exported",
            session_id=session_id,
            event_count=len(audit_events),
            finding_count=len(findings),
        )
        return report

    async def _root_cause_findings(
        self, events: list[Event], organization_id: str = LEGACY_ORG_ID
    ) -> list[RootCauseFinding]:
        """One backward walk per BLOCK, plus the forward blast radius."""
        findings: list[RootCauseFinding] = []
        for event in events:
            if event.enforcement_action != "BLOCK" or not event.node_id:
                continue
            chain = await self._graph.blame_chain(event.node_id, organization_id=organization_id)
            root_cause = find_root_cause(chain, self._settings.drift_score_warn)
            blast = await self._graph.blast_radius(event.node_id, organization_id=organization_id)
            findings.append(
                RootCauseFinding(
                    blocked_step_index=event.step_index,
                    blocked_tool_name=event.tool_name,
                    blame_chain_node_ids=[node.id for node in chain],
                    blame_chain_labels=[node.label for node in chain],
                    root_cause_node_id=root_cause.id if root_cause else None,
                    root_cause_step_index=root_cause.step_index if root_cause else None,
                    root_cause_label=root_cause.label if root_cause else None,
                    blast_radius_node_ids=[node.id for node in blast],
                )
            )
        return findings

    def _map_eu_ai_act(
        self, run: Run, events: list[AuditEvent], findings: list[RootCauseFinding]
    ) -> list[ComplianceArticleMapping]:
        """Map this run's evidence onto the obligations Ariadne actually supports.

        Scope note: Ariadne produces *evidence* for these articles. It does not
        by itself make a deployment compliant, and the report says so.
        """
        blocked = [event for event in events if event.enforcement_action == "BLOCK"]
        escalated = [event for event in events if event.enforcement_action == "ESCALATE"]
        scored = [event for event in events if event.drift_score is not None]

        return [
            ComplianceArticleMapping(
                article="Article 9",
                title="Risk management system",
                obligation=(
                    "Identify and evaluate foreseeable risks throughout the system lifecycle, "
                    "and adopt targeted risk-management measures."
                ),
                evidence=[
                    f"{len(scored)} of {len(events)} tool calls scored against the "
                    "session intent anchor.",
                    f"Hard policy layer evaluated every call; {len(blocked)} call(s) blocked.",
                    f"Peak drift score for this run: {run.max_drift_score:.1f}/100.",
                    f"Configured thresholds — warn {self._settings.drift_score_warn:.0f}, "
                    f"escalate {self._settings.drift_score_escalate:.0f}, "
                    f"block {self._settings.drift_score_block:.0f}.",
                ],
                satisfied=len(scored) == len(events) and len(events) > 0,
            ),
            ComplianceArticleMapping(
                article="Article 13",
                title="Transparency and provision of information to deployers",
                obligation=(
                    "Operation must be sufficiently transparent for deployers to interpret "
                    "output and use the system appropriately."
                ),
                evidence=[
                    f"Every decision carries a machine- and human-readable reason "
                    f"({len(events)} recorded).",
                    "Full execution provenance graph retained: tool calls, results, and the "
                    "caused_by / informed_by / contradicts / escalates_privilege edges "
                    "between them.",
                    f"{len(findings)} root-cause analys(e)s attached to blocked actions.",
                ],
                satisfied=all(event.reason for event in events) if events else False,
            ),
            ComplianceArticleMapping(
                article="Article 14",
                title="Human oversight",
                obligation=(
                    "High-risk systems must be designed so natural persons can oversee them, "
                    "including the ability to intervene or interrupt operation."
                ),
                evidence=[
                    f"{len(escalated)} action(s) escalated for human approval before execution.",
                    f"{len(blocked)} action(s) interrupted before reaching the tool.",
                    "Human-in-the-loop webhook "
                    + ("configured." if self._settings.hitl_webhook_url else "not configured."),
                    f"Escalations auto-block after {self._settings.hitl_timeout_seconds:.0f}s "
                    "without approval.",
                ],
                satisfied=bool(self._settings.hitl_webhook_url) or not escalated,
            ),
        ]

    async def export_json(self, session_id: str) -> str:
        report = await self.export_run(session_id)
        return report.model_dump_json(indent=2)

    async def export_markdown(self, session_id: str) -> str:
        return render_markdown(await self.export_run(session_id))


def render_markdown(report: ComplianceReport) -> str:
    """Render a report as the plain-text document an auditor reads."""
    run = report.run
    lines: list[str] = [
        f"# Ariadne Compliance Report — `{report.session_id}`",
        "",
        f"*Generated {_fmt(report.generated_at)} by Ariadne v{report.ariadne_version}*",
        "",
        "## 1. Run summary",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Session | `{run.session_id}` |",
        f"| Agent framework | {report.agent_framework} |",
        f"| Started | {_fmt(run.started_at)} |",
        f"| Ended | {_fmt(run.ended_at) if run.ended_at else '(still running)'} |",
        f"| Total steps | {run.total_steps} |",
        f"| Final status | **{run.final_status}** |",
        f"| Peak drift score | {run.max_drift_score:.1f} / 100 |",
        f"| Blocked / escalated / warned | {run.blocked_count} / "
        f"{run.escalated_count} / {run.warned_count} |",
        "",
        "## 2. Intent anchor",
        "",
        f"**Goal:** {report.intent.get('goal', '(not extracted)')}",
        "",
        f"**Original request:** {report.intent.get('raw_text', '(not recorded)')}",
        "",
    ]

    constraints = report.intent.get("constraints") or []
    disallowed = report.intent.get("disallowed_actions") or []
    lines.append("**Constraints:**")
    lines.extend([f"- {item}" for item in constraints] or ["- (none extracted)"])
    lines.append("")
    lines.append("**Disallowed actions:**")
    lines.extend([f"- {item}" for item in disallowed] or ["- (none extracted)"])
    lines.extend(
        [
            "",
            "## 3. Drift trajectory",
            "",
            "| Step | Tool | Drift | Slope | Decision |",
            "| --- | --- | --- | --- | --- |",
        ]
    )

    for point in report.drift_curve:
        score = f"{point.drift_score:.1f}" if point.drift_score is not None else "—"
        slope = f"{point.slope:+.3f}" if point.slope is not None else "—"
        lines.append(
            f"| {point.step_index} | `{point.tool_name}` | {score} | {slope} | "
            f"{point.enforcement_action} |"
        )

    lines.extend(["", "## 4. Enforcement decisions", ""])
    for event in report.events:
        marker = {"ALLOW": "OK", "WARN": "WARN", "ESCALATE": "ESC", "BLOCK": "BLOCK"}.get(
            event.enforcement_action, event.enforcement_action
        )
        rule = f" _(rule: `{event.triggered_rule}`)_" if event.triggered_rule else ""
        lines.append(
            f"- **[{marker}] step {event.step_index} `{event.tool_name}`**{rule} — {event.reason}"
        )

    lines.extend(["", "## 5. Root-cause analysis", ""])
    if not report.root_cause_findings:
        lines.append(
            "No actions were blocked during this run; no root-cause analysis was required."
        )
    for finding in report.root_cause_findings:
        lines.extend(
            [
                f"### Block at step {finding.blocked_step_index} — `{finding.blocked_tool_name}`",
                "",
                f"- **Root cause:** {finding.root_cause_label or 'unresolved'}"
                + (
                    f" (step {finding.root_cause_step_index})"
                    if finding.root_cause_step_index is not None
                    else ""
                ),
                f"- **Blame chain ({len(finding.blame_chain_labels)} nodes, newest first):** "
                + " → ".join(f"`{label}`" for label in finding.blame_chain_labels),
                f"- **Blast radius:** {len(finding.blast_radius_node_ids)} downstream node(s) "
                "would have been affected had this action executed.",
                "",
            ]
        )

    lines.extend(["", "## 6. EU AI Act evidence mapping", ""])
    for mapping in report.eu_ai_act_mapping:
        status = "satisfied" if mapping.satisfied else "partial — see evidence"
        lines.extend(
            [
                f"### {mapping.article} — {mapping.title} ({status})",
                "",
                f"> {mapping.obligation}",
                "",
            ]
        )
        lines.extend([f"- {item}" for item in mapping.evidence])
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "*Ariadne produces evidence supporting these obligations; it does not by itself "
            "render a deployment compliant. This report is intended as an input to a conformity "
            "assessment, not a substitute for one.*",
        ]
    )
    return "\n".join(lines)


def _fmt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S UTC") if value else "—"


def _to_audit_event(event: Event) -> AuditEvent:
    payload: dict[str, Any] = event.payload_json if isinstance(event.payload_json, dict) else {}
    return AuditEvent(
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
        payload=payload,
        timestamp=event.timestamp,
    )


def _to_run_summary(run: Run) -> RunSummary:
    return RunSummary(
        session_id=run.session_id,
        started_at=run.started_at,
        ended_at=run.ended_at,
        total_steps=run.total_steps,
        final_status=run.final_status,
        intent_summary=run.intent_summary,
        max_drift_score=run.max_drift_score,
        blocked_count=run.blocked_count,
        escalated_count=run.escalated_count,
        warned_count=run.warned_count,
    )
