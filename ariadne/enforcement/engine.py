# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""The hybrid enforcement engine: hard rules first, then graduated drift response."""

from __future__ import annotations

import uuid

from ariadne.audit.schemas import AuditEvent
from ariadne.config import Settings, get_settings
from ariadne.drift.schemas import DriftScore
from ariadne.enforcement.hard_layer import HardPolicyLayer
from ariadne.enforcement.schemas import (
    ACTION_SEVERITY,
    EnforcementAction,
    EnforcementDecision,
    PolicyViolation,
)
from ariadne.enforcement.soft_layer import SoftDriftLayer
from ariadne.logging import get_logger
from ariadne.proxy.schemas import ToolCall

logger = get_logger(__name__)


class HybridEnforcementEngine:
    """Combines deterministic policy with semantic drift.

    Hard rules run first and short-circuit: they are exact, explainable, and
    must not be overridable by a low drift score — an attacker who keeps every
    step semantically on-mission still cannot wire money without approval.
    """

    def __init__(
        self,
        hard_layer: HardPolicyLayer | None = None,
        soft_layer: SoftDriftLayer | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._hard = hard_layer or HardPolicyLayer(self._settings)
        self._soft = soft_layer or SoftDriftLayer(self._settings)

    @property
    def hard_layer(self) -> HardPolicyLayer:
        return self._hard

    @property
    def soft_layer(self) -> SoftDriftLayer:
        return self._soft

    async def decide(
        self,
        tool_call: ToolCall,
        drift_score: DriftScore | None,
        *,
        tool_call_count: int,
        graph_node_id: str | None = None,
        granted_capabilities: set[str] | None = None,
        hitl_token: str | None = None,
        violated_prohibitions: list[str] | None = None,
        latency_ms: float = 0.0,
    ) -> EnforcementDecision:
        """Produce the verdict for one tool call."""
        violations = await self._hard.evaluate(
            tool_call,
            tool_call_count=tool_call_count,
            granted_capabilities=granted_capabilities,
            hitl_token=hitl_token,
            violated_prohibitions=violated_prohibitions,
        )

        if violations:
            decision = self._from_violations(violations, tool_call, drift_score, graph_node_id)
        elif drift_score is not None:
            action, reason = self._soft.evaluate(drift_score)
            decision = EnforcementDecision(
                action=action.value,
                reason=reason,
                drift_score=drift_score.drift_score,
                blocking_node_id=graph_node_id
                if action in (EnforcementAction.BLOCK, EnforcementAction.ESCALATE)
                else None,
                requires_hitl_token=action is EnforcementAction.ESCALATE,
                layer="soft",
            )
        else:
            # No hard violation and no score to judge by. FAIL_CLOSED refuses
            # rather than silently forwarding an unscored action.
            fail_closed = self._settings.fail_mode.value == "FAIL_CLOSED"
            decision = EnforcementDecision(
                action=EnforcementAction.BLOCK.value
                if fail_closed
                else EnforcementAction.ALLOW.value,
                reason=(
                    "No drift score available for this action and FAIL_CLOSED is configured."
                    if fail_closed
                    else "No drift score available; FAIL_OPEN is configured so the call proceeds."
                ),
                layer="none",
                blocking_node_id=graph_node_id if fail_closed else None,
            )

        decision.audit_event = AuditEvent(
            event_id=str(uuid.uuid4()),
            session_id=tool_call.session_id,
            step_index=tool_call.step_index,
            tool_name=tool_call.tool_name,
            enforcement_action=decision.action,
            reason=decision.reason,
            triggered_rule=decision.triggered_rule,
            drift_score=drift_score.drift_score if drift_score else None,
            slope=drift_score.slope if drift_score else None,
            raw_distance=drift_score.raw_distance if drift_score else None,
            node_id=graph_node_id,
            latency_ms=latency_ms,
            payload={
                "arguments": tool_call.arguments,
                "calling_agent_id": tool_call.calling_agent_id,
                "layer": decision.layer,
                "violations": [
                    violation.model_dump(mode="json") for violation in decision.violations
                ],
            },
        )

        logger.info(
            "enforcement.decision",
            session_id=tool_call.session_id,
            step_index=tool_call.step_index,
            tool_name=tool_call.tool_name,
            action=decision.action,
            layer=decision.layer,
            triggered_rule=decision.triggered_rule,
            drift_score=round(drift_score.drift_score, 2) if drift_score else None,
            latency_ms=round(latency_ms, 2),
        )
        return decision

    @staticmethod
    def _from_violations(
        violations: list[PolicyViolation],
        tool_call: ToolCall,
        drift_score: DriftScore | None,
        graph_node_id: str | None,
    ) -> EnforcementDecision:
        strictest = max(violations, key=lambda violation: ACTION_SEVERITY[violation.action.value])
        return EnforcementDecision(
            action=strictest.action.value,
            reason=(
                f"Hard policy '{strictest.rule_name}' fired on "
                f"{tool_call.tool_name} ({strictest.matched_on}): {strictest.description}"
            ),
            triggered_rule=strictest.rule_name,
            drift_score=drift_score.drift_score if drift_score else None,
            blocking_node_id=graph_node_id,
            requires_hitl_token=strictest.requires_hitl_token,
            layer="hard",
            violations=violations,
        )

    async def aclose(self) -> None:
        await self._hard.aclose()
