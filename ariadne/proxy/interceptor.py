# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""The interception pipeline: embed, score, graph, enforce."""

from __future__ import annotations

import time

from ariadne.audit.recorder import AuditRecorder
from ariadne.config import Settings, get_settings
from ariadne.drift.embedder import ActionEmbedder
from ariadne.drift.schemas import DriftUpdate
from ariadne.drift.scorer import TrajectoryScorer
from ariadne.drift.window import WindowRegistry
from ariadne.enforcement.engine import HybridEnforcementEngine
from ariadne.graph.builder import ProvenanceGraphBuilder
from ariadne.intent.anchor import IntentAnchorGenerator
from ariadne.logging import get_logger
from ariadne.proxy.schemas import InterceptionResult, SessionState, ToolCall, ToolResult
from ariadne.streaming import DriftStreamHub

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
            tool_call, drift_score, enforcement_action="PENDING", anchor=anchor
        )

        # 4. Adjudicate. Prohibitions the user stated explicitly are passed to
        #    the hard layer, where no drift score can overrule them.
        latency_ms = (time.perf_counter() - started) * 1000.0
        violated = (
            anchor.violated_prohibitions(tool_call.to_natural_language())
            if anchor is not None
            else []
        )
        decision = await self._engine.decide(
            tool_call,
            drift_score,
            tool_call_count=state.tool_call_count,
            graph_node_id=node.id,
            granted_capabilities=self._graph.granted_capabilities(tool_call.session_id),
            hitl_token=hitl_token,
            violated_prohibitions=violated,
            latency_ms=latency_ms,
        )
        # Nodes are written PENDING before adjudication so a blocked call still
        # appears in the graph; the verdict has to be pushed back to the store,
        # not just onto the in-memory object, or durable backends keep PENDING.
        await self._graph.finalize_node(node, decision.action)

        # 5. Persist and broadcast.
        if decision.audit_event is not None:
            self._recorder.record_event(decision.audit_event)
        if decision.action in ("ESCALATE", "BLOCK"):
            await self._graph.add_alert(
                session_id=tool_call.session_id,
                step_index=tool_call.step_index,
                reason=decision.reason,
                triggering_node_id=node.id,
                action=decision.action,
            )
            self._recorder.record_alert(
                session_id=tool_call.session_id,
                step_index=tool_call.step_index,
                tool_name=tool_call.tool_name,
                action=decision.action,
                reason=decision.reason,
                drift_score=decision.drift_score,
                node_id=node.id,
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

    async def record_result(self, tool_result: ToolResult, call_node_id: str) -> str:
        """Add an upstream result to the graph. Failures here never fail the call."""
        try:
            node = await self._graph.add_tool_result(tool_result, call_node_id)
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
