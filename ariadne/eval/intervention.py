# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Feature 11: Minimum Intervention Finder.

Given one specific incident (a session that ended in BLOCK), this searches a
small set of candidate intervention policies and finds the one that would
have prevented the incident earliest with the fewest side effects, measured
against a control sample of clean/known-good runs.

Same constraint as Feature 5A's ``PolicyBacktester``: this is a *replay*
engine, not a simulation engine. It never re-runs the agent and never
touches the live shared ``HardPolicyLayer``/``SoftDriftLayer`` instances --
it only re-evaluates already-recorded ``Event`` rows against candidate
policies using ``PolicyBacktester``'s own per-event replay logic
(``_evaluate_event``), which is reused directly rather than reimplemented a
second time. This module lives alongside ``backtester.py`` (a sibling file,
per the task spec's stated preference) precisely so both can share that one
implementation of "what would this policy have done to this event".
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ariadne.audit.recorder import AuditRecorder
from ariadne.config import Settings
from ariadne.db.models import Event
from ariadne.eval.backtester import PolicyBacktester, ProposedPolicy, _SEVERITY
from ariadne.logging import get_logger

logger = get_logger(__name__)

#: Severity threshold for "this policy would have blocked".
_BLOCK_SEVERITY = _SEVERITY["BLOCK"]


class IncidentNotFoundError(Exception):
    """Raised when the requested incident session does not exist in this org.

    Mapped to HTTP 404 by the API route. Unlike Feature 5A's bulk
    ``/backtest`` route -- which treats a cross-org (or empty) run_filter as
    "zero runs analyzed" because it operates on a *collection* the caller may
    legitimately not own any of -- this endpoint addresses exactly ONE named
    resource (`incident_session_id`). A single-resource lookup that silently
    returns an empty/zero report when the resource belongs to another org
    would be a worse API: the caller asked "how do I fix incident X" and a
    zero-candidate report reads as "there is no fix" rather than "you don't
    have access to X" or "X doesn't exist". So this module raises a distinct
    exception the route translates to 404, deliberately diverging from
    Feature 5A's bulk-query choice because the access pattern is different
    (single resource vs. bulk filter), even though both live in the eval
    package.
    """


class InterventionCandidateResult(BaseModel):
    policy_name: str
    prevented: bool
    prevented_at_step: int | None
    new_false_positives_on_clean_sample: int
    disruption_score: float  # lower = better


class MinimumInterventionReport(BaseModel):
    incident_session_id: str
    candidates: list[InterventionCandidateResult]
    recommended: InterventionCandidateResult | None
    recommendation_reason: str


class MinimumInterventionFinder:
    """Searches candidate intervention policies for one incident session.

    Reuses ``PolicyBacktester._evaluate_event`` for per-event replay -- see
    module docstring. Never re-runs the agent, never touches the live shared
    enforcement layers.
    """

    def __init__(self, recorder: AuditRecorder, settings: Settings) -> None:
        self._recorder = recorder
        self._settings = settings
        # Reused purely for its _evaluate_event replay logic (and its
        # settings-aware threshold fallback) -- run_backtest/simulate_run are
        # not called from here.
        self._backtester = PolicyBacktester(recorder, settings)

    async def find_minimum_intervention(
        self,
        organization_id: str,
        incident_session_id: str,
        candidate_policies: list[ProposedPolicy] | None = None,
        clean_run_sample_size: int = 200,
    ) -> MinimumInterventionReport:
        incident_run = await self._recorder.get_run(incident_session_id, organization_id)
        if incident_run is None:
            raise IncidentNotFoundError(
                f"session {incident_session_id!r} not found in organization {organization_id!r}"
            )
        incident_events = await self._recorder.get_events(incident_session_id, organization_id)

        clean_sample: list[list[Event]] = []
        if clean_run_sample_size > 0:
            clean_runs = await self._recorder.list_runs_filtered(
                organization_id=organization_id,
                final_status=["CLEAN", "ALLOW", "ALLOWED"],
                limit=clean_run_sample_size,
            )
            for run in clean_runs:
                clean_sample.append(await self._recorder.get_events(run.session_id, organization_id))

        if candidate_policies is None:
            candidate_policies = self._auto_generate_candidates(incident_events)

        results: list[InterventionCandidateResult] = []
        for policy in candidate_policies:
            prevented_at = self._earliest_block_step(incident_events, policy)
            fp_count = (
                self._count_new_false_positives(clean_sample, policy)
                if clean_run_sample_size > 0
                else 0
            )
            disruption = self._disruption_score(prevented_at, fp_count, incident_events)
            results.append(
                InterventionCandidateResult(
                    policy_name=policy.name,
                    prevented=prevented_at is not None,
                    prevented_at_step=prevented_at,
                    new_false_positives_on_clean_sample=fp_count,
                    disruption_score=disruption,
                )
            )

        ranked = sorted((r for r in results if r.prevented), key=lambda r: r.disruption_score)
        recommended = ranked[0] if ranked else None

        logger.info(
            "eval.minimum_intervention_completed",
            organization_id=organization_id,
            incident_session_id=incident_session_id,
            candidate_count=len(results),
            recommended=recommended.policy_name if recommended else None,
        )

        return MinimumInterventionReport(
            incident_session_id=incident_session_id,
            candidates=results,
            recommended=recommended,
            recommendation_reason=self._explain(ranked, incident_events),
        )

    def _earliest_block_step(
        self, incident_events: list[Event], policy: ProposedPolicy
    ) -> int | None:
        """First step index at which `policy` would have produced BLOCK.

        Mirrors PolicyBacktester.simulate_run's prevented_at_step logic, but
        keyed only off the proposed policy's own severity (this module cares
        about "would this policy alone have blocked it", not a real-vs-
        proposed diff), and reuses the same underlying per-event evaluator.
        """
        for event in incident_events:
            action = self._backtester._evaluate_event(event, policy)  # noqa: SLF001 - shared replay logic, see module docstring
            if _SEVERITY.get(action, 0) >= _BLOCK_SEVERITY:
                return event.step_index
        return None

    def _count_new_false_positives(
        self, clean_sample: list[list[Event]], policy: ProposedPolicy
    ) -> int:
        """Count clean runs where `policy` would have produced a BLOCK.

        Every run in `clean_sample` is, by construction (final_status
        indicating a clean/ALLOW outcome), a run that was NOT blocked in
        reality -- so any BLOCK the candidate policy would introduce here is
        a new false positive, not a re-detection of a real incident.
        """
        fp_count = 0
        for events in clean_sample:
            for event in events:
                action = self._backtester._evaluate_event(event, policy)  # noqa: SLF001
                if _SEVERITY.get(action, 0) >= _BLOCK_SEVERITY:
                    fp_count += 1
                    break
        return fp_count

    def _disruption_score(
        self, prevented_at: int | None, fp_count: int, events: list[Event]
    ) -> float:
        """Lower is better.

        - Lateness penalty: (prevented_at / total_steps) * 50 when prevented
          -- earlier prevention is cheaper. When NOT prevented the policy is
          filtered out of ranking entirely (see find_minimum_intervention),
          so this branch's value is never compared against a "prevented"
          candidate's score; it is still given a defined, documented value
          (the max lateness penalty, 100) purely so the field is always a
          concrete float rather than None, which keeps
          InterventionCandidateResult.disruption_score total and easy to
          sort/display even for excluded candidates.
        - False positive cost: fp_count * 10.
        - Sum, capped at 100.
        """
        total_steps = len(events) or 1
        if prevented_at is None:
            lateness_penalty = 100.0
        else:
            lateness_penalty = (prevented_at / total_steps) * 50.0
        fp_cost = fp_count * 10.0
        return min(lateness_penalty + fp_cost, 100.0)

    def _auto_generate_candidates(self, incident_events: list[Event]) -> list[ProposedPolicy]:
        """3 tighter BLOCK thresholds + 3 tighter ESCALATE thresholds + up to
        a handful of root-cause-specific candidates derived from the
        incident's own BLOCK event narrative trigger.

        "Current" thresholds are pulled from the org's live Settings
        drift_block/drift_escalate, matching Feature 5A's own fallback
        logic in PolicyBacktester._evaluate_event (a proposed policy with no
        explicit drift_block/drift_escalate falls back to these same
        settings values).
        """
        current_block = self._settings.drift_score_block
        current_escalate = self._settings.drift_score_escalate

        candidates: list[ProposedPolicy] = []
        for delta in (5.0, 10.0, 15.0):
            candidates.append(
                ProposedPolicy(name=f"tighter-block-minus-{int(delta)}", drift_block=current_block - delta)
            )
        for delta in (5.0, 10.0, 15.0):
            candidates.append(
                ProposedPolicy(
                    name=f"tighter-escalate-minus-{int(delta)}",
                    drift_escalate=current_escalate - delta,
                )
            )

        trigger = self._root_cause_trigger(incident_events)
        if trigger is not None:
            trigger_lower = trigger.lower()
            if "privilege escalation" in trigger_lower:
                # ProposedPolicy has no native "edge type" concept (it only
                # knows tool_name_patterns/argument_patterns -- see
                # backtester.py::ProposedPolicy docstring), so a root-cause
                # candidate targeting a *signal* like "privilege escalation"
                # is approximated via argument_patterns: _matches_arguments
                # substring-matches against str(event.payload_json).lower(),
                # and the drift narrative (including its `trigger` string) is
                # itself stored inside payload_json under the "narrative" key
                # (see ariadne/audit/schemas.py). So a pattern of
                # "privilege escalation" will match any event whose stored
                # narrative trigger names that signal -- a documented
                # approximation, not a byte-exact replay of a dedicated
                # "edge type" concept the schema doesn't have.
                candidates.append(
                    ProposedPolicy(
                        name="root-cause-privilege-escalation",
                        action="BLOCK",
                        argument_patterns=["privilege escalation"],
                    )
                )
            if "untrusted" in trigger_lower or "external tool result" in trigger_lower:
                candidates.append(
                    ProposedPolicy(
                        name="root-cause-untrusted-external-result",
                        action="BLOCK",
                        argument_patterns=["untrusted"],
                    )
                )

        return candidates

    def _root_cause_trigger(self, incident_events: list[Event]) -> str | None:
        """Return the `narrative.trigger` string from this incident's BLOCK
        event, if any -- used to auto-generate a root-cause-specific
        candidate. Returns None if no BLOCK event or no trigger recorded.
        """
        for event in incident_events:
            if event.enforcement_action != "BLOCK":
                continue
            payload = event.payload_json or {}
            narrative = payload.get("narrative")
            if isinstance(narrative, dict):
                trigger = narrative.get("trigger")
                if isinstance(trigger, str) and trigger:
                    return trigger
        return None

    def _explain(
        self,
        ranked: list[InterventionCandidateResult],
        incident_events: list[Event],
    ) -> str:
        """Reference the specific step/fp_count of the recommendation, or
        give a clear, specific "nothing worked" explanation when empty.
        """
        if not ranked:
            return (
                "No candidate intervention policy would have prevented this incident: "
                "every candidate evaluated allowed it through to the recorded outcome. "
                "Consider a more targeted hard rule for this incident's root cause, or "
                "widening the candidate sweep."
            )

        winner = ranked[0]
        real_block_step = next(
            (event.step_index for event in incident_events if event.enforcement_action == "BLOCK"),
            None,
        )
        real_step_clause = (
            f"vs step {real_block_step} in the real recorded outcome"
            if real_block_step is not None
            else "vs no block in the real recorded outcome"
        )
        return (
            f"Policy '{winner.policy_name}' prevents the incident at step "
            f"{winner.prevented_at_step} ({real_step_clause}) with "
            f"{winner.new_false_positives_on_clean_sample} new false positives "
            f"across the clean sample."
        )
