# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Deterministic, rule-based drift narratives — no LLM calls, no external services.

This module exists to turn a drift score into a sentence an operator can read
in under a second. It is intentionally boring: every branch is a fixed
threshold or a fixed string template, so it adds no latency risk and can
never itself become a source of hallucinated explanations. Nothing here may
call an LLM, a network service, or anything that can raise in a way the
caller has not already guarded against.
"""

from __future__ import annotations

from pydantic import BaseModel

from ariadne.drift.schemas import DriftScore
from ariadne.drift.window import SlidingWindow
from ariadne.graph.schemas import EdgeType, GraphNode, NodeType


class DriftNarrative(BaseModel):
    """A human-readable explanation of one step's drift verdict."""

    session_id: str
    step_index: int
    summary: str
    detail: str | None = None
    trigger: str | None = None
    consecutive_escalation_steps: int = 0
    first_divergence_step: int | None = None


#: Fallback narrative used when generation itself fails. Must never raise.
def _safe_fallback(session_id: str, step_index: int) -> DriftNarrative:
    return DriftNarrative(
        session_id=session_id,
        step_index=step_index,
        summary="drift narrative unavailable",
        detail=None,
        trigger=None,
        consecutive_escalation_steps=0,
        first_divergence_step=None,
    )


class DriftNarrator:
    """Builds a :class:`DriftNarrative` from a scored step and its context."""

    def narrate(
        self,
        session_id: str,
        step_index: int,
        drift_score: DriftScore,
        window: SlidingWindow,
        recent_nodes: list[GraphNode],
        enforcement_action: str,
        first_divergence_step: int | None,
    ) -> DriftNarrative:
        try:
            return self._narrate(
                session_id,
                step_index,
                drift_score,
                window,
                recent_nodes,
                enforcement_action,
                first_divergence_step,
            )
        except Exception:  # noqa: BLE001 - narration must never break the pipeline
            return _safe_fallback(session_id, step_index)

    def _narrate(
        self,
        session_id: str,
        step_index: int,
        drift_score: DriftScore,
        window: SlidingWindow,
        recent_nodes: list[GraphNode],
        enforcement_action: str,
        first_divergence_step: int | None,
    ) -> DriftNarrative:
        score = drift_score.drift_score
        slope = drift_score.slope
        consecutive = self._consecutive_escalation_steps(window)
        trigger = self._identify_trigger(recent_nodes, window)

        if score < 40:
            return DriftNarrative(
                session_id=session_id,
                step_index=step_index,
                summary="Action aligns with stated intent.",
                detail=None,
                trigger=None,
                consecutive_escalation_steps=consecutive,
                first_divergence_step=first_divergence_step,
            )

        if score < 65:
            if slope <= 0:
                return DriftNarrative(
                    session_id=session_id,
                    step_index=step_index,
                    summary=(
                        "Elevated drift but trend is stabilising — "
                        "possible lateral exploration."
                    ),
                    detail=None,
                    trigger=trigger,
                    consecutive_escalation_steps=consecutive,
                    first_divergence_step=first_divergence_step,
                )
            return DriftNarrative(
                session_id=session_id,
                step_index=step_index,
                summary=(
                    f"Drift is rising over {consecutive} consecutive steps. "
                    "Last action moved further from intent."
                ),
                detail=f"Drift accelerated for {consecutive} consecutive steps after {trigger}.",
                trigger=trigger,
                consecutive_escalation_steps=consecutive,
                first_divergence_step=first_divergence_step,
            )

        if score < 85:
            return DriftNarrative(
                session_id=session_id,
                step_index=step_index,
                summary="Significant escalating drift. This action requires review before proceeding.",
                detail=(
                    f"First divergence was at step {first_divergence_step}. Trigger: {trigger}."
                ),
                trigger=trigger,
                consecutive_escalation_steps=consecutive,
                first_divergence_step=first_divergence_step,
            )

        return DriftNarrative(
            session_id=session_id,
            step_index=step_index,
            summary=(
                f"Execution blocked. Agent progressively diverged from intent over "
                f"{consecutive} steps starting at step {first_divergence_step}."
            ),
            detail=f"Trigger: {trigger}. Downstream actions prevented by this block.",
            trigger=trigger,
            consecutive_escalation_steps=consecutive,
            first_divergence_step=first_divergence_step,
        )

    def _consecutive_escalation_steps(self, window: SlidingWindow) -> int:
        """Count consecutive recent samples with a rising step-to-step distance.

        Walks the window's distances from the end backwards, counting how many
        consecutive pairs are increasing. This is a proxy for "how many steps
        has the slope been positive," computed from the raw samples the window
        already holds rather than re-fitting a line per step.
        """
        distances = window.distances
        if len(distances) < 2:
            return 0
        count = 0
        for i in range(len(distances) - 1, 0, -1):
            if distances[i] > distances[i - 1]:
                count += 1
            else:
                break
        return count

    def _identify_trigger(self, recent_nodes: list[GraphNode], window: SlidingWindow) -> str:
        for node in recent_nodes:
            for edge_type in node.node_metadata.get("edge_types", []):
                if edge_type == EdgeType.ESCALATES_PRIVILEGE.value:
                    return "privilege escalation attempt"

        for node in recent_nodes:
            for edge_type in node.node_metadata.get("edge_types", []):
                if edge_type == EdgeType.CONTRADICTS.value:
                    constraint = node.node_metadata.get("contradicted_constraint")
                    if constraint:
                        return f"action contradicts user constraint: '{constraint}'"
                    return "action contradicts user constraint"

        if recent_nodes:
            preceding = recent_nodes[-1]
            if preceding.node_type == NodeType.TOOL_RESULT:
                return "untrusted external tool result"

        if self._consecutive_escalation_steps(window) >= 3:
            return "sustained lateral movement away from stated goal"

        return "cumulative semantic drift from original intent"
