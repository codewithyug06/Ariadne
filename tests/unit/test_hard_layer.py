# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Hard policy layer: deterministic rules that drift cannot override."""

from __future__ import annotations

import pytest

from ariadne.config import Settings
from ariadne.enforcement.hard_layer import HardPolicyLayer, _parse_opa_result
from ariadne.enforcement.schemas import EnforcementAction, PolicyRule
from ariadne.proxy.schemas import ToolCall


def make_call(tool_name: str, arguments: dict[str, object] | None = None, step: int = 1) -> ToolCall:
    return ToolCall(
        session_id="hard-layer-test",
        step_index=step,
        tool_name=tool_name,
        arguments=arguments or {},
    )


@pytest.fixture
def layer(settings: Settings) -> HardPolicyLayer:
    return HardPolicyLayer(settings)


class TestPaymentRule:
    @pytest.mark.parametrize(
        "tool_name",
        ["make_payment", "charge_card", "transfer_funds", "create_invoice", "wire_money"],
    )
    async def test_money_tools_require_human_approval(
        self, layer: HardPolicyLayer, tool_name: str
    ) -> None:
        violations = await layer.evaluate(make_call(tool_name), tool_call_count=1)
        rules = {violation.rule_name for violation in violations}
        assert "payment_requires_hitl" in rules

        payment = next(v for v in violations if v.rule_name == "payment_requires_hitl")
        assert payment.action is EnforcementAction.ESCALATE
        assert payment.requires_hitl_token is True

    async def test_an_approval_token_satisfies_the_rule(self, layer: HardPolicyLayer) -> None:
        violations = await layer.evaluate(
            make_call("make_payment"), tool_call_count=1, hitl_token="approved-by-a-human"
        )
        assert violations == []


class TestBenignCalls:
    @pytest.mark.parametrize("tool_name", ["list_files", "read_file", "search", "summarize"])
    async def test_ordinary_tools_trigger_no_rule(
        self, layer: HardPolicyLayer, tool_name: str
    ) -> None:
        assert await layer.evaluate(make_call(tool_name), tool_call_count=1) == []

    async def test_benign_arguments_do_not_trigger_rules(self, layer: HardPolicyLayer) -> None:
        call = make_call("read_file", {"path": "/var/log/app.log", "lines": 100})
        assert await layer.evaluate(call, tool_call_count=1) == []


class TestDeleteRule:
    async def test_destructive_tool_name_escalates(self, layer: HardPolicyLayer) -> None:
        violations = await layer.evaluate(make_call("delete_records"), tool_call_count=1)
        assert any(v.rule_name == "no_delete_without_confirmation" for v in violations)

    async def test_destructive_payload_escalates_under_a_benign_name(
        self, layer: HardPolicyLayer
    ) -> None:
        """The dangerous part is often the argument, not the tool name."""
        call = make_call("run_query", {"sql": "DROP TABLE customers"})
        violations = await layer.evaluate(call, tool_call_count=1)
        assert any(v.rule_name == "no_delete_without_confirmation" for v in violations)


class TestPrivilegeEscalationRule:
    async def test_role_grant_is_blocked_outright(self, layer: HardPolicyLayer) -> None:
        violations = await layer.evaluate(
            make_call("grant_role", {"user": "agent", "role": "admin"}), tool_call_count=1
        )
        privilege = next(v for v in violations if v.rule_name == "no_privilege_escalation")
        assert privilege.action is EnforcementAction.BLOCK
        assert privilege.requires_hitl_token is False

    async def test_explicit_grant_waives_the_rule(self, layer: HardPolicyLayer) -> None:
        """An operator-granted capability is a deliberate decision, not an escalation."""
        violations = await layer.evaluate(
            make_call("assume_role"),
            tool_call_count=1,
            granted_capabilities={"assume_role"},
        )
        assert not any(v.rule_name == "no_privilege_escalation" for v in violations)


class TestSessionBudget:
    async def test_exceeding_the_budget_blocks(self, settings: Settings) -> None:
        layer = HardPolicyLayer(settings)
        over_budget = settings.max_tool_calls_per_session + 1
        violations = await layer.evaluate(make_call("list_files"), tool_call_count=over_budget)
        budget = next(v for v in violations if v.rule_name == "max_tool_calls_per_session")
        assert budget.action is EnforcementAction.BLOCK

    async def test_at_the_limit_is_still_allowed(self, settings: Settings) -> None:
        layer = HardPolicyLayer(settings)
        violations = await layer.evaluate(
            make_call("list_files"), tool_call_count=settings.max_tool_calls_per_session
        )
        assert violations == []


class TestDisallowedTools:
    async def test_deny_list_blocks(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        settings = Settings(
            DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path.as_posix()}/t.db",
            DISALLOWED_TOOLS="internal_admin_console,billing_root",
        )
        layer = HardPolicyLayer(settings)
        violations = await layer.evaluate(
            make_call("internal_admin_console"), tool_call_count=1
        )
        assert any(v.rule_name == "disallowed_domains" for v in violations)

    async def test_rule_is_disabled_when_the_list_is_empty(self, layer: HardPolicyLayer) -> None:
        rule = next(r for r in layer.rules if r.name == "disallowed_domains")
        assert rule.enabled is False


class TestRuntimeRuleManagement:
    async def test_added_rule_takes_effect_immediately(self, layer: HardPolicyLayer) -> None:
        layer.add_rule(
            PolicyRule(
                name="no_social_media",
                description="This deployment does not post to social platforms.",
                action=EnforcementAction.BLOCK,
                tool_name_patterns=["tweet", "post_to_"],
            )
        )
        violations = await layer.evaluate(make_call("tweet_update"), tool_call_count=1)
        assert any(v.rule_name == "no_social_media" for v in violations)

    async def test_removed_rule_stops_firing(self, layer: HardPolicyLayer) -> None:
        assert layer.remove_rule("payment_requires_hitl") is True
        assert await layer.evaluate(make_call("make_payment"), tool_call_count=1) == []

    def test_removing_an_unknown_rule_reports_false(self, layer: HardPolicyLayer) -> None:
        assert layer.remove_rule("does_not_exist") is False


class TestOPAResultParsing:
    def test_boolean_allow_true_yields_no_violations(self) -> None:
        assert _parse_opa_result(True) == []

    def test_boolean_allow_false_yields_a_block(self) -> None:
        violations = _parse_opa_result(False)
        assert len(violations) == 1
        assert violations[0].action is EnforcementAction.BLOCK

    def test_rich_document_is_translated(self) -> None:
        violations = _parse_opa_result(
            {
                "allow": False,
                "violations": [
                    {
                        "rule": "no_phi_egress",
                        "description": "Patient data may not leave the network.",
                        "action": "BLOCK",
                        "matched_on": "tool_name~email",
                        "requires_hitl_token": False,
                    }
                ],
            }
        )
        assert len(violations) == 1
        assert violations[0].rule_name == "no_phi_egress"
        assert violations[0].action is EnforcementAction.BLOCK

    def test_unknown_action_defaults_to_block(self) -> None:
        violations = _parse_opa_result(
            {"allow": False, "violations": [{"rule": "x", "action": "NONSENSE"}]}
        )
        assert violations[0].action is EnforcementAction.BLOCK

    def test_none_result_is_empty(self) -> None:
        assert _parse_opa_result(None) == []
