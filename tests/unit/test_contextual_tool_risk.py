# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Feature 10: contextual tool-risk scoring."""

from __future__ import annotations

from ariadne.config import Settings
from ariadne.enforcement.contextual_tool_risk import ContextualToolRiskScorer
from ariadne.proxy.schemas import ToolCall


def make_call(
    tool_name: str,
    arguments: dict[str, object] | None = None,
    session_id: str = "sess-1",
    step_index: int = 1,
) -> ToolCall:
    return ToolCall(
        session_id=session_id,
        step_index=step_index,
        tool_name=tool_name,
        arguments=arguments or {},
    )


class TestArgumentContextVsNameOnly:
    def test_prod_path_argument_scores_higher_than_a_harmless_delete(self) -> None:
        scorer = ContextualToolRiskScorer()
        low = scorer.score(
            make_call("delete_draft_comment", {"comment_id": "c-123"}), [], {}
        )
        high = scorer.score(
            make_call("delete_production_database", {"target": "/prod/db-01"}), [], {}
        )
        assert high.value > low.value


class TestEmailDomainContext:
    def test_external_domain_scores_higher_than_internal_domain(self) -> None:
        scorer = ContextualToolRiskScorer()
        internal = scorer.score(
            make_call("send_email", {"to": "alice@corp.com"}), [], {}
        )
        external = scorer.score(
            make_call("send_email", {"to": "alice@totally-unknown-domain.biz"}), [], {}
        )
        assert external.value > internal.value
        assert external.argument_modifier > internal.argument_modifier


class TestNovelty:
    def test_first_use_of_high_risk_tool_scores_higher_than_with_prior_history(self) -> None:
        scorer = ContextualToolRiskScorer()
        call = make_call("delete_production_database", {}, step_index=3)

        first_use = scorer.score(call, [], {})

        history = [
            make_call("delete_production_database", {}, step_index=1),
            make_call("delete_production_database", {}, step_index=2),
        ]
        with_history = scorer.score(call, history, {})

        assert first_use.value > with_history.value
        assert first_use.novelty_modifier > with_history.novelty_modifier

    def test_rapid_repetition_within_last_ten_steps_applies_modifier(self) -> None:
        scorer = ContextualToolRiskScorer()
        history = [
            make_call("read_file", {"path": f"/tmp/{i}.txt"}, step_index=i)
            for i in range(1, 7)  # 6 prior calls to the same tool
        ]
        call = make_call("read_file", {"path": "/tmp/7.txt"}, step_index=7)

        result = scorer.score(call, history, {})

        assert result.novelty_modifier == 15.0
        assert "rapid" in result.explanation.lower()

    def test_no_repetition_below_threshold_applies_no_rapid_modifier(self) -> None:
        scorer = ContextualToolRiskScorer()
        history = [
            make_call("read_file", {"path": f"/tmp/{i}.txt"}, step_index=i)
            for i in range(1, 4)  # only 3 prior calls -- below the >5 threshold
        ]
        call = make_call("read_file", {"path": "/tmp/4.txt"}, step_index=4)

        result = scorer.score(call, history, {})

        assert result.novelty_modifier == 0.0


class TestOrgOverrideAlwaysWins:
    def test_override_ignores_conflicting_argument_signals(self) -> None:
        scorer = ContextualToolRiskScorer()
        # This call would otherwise score very high: prod-path argument,
        # credential-shaped key, and a fresh first-use novelty bonus.
        call = make_call(
            "delete_production_database",
            {"target": "/prod/db-01", "api_key": "sk-live-abc"},
        )
        result = scorer.score(call, [], {"delete_production_database": 5.0})

        assert result.value == 5.0
        assert result.base_risk == 5.0
        assert result.argument_modifier == 0.0
        assert result.novelty_modifier == 0.0
        assert "override" in result.explanation.lower()

    def test_override_wins_even_with_history_and_low_pin(self) -> None:
        scorer = ContextualToolRiskScorer()
        history = [make_call("send_email", {"to": "x@y.com"}, step_index=i) for i in range(1, 8)]
        call = make_call("send_email", {"to": "attacker@evil.biz"}, step_index=8)
        result = scorer.score(call, history, {"send_email": 1.0})
        assert result.value == 1.0


class TestExplanationNonEmpty:
    def test_explanation_always_non_empty_and_references_trigger(self) -> None:
        scorer = ContextualToolRiskScorer()

        prod_result = scorer.score(
            make_call("delete_production_database", {"target": "/prod/x"}), [], {}
        )
        assert prod_result.explanation
        assert "production" in prod_result.explanation.lower()

        override_result = scorer.score(make_call("some_tool"), [], {"some_tool": 42.0})
        assert override_result.explanation
        assert "override" in override_result.explanation.lower()

        rapid_history = [make_call("noop", step_index=i) for i in range(1, 7)]
        rapid_result = scorer.score(make_call("noop", step_index=7), rapid_history, {})
        assert rapid_result.explanation
        assert "rapid" in rapid_result.explanation.lower()

        first_use_result = scorer.score(make_call("delete_all_backups"), [], {})
        assert first_use_result.explanation
        assert "first use" in first_use_result.explanation.lower()

    def test_clean_call_still_gets_a_non_empty_explanation(self) -> None:
        scorer = ContextualToolRiskScorer()
        history = [make_call("list_files", step_index=i) for i in range(1, 3)]
        result = scorer.score(make_call("list_files", step_index=3), history, {})
        assert result.explanation


class TestArgumentModifierCap:
    def test_multiple_simultaneous_triggers_are_capped_at_fifty(self) -> None:
        scorer = ContextualToolRiskScorer(Settings(_env_file=None, LARGE_TRANSACTION_THRESHOLD=100.0))
        call = make_call(
            "process_transfer",
            {
                "to": "someone@totally-unknown-domain.biz",
                "callback_url": "http://not-safe.example",
                "path": "/prod/live/ledger",
                "api_key": "sk-live-abc",
                "amount": 999999,
            },
        )
        result = scorer.score(call, [], {})
        assert result.argument_modifier == 50.0
