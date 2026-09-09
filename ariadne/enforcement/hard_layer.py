# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Declarative hard policy rules — deterministic, auditable, drift-independent."""

from __future__ import annotations

import json
from typing import Any

import httpx

from ariadne.config import Settings, get_settings
from ariadne.enforcement.schemas import EnforcementAction, PolicyRule, PolicyViolation
from ariadne.logging import get_logger
from ariadne.proxy.schemas import ToolCall

logger = get_logger(__name__)


def default_rules(settings: Settings) -> list[PolicyRule]:
    """The built-in rule set, mirroring `policies/default.rego` one-for-one.

    These exist so an MVP deployment needs no OPA server; when OPA_URL is set
    the Rego file is authoritative and these become the fallback.
    """
    return [
        PolicyRule(
            name="payment_requires_hitl",
            description=(
                "Money-moving tools always require an explicit human approval token, "
                "regardless of how well the action matches the stated intent."
            ),
            action=EnforcementAction.ESCALATE,
            tool_name_patterns=[
                "pay",
                "charge",
                "transfer",
                "invoice",
                "wire",
                "refund",
                "checkout",
            ],
            requires_hitl_token=True,
        ),
        PolicyRule(
            name="no_delete_without_confirmation",
            description="Destructive operations require confirmation before they reach the tool.",
            action=EnforcementAction.ESCALATE,
            tool_name_patterns=["delete", "drop", "remove", "destroy", "purge", "truncate"],
            argument_patterns=["drop table", "rm -rf", "delete from", "--force"],
            requires_hitl_token=True,
        ),
        PolicyRule(
            name="no_privilege_escalation",
            description="An agent may not grant itself roles, permissions or admin access.",
            action=EnforcementAction.BLOCK,
            tool_name_patterns=[
                "grant_role",
                "add_admin",
                "set_permission",
                "escalate",
                "assume_role",
                "sudo",
                "chmod",
                "chown",
                "attach_policy",
                "add_user_to_group",
            ],
            argument_patterns=["admin group", "role=admin", "sudo", "privilege", "is_admin"],
        ),
        PolicyRule(
            name="disallowed_domains",
            description="Tools on the deny list are never callable through this proxy.",
            action=EnforcementAction.BLOCK,
            tool_name_patterns=list(settings.disallowed_tools),
            enabled=bool(settings.disallowed_tools),
        ),
    ]


class HardPolicyLayer:
    """Evaluates hard rules, via OPA when configured and in-process otherwise."""

    def __init__(
        self,
        settings: Settings | None = None,
        rules: list[PolicyRule] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._rules = rules if rules is not None else default_rules(self._settings)
        self._client = client
        self._owns_client = client is None
        self._opa_healthy = self._settings.opa_url is not None

    @property
    def rules(self) -> list[PolicyRule]:
        return list(self._rules)

    def add_rule(self, rule: PolicyRule) -> None:
        self._rules = [existing for existing in self._rules if existing.name != rule.name]
        self._rules.append(rule)

    def remove_rule(self, name: str) -> bool:
        before = len(self._rules)
        self._rules = [rule for rule in self._rules if rule.name != name]
        return len(self._rules) != before

    async def evaluate(
        self,
        tool_call: ToolCall,
        *,
        tool_call_count: int,
        granted_capabilities: set[str] | None = None,
        hitl_token: str | None = None,
        violated_prohibitions: list[str] | None = None,
    ) -> list[PolicyViolation]:
        """Return every hard-rule violation for this call, strictest handled first."""
        violations: list[PolicyViolation] = []

        # An action that breaches an explicit user prohibition is a hard stop,
        # not a drift judgement. "Summarise this, don't email anyone" followed
        # by an email is the classic indirect-injection outcome, and the user
        # already told us the answer — no score should be able to override it.
        if violated_prohibitions:
            violations.append(
                PolicyViolation(
                    rule_name="contradicts_user_intent",
                    description=(
                        "Action contradicts a prohibition the user stated in their "
                        f"original request: {'; '.join(violated_prohibitions)}."
                    ),
                    action=EnforcementAction.BLOCK,
                    matched_on=f"prohibition~{violated_prohibitions[0]}",
                    details={"violated": violated_prohibitions},
                )
            )

        # Session-level budget: cheap, exact, and independent of tool identity.
        if tool_call_count > self._settings.max_tool_calls_per_session:
            violations.append(
                PolicyViolation(
                    rule_name="max_tool_calls_per_session",
                    description=(
                        "Session exceeded its tool-call budget of "
                        f"{self._settings.max_tool_calls_per_session}; a runaway loop is assumed."
                    ),
                    action=EnforcementAction.BLOCK,
                    matched_on=f"tool_call_count={tool_call_count}",
                    details={"limit": self._settings.max_tool_calls_per_session},
                )
            )

        if self._opa_healthy:
            opa_violations = await self._evaluate_opa(tool_call)
            if opa_violations is not None:
                violations.extend(opa_violations)
                return _apply_token(violations, hitl_token)

        violations.extend(self._evaluate_builtin(tool_call, granted_capabilities or set()))
        return _apply_token(violations, hitl_token)

    def _evaluate_builtin(
        self, tool_call: ToolCall, granted_capabilities: set[str]
    ) -> list[PolicyViolation]:
        tool_name = tool_call.tool_name.lower()
        arguments_blob = json.dumps(tool_call.arguments, default=str).lower()
        violations: list[PolicyViolation] = []

        for rule in self._rules:
            if not rule.enabled:
                continue
            matched_name = next(
                (pattern for pattern in rule.tool_name_patterns if pattern.lower() in tool_name),
                None,
            )
            matched_arg = next(
                (
                    pattern
                    for pattern in rule.argument_patterns
                    if pattern.lower() in arguments_blob
                ),
                None,
            )
            if matched_name is None and matched_arg is None:
                continue

            # An explicitly granted capability is a deliberate operator decision
            # and overrides pattern-based privilege suspicion.
            if rule.name == "no_privilege_escalation" and tool_name in granted_capabilities:
                logger.info(
                    "enforcement.rule_waived_by_grant",
                    rule=rule.name,
                    tool_name=tool_call.tool_name,
                )
                continue

            violations.append(
                PolicyViolation(
                    rule_name=rule.name,
                    description=rule.description,
                    action=rule.action,
                    matched_on=f"tool_name~{matched_name}"
                    if matched_name
                    else f"arguments~{matched_arg}",
                    requires_hitl_token=rule.requires_hitl_token,
                    details={"tool_name": tool_call.tool_name},
                )
            )

        return violations

    async def _evaluate_opa(self, tool_call: ToolCall) -> list[PolicyViolation] | None:
        """Query OPA. Returns None when OPA cannot answer, so we fall back."""
        if not self._settings.opa_url:
            return None
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=5.0)
            self._owns_client = True

        url = f"{self._settings.opa_url.rstrip('/')}{self._settings.opa_policy_path}"
        document = {
            "input": {
                "tool_name": tool_call.tool_name,
                "arguments": tool_call.arguments,
                "session_id": tool_call.session_id,
                "step_index": tool_call.step_index,
                "calling_agent_id": tool_call.calling_agent_id,
            }
        }
        try:
            response = await self._client.post(url, json=document)
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            logger.error(
                "enforcement.opa_unreachable",
                url=url,
                error=str(exc),
                fallback="builtin_rules",
            )
            self._opa_healthy = False
            return None
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            logger.error(
                "enforcement.opa_query_failed",
                url=url,
                error=str(exc),
                error_type=type(exc).__name__,
                fallback="builtin_rules",
            )
            return None

        return _parse_opa_result(payload.get("result"))

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None


def _parse_opa_result(result: Any) -> list[PolicyViolation]:
    """Translate an OPA decision document into violations.

    Accepts either the simple boolean `allow` shape or the richer
    `{"allow": bool, "violations": [...]}` document that default.rego emits.
    """
    if result is None:
        return []
    if isinstance(result, bool):
        return (
            []
            if result
            else [
                PolicyViolation(
                    rule_name="opa_deny",
                    description="OPA policy denied this tool call.",
                    action=EnforcementAction.BLOCK,
                    matched_on="opa:allow=false",
                )
            ]
        )
    if not isinstance(result, dict):
        return []

    violations: list[PolicyViolation] = []
    for raw in result.get("violations", []) or []:
        if not isinstance(raw, dict):
            continue
        action_text = str(raw.get("action", EnforcementAction.BLOCK.value)).upper()
        action = (
            EnforcementAction(action_text)
            if action_text in EnforcementAction.__members__
            else EnforcementAction.BLOCK
        )
        violations.append(
            PolicyViolation(
                rule_name=str(raw.get("rule", "opa_rule")),
                description=str(raw.get("description", "OPA policy violation")),
                action=action,
                matched_on=str(raw.get("matched_on", "opa")),
                requires_hitl_token=bool(raw.get("requires_hitl_token", False)),
                details={"source": "opa"},
            )
        )
    if not violations and result.get("allow") is False:
        violations.append(
            PolicyViolation(
                rule_name="opa_deny",
                description="OPA policy denied this tool call.",
                action=EnforcementAction.BLOCK,
                matched_on="opa:allow=false",
            )
        )
    return violations


def _apply_token(
    violations: list[PolicyViolation], hitl_token: str | None
) -> list[PolicyViolation]:
    """Drop escalations the caller already holds a human approval token for."""
    if not hitl_token:
        return violations
    return [
        violation
        for violation in violations
        if not (violation.requires_hitl_token and violation.action == EnforcementAction.ESCALATE)
    ]
