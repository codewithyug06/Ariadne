# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Data flywheel: persists a completed session's full trajectory.

Feature 7. Pure persistence -- no ML training happens here. Every completed
session gets one TrajectoryRecord row: the drift/slope/R^2 curves, the last
known Feature-2 risk-dimension breakdown, and an auto-labeling heuristic
verdict, all kept as raw material for a future supervised-training pipeline.

Writes must never block or fail the session-end response: record_session
catches and logs any exception rather than propagating it.
"""

from __future__ import annotations

from uuid import uuid4

from ariadne.audit.schemas import AuditEvent, RunSummary
from ariadne.db.models import LEGACY_ORG_ID, TrajectoryRecord
from ariadne.db.session import Database
from ariadne.graph.builder import ProvenanceGraphBuilder
from ariadne.logging import get_logger

logger = get_logger(__name__)


class TrajectoryRecorder:
    """Persists a completed session's full trajectory for future supervised
    training data collection (the "data flywheel"). Async write, must never
    block or fail the session-end response -- catch and log any exception.
    """

    def __init__(
        self, database: Database, graph_builder: ProvenanceGraphBuilder | None = None
    ) -> None:
        self._db = database
        self._graph = graph_builder

    async def record_session(
        self,
        session_id: str,
        events: list[AuditEvent],
        run_summary: RunSummary,
        organization_id: str = LEGACY_ORG_ID,
        agent_identity: str | None = None,
    ) -> None:
        try:
            record = await self._build_record(
                session_id, events, run_summary, organization_id, agent_identity
            )
            async with self._db.session() as session:
                session.add(record)
        except Exception as exc:  # noqa: BLE001 - must never fail session end
            logger.error(
                "trajectory_recorder.write_failed",
                session_id=session_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    async def _build_record(
        self,
        session_id: str,
        events: list[AuditEvent],
        run_summary: RunSummary,
        organization_id: str,
        agent_identity: str | None,
    ) -> TrajectoryRecord:
        ordered = sorted(events, key=lambda e: e.step_index)

        drift_curve = [event.drift_score or 0.0 for event in ordered]
        slope_curve = [event.slope or 0.0 for event in ordered]
        # No R-squared field is threaded through AuditEvent/DriftScore today
        # (ariadne/drift/scorer.py computes it internally as a fit-quality
        # gate but never surfaces it) -- default every step to 0.0 rather
        # than reconstructing the fit here. Documented deviation from the
        # spec's literal r_squared-per-event reading.
        r2_curve = [0.0 for _ in ordered]

        first_divergence_step: int | None = None
        root_cause_trigger: str | None = None
        for event in ordered:
            if event.narrative is None:
                continue
            if first_divergence_step is None:
                first_divergence_step = event.narrative.get("first_divergence_step")
            trigger = event.narrative.get("trigger")
            if trigger is not None:
                root_cause_trigger = trigger

        intent_score = tool_score = privilege_score = identity_score = data_score = 0.0
        for event in reversed(ordered):
            risk_dimensions = event.payload.get("risk_dimensions")
            if isinstance(risk_dimensions, dict):
                intent_score = float(risk_dimensions.get("intent", {}).get("value", 0.0))
                tool_score = float(risk_dimensions.get("tool", {}).get("value", 0.0))
                privilege_score = float(risk_dimensions.get("privilege", {}).get("value", 0.0))
                identity_score = float(risk_dimensions.get("identity", {}).get("value", 0.0))
                data_score = float(risk_dimensions.get("data", {}).get("value", 0.0))
                break

        # blast_radius_count: the forward blast radius of the last BLOCK's
        # graph node, reusing ProvenanceGraphBuilder.blast_radius (the same
        # traversal ariadne/audit/exporter.py and the /blast-radius endpoint
        # use) rather than reimplementing graph traversal here. If no graph
        # builder was injected (unit tests construct this recorder without
        # one) or no BLOCK event has a node_id, this stays 0.
        blast_radius_count = 0
        last_block = next((e for e in reversed(ordered) if e.enforcement_action == "BLOCK"), None)
        if self._graph is not None and last_block is not None and last_block.node_id is not None:
            nodes = await self._graph.blast_radius(
                last_block.node_id, organization_id=organization_id
            )
            blast_radius_count = len(nodes)

        # RunSummary.final_status uses a distinct vocabulary ("BLOCKED",
        # "ESCALATED", "WARNED", "CLEAN") from the per-event
        # enforcement_action ("BLOCK"/"WARN"/"ESCALATE"/"ALLOW", see
        # ariadne/enforcement/schemas.py). The spec's auto-labeling
        # heuristic is phrased in terms of the latter, so
        # final_enforcement_action here is the last recorded event's
        # enforcement_action (what actually happened on the final step),
        # defaulting to "ALLOW" for a session with no intercepted events.
        final_enforcement_action = ordered[-1].enforcement_action if ordered else "ALLOW"
        confirmed_attack: bool | None = None
        label_source: str | None = None
        if final_enforcement_action == "BLOCK":
            # Auto-labeling heuristic: a BLOCK triggered by a hard policy
            # rule (Event.triggered_rule / AuditEvent.triggered_rule is
            # non-null) is a confident positive label -- the operator wrote
            # a rule specifically to catch this pattern, so it is treated as
            # a confirmed attack for training purposes. A BLOCK reached
            # through drift-score alone (no triggered_rule) is not
            # confidently labeled either way -- it could be a true positive
            # or a false positive from the drift model -- so it is left
            # unlabeled (None) for a human to review later via the /label
            # endpoint.
            triggering_events = [e for e in ordered if e.enforcement_action == "BLOCK"]
            if any(e.triggered_rule is not None for e in triggering_events):
                confirmed_attack = True
                label_source = "auto_policy"

        return TrajectoryRecord(
            id=str(uuid4()),
            organization_id=organization_id,
            session_id=session_id,
            agent_identity=agent_identity,
            step_count=len(ordered),
            drift_curve=drift_curve,
            slope_curve=slope_curve,
            r2_curve=r2_curve,
            final_enforcement_action=final_enforcement_action,
            first_divergence_step=first_divergence_step,
            root_cause_trigger=root_cause_trigger,
            blast_radius_count=blast_radius_count,
            intent_score=intent_score,
            tool_score=tool_score,
            privilege_score=privilege_score,
            identity_score=identity_score,
            data_score=data_score,
            confirmed_attack=confirmed_attack,
            label_source=label_source,
        )
