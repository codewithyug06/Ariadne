# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""The interception pipeline: embed, score, graph, enforce."""

from __future__ import annotations

import time

from sqlalchemy import select

from ariadne.audit.recorder import AuditRecorder
from ariadne.config import Settings, get_settings
from ariadne.db.models import LEGACY_ORG_ID, CalibrationProfile, OrgToolOverride
from ariadne.db.session import Database
from ariadne.drift.calibration import calibration_note_for_score, get_active_profile
from ariadne.drift.embedder import ActionEmbedder
from ariadne.drift.extrapolator import DriftProjection, ExtrapolationPredictor, RiskPredictor
from ariadne.drift.narrative import DriftNarrative, DriftNarrator
from ariadne.drift.schemas import DriftUpdate
from ariadne.drift.scorer import TrajectoryScorer
from ariadne.drift.versioning import current_stamp
from ariadne.drift.window import WindowRegistry
from ariadne.enforcement.engine import HybridEnforcementEngine
from ariadne.graph.builder import ProvenanceGraphBuilder
from ariadne.intent.anchor import IntentAnchorGenerator
from ariadne.logging import get_logger
from ariadne.proxy.schemas import InterceptionResult, SessionState, ToolCall, ToolResult
from ariadne.streaming import DriftStreamHub

#: How long a fetched active CalibrationProfile is trusted before the next
#: interception re-queries the DB. Balances "activating a new profile should
#: take effect reasonably soon" against "don't hit the DB on every single
#: tool call" -- the interception hot path already does several DB/graph
#: round trips per call, so this is not the place to add an unconditional one.
_CALIBRATION_CACHE_TTL_SECONDS = 30.0

logger = get_logger(__name__)


class ToolCallInterceptor:
    """Runs every tool call through Ariadne before it reaches the real tool.

    Owns no session state of its own beyond the drift windows; the proxy passes
    the SessionState in, so a single interceptor serves all concurrent sessions.
    """

    def __init__(
        self,
        embedder: ActionEmbedder,
        scorer: TrajectoryScorer,
        graph_builder: ProvenanceGraphBuilder,
        engine: HybridEnforcementEngine,
        anchors: IntentAnchorGenerator,
        recorder: AuditRecorder,
        stream_hub: DriftStreamHub,
        settings: Settings | None = None,
        predictor: RiskPredictor | None = None,
        database: Database | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._embedder = embedder
        self._scorer = scorer
        self._graph = graph_builder
        self._engine = engine
        self._anchors = anchors
        self._recorder = recorder
        self._hub = stream_hub
        self._windows = WindowRegistry(self._settings.drift_window_size)
        self._narrator = DriftNarrator()
        # Feature 8 (drift extrapolation engine). Constructor-injectable, same
        # DI style as the pluggable graph/hard-layer backends elsewhere in the
        # codebase, so a future XGBoostPredictor can be swapped in without
        # touching this class.
        self._predictor: RiskPredictor = predictor or ExtrapolationPredictor(
            settings=self._settings
        )
        # Feature 9 (calibrated/versioned risk scores). Optional: unit tests
        # and any caller that doesn't need calibration stamping can construct
        # this without a Database at all, same tolerance-for-missing-deps
        # pattern as `predictor` above -- calibration stamping then falls
        # back to an unstamped "" version rather than failing.
        self._database = database
        self._calibration_cache: tuple[float, CalibrationProfile | None] | None = None
        # Feature 10 (contextual tool-risk scoring). Org tool overrides are
        # cached per-organization with the same TTL/style as the calibration
        # profile cache above -- loaded once per TTL window, not once per
        # call, since the interception hot path already does several DB/graph
        # round trips per tool call.
        self._tool_override_cache: dict[str, tuple[float, dict[str, float]]] = {}

    async def _get_active_calibration_profile(self) -> CalibrationProfile | None:
        """Cached lookup of the active CalibrationProfile, see the TTL constant above."""
        if self._database is None:
            return None
        now = time.monotonic()
        if self._calibration_cache is not None:
            fetched_at, cached = self._calibration_cache
            if now - fetched_at < _CALIBRATION_CACHE_TTL_SECONDS:
                return cached
        try:
            async with self._database.session() as session:
                profile = await get_active_profile(session)
        except Exception as exc:  # noqa: BLE001 - stamping must never break interception
            logger.warning("calibration.lookup_failed", error=str(exc))
            profile = None
        self._calibration_cache = (now, profile)
        return profile

    async def _get_org_tool_overrides(self, organization_id: str) -> dict[str, float]:
        """Cached lookup of an org's tool-risk overrides, see the TTL constant above."""
        if self._database is None:
            return {}
        now = time.monotonic()
        cached_entry = self._tool_override_cache.get(organization_id)
        if cached_entry is not None:
            fetched_at, cached = cached_entry
            if now - fetched_at < _CALIBRATION_CACHE_TTL_SECONDS:
                return cached
        overrides: dict[str, float] = {}
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    select(OrgToolOverride).where(
                        OrgToolOverride.organization_id == organization_id
                    )
                )
                overrides = {row.tool_name: row.risk_override for row in result.scalars().all()}
        except Exception as exc:  # noqa: BLE001 - risk scoring must never break interception
            logger.warning("tool_overrides.lookup_failed", error=str(exc))
            overrides = {}
        self._tool_override_cache[organization_id] = (now, overrides)
        return overrides

    @property
    def windows(self) -> WindowRegistry:
        return self._windows

    async def intercept(
        self,
        tool_call: ToolCall,
        state: SessionState,
        hitl_token: str | None = None,
    ) -> InterceptionResult:
        """Score and adjudicate one tool call.

        Never raises: an internal failure resolves to the configured fail mode
        so the caller always has a decision to act on.
        """
        started = time.perf_counter()
        try:
            return await self._run_pipeline(tool_call, state, hitl_token, started)
        except Exception as exc:  # noqa: BLE001 - fail mode is the contract here
            latency_ms = (time.perf_counter() - started) * 1000.0
            fail_closed = self._settings.fail_mode.value == "FAIL_CLOSED"
            action = "BLOCK" if fail_closed else "ALLOW"
            logger.error(
                "interceptor.pipeline_failed",
                session_id=tool_call.session_id,
                step_index=tool_call.step_index,
                tool_name=tool_call.tool_name,
                error=str(exc),
                error_type=type(exc).__name__,
                fail_mode=self._settings.fail_mode.value,
                resolved_action=action,
                latency_ms=round(latency_ms, 2),
                exc_info=True,
            )
            return InterceptionResult(
                session_id=tool_call.session_id,
                step_index=tool_call.step_index,
                tool_name=tool_call.tool_name,
                action=action,
                reason=(
                    f"Ariadne internal error ({type(exc).__name__}); "
                    f"{self._settings.fail_mode.value} policy applied."
                ),
                latency_ms=latency_ms,
                degraded=True,
            )

    async def _run_pipeline(
        self,
        tool_call: ToolCall,
        state: SessionState,
        hitl_token: str | None,
        started: float,
    ) -> InterceptionResult:
        anchor = self._anchors.get(tool_call.session_id)

        # 1. Embed the action.
        action_embedding = self._embedder.embed(tool_call)

        # 2. Score its drift from the anchor. Without an anchor there is no
        #    reference point, so the hard layer alone adjudicates.
        drift_score = None
        if anchor is not None:
            window = self._windows.get(tool_call.session_id)
            drift_score = self._scorer.score(
                session_id=tool_call.session_id,
                intent_embedding=anchor.embedding,
                action_embedding=action_embedding,
                window=window,
                step_index=tool_call.step_index,
            )
            state.max_drift_score = max(state.max_drift_score, drift_score.drift_score)

        # 3. Record the attempt in the provenance graph before adjudicating, so
        #    a blocked call is still visible in the graph and the audit trail.
        node = await self._graph.add_tool_call(
            tool_call,
            drift_score,
            enforcement_action="PENDING",
            anchor=anchor,
            organization_id=state.organization_id,
        )

        # 4. Adjudicate. Prohibitions the user stated explicitly are passed to
        #    the hard layer, where no drift score can overrule them.
        latency_ms = (time.perf_counter() - started) * 1000.0
        violated = (
            anchor.violated_prohibitions(tool_call.to_natural_language())
            if anchor is not None
            else []
        )
        org_tool_overrides = await self._get_org_tool_overrides(state.organization_id)
        decision = await self._engine.decide(
            tool_call,
            drift_score,
            tool_call_count=state.tool_call_count,
            graph_node_id=node.id,
            granted_capabilities=self._graph.granted_capabilities(tool_call.session_id),
            hitl_token=hitl_token,
            violated_prohibitions=violated,
            latency_ms=latency_ms,
            intent_anchor=anchor,
            graph_builder=self._graph,
            session_history=state.tool_call_history,
            org_tool_overrides=org_tool_overrides,
        )
        # Feature 10: record this call for future session-novelty scoring.
        # Appended after adjudication (not before) so `session_history` above
        # correctly reflects "prior" calls only, excluding this one.
        state.tool_call_history.append(tool_call)
        # Nodes are written PENDING before adjudication so a blocked call still
        # appears in the graph; the verdict has to be pushed back to the store,
        # not just onto the in-memory object, or durable backends keep PENDING.
        await self._graph.finalize_node(node, decision.action)

        # 4b. Drift narrative — deterministic, rule-based, no LLM/network calls.
        # Wrapped defensively: a narration failure must never propagate into
        # the interception hot path, so it is caught here (in addition to
        # DriftNarrator.narrate's own internal guard) and downgraded to a
        # safe fallback.
        narrative: DriftNarrative | None = None
        if drift_score is not None:
            try:
                if (
                    state.first_divergence_step is None
                    and drift_score.drift_score >= self._settings.drift_score_warn
                ):
                    state.first_divergence_step = tool_call.step_index
                session_graph = await self._graph.session_graph(tool_call.session_id)
                edge_types_by_source: dict[str, list[str]] = {}
                for edge in session_graph.edges:
                    edge_types_by_source.setdefault(edge.source_id, []).append(
                        edge.edge_type.value
                    )
                recent_nodes = session_graph.nodes[-5:]
                for recent_node in recent_nodes:
                    recent_node.node_metadata["edge_types"] = edge_types_by_source.get(
                        recent_node.id, []
                    )
                narrative = self._narrator.narrate(
                    session_id=tool_call.session_id,
                    step_index=tool_call.step_index,
                    drift_score=drift_score,
                    window=window,
                    recent_nodes=recent_nodes,
                    enforcement_action=decision.action,
                    first_divergence_step=state.first_divergence_step,
                )
            except Exception as exc:  # noqa: BLE001 - must never break interception
                logger.warning("narrative.generation_failed", error=str(exc))
                narrative = DriftNarrative(
                    session_id=tool_call.session_id,
                    step_index=tool_call.step_index,
                    summary="drift narrative unavailable",
                )

        # 4c. Drift extrapolation — purely deterministic, no model. Wrapped
        # defensively for the same reason as narration above: a projection
        # failure (or a predictor that raises, like the XGBoostPredictor
        # scaffold if ever misconfigured as the active predictor) must never
        # propagate into the interception hot path.
        projection: DriftProjection | None = None
        if drift_score is not None:
            try:
                projection = self._predictor.predict(drift_score, window)
            except Exception as exc:  # noqa: BLE001 - must never break interception
                logger.warning("projection.generation_failed", error=str(exc))
                projection = None

        # 4d. Calibration/versioning stamp -- attached to every scored event
        # (not just when a drift_score exists) so even an ALLOW with no
        # anchor still records exactly which embedding/weights/scorer
        # versions were in effect. Wrapped defensively for the same reason
        # as narration/projection above.
        calibration_profile: CalibrationProfile | None = None
        try:
            calibration_profile = await self._get_active_calibration_profile()
        except Exception as exc:  # noqa: BLE001 - must never break interception
            logger.warning("calibration.stamp_failed", error=str(exc))

        calibration_version = calibration_profile.version if calibration_profile else ""
        stamp = current_stamp(calibration_version, settings=self._settings)
        calibration_note = None
        if drift_score is not None and calibration_profile is not None:
            drift_score.calibration_version = calibration_version
            try:
                calibration_note = calibration_note_for_score(
                    calibration_profile, drift_score.drift_score
                )
            except Exception as exc:  # noqa: BLE001 - must never break interception
                logger.warning("calibration.note_failed", error=str(exc))

        # 5. Persist and broadcast.
        if decision.audit_event is not None:
            if narrative is not None:
                decision.audit_event.narrative = narrative.model_dump(mode="json")
            if projection is not None:
                decision.audit_event.projection = projection.model_dump(mode="json")
            decision.audit_event.scoring_version = stamp.model_dump(mode="json")
            decision.audit_event.calibration_note = calibration_note
            self._recorder.record_event(decision.audit_event, organization_id=state.organization_id)
        if decision.action in ("ESCALATE", "BLOCK"):
            await self._graph.add_alert(
                session_id=tool_call.session_id,
                step_index=tool_call.step_index,
                reason=decision.reason,
                triggering_node_id=node.id,
                action=decision.action,
                organization_id=state.organization_id,
            )
            self._recorder.record_alert(
                session_id=tool_call.session_id,
                step_index=tool_call.step_index,
                tool_name=tool_call.tool_name,
                action=decision.action,
                reason=decision.reason,
                drift_score=decision.drift_score,
                node_id=node.id,
                organization_id=state.organization_id,
            )

        _update_state(state, decision.action)

        self._hub.publish(
            DriftUpdate(
                session_id=tool_call.session_id,
                step_index=tool_call.step_index,
                tool_name=tool_call.tool_name,
                drift_score=drift_score.drift_score if drift_score else 0.0,
                slope=drift_score.slope if drift_score else 0.0,
                raw_distance=drift_score.raw_distance if drift_score else 0.0,
                enforcement_action=decision.action,
                reason=decision.reason,
                node_id=node.id,
                agent_identity=tool_call.calling_agent_id,
                narrative_summary=narrative.summary if narrative else None,
                narrative_trigger=narrative.trigger if narrative else None,
                projection=projection.model_dump(mode="json") if projection else None,
            )
        )

        total_latency_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "interceptor.completed",
            session_id=tool_call.session_id,
            step_index=tool_call.step_index,
            tool_name=tool_call.tool_name,
            enforcement_action=decision.action,
            drift_score=round(drift_score.drift_score, 2) if drift_score else None,
            slope=round(drift_score.slope, 4) if drift_score else None,
            node_id=node.id,
            latency_ms=round(total_latency_ms, 2),
        )

        return InterceptionResult(
            session_id=tool_call.session_id,
            step_index=tool_call.step_index,
            tool_name=tool_call.tool_name,
            action=decision.action,
            reason=decision.reason,
            drift_score=drift_score.drift_score if drift_score else None,
            slope=drift_score.slope if drift_score else None,
            raw_distance=drift_score.raw_distance if drift_score else None,
            graph_node_id=node.id,
            triggered_rule=decision.triggered_rule,
            layer=decision.layer,
            requires_hitl_token=decision.requires_hitl_token,
            latency_ms=total_latency_ms,
        )

    async def record_result(
        self, tool_result: ToolResult, call_node_id: str, organization_id: str = LEGACY_ORG_ID
    ) -> str:
        """Add an upstream result to the graph. Failures here never fail the call."""
        try:
            node = await self._graph.add_tool_result(
                tool_result, call_node_id, organization_id=organization_id
            )
        except Exception as exc:  # noqa: BLE001 - provenance loss must not break the run
            logger.error(
                "interceptor.result_graph_failed",
                session_id=tool_result.session_id,
                step_index=tool_result.step_index,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return ""
        return node.id

    def release_session(self, session_id: str) -> None:
        """Drop per-session working state once a run ends."""
        self._windows.discard(session_id)
        self._graph.discard(session_id)
        self._anchors.discard(session_id)


def _update_state(state: SessionState, action: str) -> None:
    if action == "WARN":
        state.warned = True
    elif action == "ESCALATE":
        state.escalated = True
    elif action == "BLOCK":
        state.blocked = True
