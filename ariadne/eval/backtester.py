# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Policy backtesting: replay a proposed policy against already-recorded audit data.

This deliberately never touches the live, shared `HardPolicyLayer` /
`SoftDriftLayer` instances (see the NOTE in ariadne/api/policies.py — the
runtime enforcement engine is one shared in-process instance for the whole
deployment, not per-org, and definitely not something a backtest should be
able to perturb). Instead it reimplements a miniature, read-only version of
each layer's matching logic against `Event` rows already sitting in the
database, and never re-runs the agent or re-scores anything live.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ariadne.audit.recorder import AuditRecorder
from ariadne.config import Settings
from ariadne.db.models import Event, Run
from ariadne.logging import get_logger
from ariadne.proxy.schemas import utcnow

logger = get_logger(__name__)

#: Ordering used to compare enforcement actions by severity. Higher is
#: stricter. Mirrors the ALLOW < WARN < ESCALATE < BLOCK ladder in
#: ariadne/enforcement/soft_layer.py.
_SEVERITY: dict[str, int] = {"ALLOW": 0, "WARN": 1, "ESCALATE": 2, "BLOCK": 3}

#: Severity at or above which an action counts as "this would have been
#: caught" for detection-rate / false-positive-rate purposes.
_DETECT_THRESHOLD = _SEVERITY["ESCALATE"]


class BacktestRunFilter(BaseModel):
    date_from: datetime | None = None
    date_to: datetime | None = None
    agent_id: str | None = None
    final_status: list[str] | None = None
    limit: int = 1000


class BacktestRunDiff(BaseModel):
    session_id: str
    agent_name: str | None
    real_decision: str
    proposed_decision: str
    changed_at_step: int
    impact: Literal["incident_prevented", "false_positive_added", "false_negative_added"]


class BacktestReport(BaseModel):
    job_id: str
    organization_id: str
    runs_analyzed: int
    date_range: tuple[datetime, datetime] | None
    baseline_detection_rate: float
    baseline_fpr: float
    baseline_blocks: int
    baseline_escalations: int
    proposed_detection_rate: float
    proposed_fpr: float
    proposed_blocks: int
    proposed_escalations: int
    incidents_prevented_delta: int
    false_positive_delta: int
    detection_rate_delta: float
    fpr_delta: float
    changed_runs: list[BacktestRunDiff]
    recommendation: Literal["DEPLOY", "REVIEW", "DO NOT DEPLOY"]
    recommendation_reason: str
    completed_at: datetime = Field(default_factory=utcnow)


class ProposedPolicy(BaseModel):
    """A minimal policy config for backtesting -- not the full Policy ORM model.

    tool_name_patterns/argument_patterns mirror Policy's JSON shape (see
    ariadne/db/models.py::Policy, which stores them as {"patterns": [...]}
    JSON columns -- here they're plain lists since this model never touches
    that table directly).
    """

    name: str
    action: Literal["ALLOW", "WARN", "ESCALATE", "BLOCK"] = "BLOCK"
    tool_name_patterns: list[str] = Field(default_factory=list)
    argument_patterns: list[str] = Field(default_factory=list)
    drift_warn: float | None = None
    drift_escalate: float | None = None
    drift_block: float | None = None


def _matches_tool_name(tool_name: str, patterns: list[str]) -> str | None:
    """Mirror HardPolicyLayer._evaluate_builtin's substring matching, plus a
    "*" sentinel meaning "match every tool" (used by block-everything
    proposals) -- a plain substring check can't express "match anything"
    without matching the literal character, so it gets a dedicated case.
    """
    tool_lower = tool_name.lower()
    for pattern in patterns:
        if pattern == "*":
            return pattern
        if pattern.lower() in tool_lower:
            return pattern
    return None


def _matches_arguments(payload_json: dict[str, Any], patterns: list[str]) -> str | None:
    """Best-effort argument match against whatever ended up in payload_json.

    Event rows don't store the raw tool-call arguments as a dedicated column
    (see ariadne/db/models.py::Event) -- only payload_json, which may or may
    not carry them depending on what the interceptor recorded. This is an
    approximation of HardPolicyLayer's argument_patterns check, not a byte
    -for-byte replay; documented deviation, not a silent gap.
    """
    if not patterns:
        return None
    blob = str(payload_json).lower()
    for pattern in patterns:
        if pattern.lower() in blob:
            return pattern
    return None


class PolicyBacktester:
    """Replays a proposed policy against stored Run/Event rows for one org."""

    def __init__(self, recorder: AuditRecorder, settings: Settings) -> None:
        self._recorder = recorder
        self._settings = settings

    def _evaluate_event(self, event: Event, proposed_policy: ProposedPolicy) -> str:
        """Return the EnforcementAction (as a str) the proposed policy would
        have produced for this stored event, using only already-recorded data.
        """
        matched_name = _matches_tool_name(event.tool_name, proposed_policy.tool_name_patterns)
        matched_arg = _matches_arguments(event.payload_json, proposed_policy.argument_patterns)
        if matched_name is not None or matched_arg is not None:
            return proposed_policy.action

        risk_dimensions = event.payload_json.get("risk_dimensions") if event.payload_json else None
        risk_aggregate = 0.0
        if isinstance(risk_dimensions, dict):
            candidate = risk_dimensions.get("aggregate")
            if isinstance(candidate, int | float):
                risk_aggregate = float(candidate)
        effective_score = max(event.drift_score or 0.0, risk_aggregate)

        warn = (
            proposed_policy.drift_warn
            if proposed_policy.drift_warn is not None
            else self._settings.drift_score_warn
        )
        escalate = (
            proposed_policy.drift_escalate
            if proposed_policy.drift_escalate is not None
            else self._settings.drift_score_escalate
        )
        block = (
            proposed_policy.drift_block
            if proposed_policy.drift_block is not None
            else self._settings.drift_score_block
        )

        if effective_score >= block:
            return "BLOCK"
        if effective_score >= escalate:
            return "ESCALATE"
        if effective_score >= warn:
            return "WARN"
        return "ALLOW"

    async def run_backtest(
        self,
        job_id: str,
        organization_id: str,
        proposed_policy: ProposedPolicy,
        run_filter: BacktestRunFilter,
    ) -> BacktestReport:
        runs = await self._recorder.list_runs_filtered(
            organization_id=organization_id,
            date_from=run_filter.date_from,
            date_to=run_filter.date_to,
            agent_id=run_filter.agent_id,
            final_status=run_filter.final_status,
            limit=run_filter.limit,
        )

        total_incidents = 0
        total_clean = 0
        real_detected_incidents = 0
        proposed_detected_incidents = 0
        real_fp_clean = 0
        proposed_fp_clean = 0
        real_blocks = 0
        real_escalations = 0
        proposed_blocks = 0
        proposed_escalations = 0
        changed_runs: list[BacktestRunDiff] = []
        started_ats: list[datetime] = []

        for run in runs:
            events = await self._recorder.get_events(run.session_id, organization_id)
            started_ats.append(run.started_at)

            # Ground-truth heuristic (no dedicated label field exists yet --
            # that's Feature 7): a run counts as a real incident if the
            # recorded final_status wasn't CLEAN, or any event along the way
            # tripped a named hard rule (triggered_rule non-null). Everything
            # else counts as a clean run for false-positive-rate purposes.
            is_incident = run.final_status != "CLEAN" or any(
                event.triggered_rule for event in events
            )

            real_severity = 0
            proposed_severity = 0
            first_diff: tuple[int, str, str] | None = None
            for event in events:
                real_action = event.enforcement_action
                proposed_action = self._evaluate_event(event, proposed_policy)
                real_severity = max(real_severity, _SEVERITY.get(real_action, 0))
                proposed_severity = max(proposed_severity, _SEVERITY.get(proposed_action, 0))
                if first_diff is None and proposed_action != real_action:
                    first_diff = (event.step_index, real_action, proposed_action)

            real_detected = real_severity >= _DETECT_THRESHOLD
            proposed_detected = proposed_severity >= _DETECT_THRESHOLD

            if is_incident:
                total_incidents += 1
                real_detected_incidents += int(real_detected)
                proposed_detected_incidents += int(proposed_detected)
            else:
                total_clean += 1
                real_fp_clean += int(real_detected)
                proposed_fp_clean += int(proposed_detected)

            if real_severity == _SEVERITY["BLOCK"]:
                real_blocks += 1
            elif real_severity == _SEVERITY["ESCALATE"]:
                real_escalations += 1
            if proposed_severity == _SEVERITY["BLOCK"]:
                proposed_blocks += 1
            elif proposed_severity == _SEVERITY["ESCALATE"]:
                proposed_escalations += 1

            if first_diff is not None:
                step_index, real_decision, proposed_decision = first_diff
                impact: Literal[
                    "incident_prevented", "false_positive_added", "false_negative_added"
                ] | None = None
                if is_incident and proposed_detected and not real_detected:
                    impact = "incident_prevented"
                elif not is_incident and proposed_detected and not real_detected:
                    impact = "false_positive_added"
                elif is_incident and real_detected and not proposed_detected:
                    impact = "false_negative_added"
                if impact is not None:
                    changed_runs.append(
                        BacktestRunDiff(
                            session_id=run.session_id,
                            agent_name=run.agent_id,
                            real_decision=real_decision,
                            proposed_decision=proposed_decision,
                            changed_at_step=step_index,
                            impact=impact,
                        )
                    )

        baseline_detection_rate = (
            real_detected_incidents / total_incidents if total_incidents else 0.0
        )
        baseline_fpr = real_fp_clean / total_clean if total_clean else 0.0
        proposed_detection_rate = (
            proposed_detected_incidents / total_incidents if total_incidents else 0.0
        )
        proposed_fpr = proposed_fp_clean / total_clean if total_clean else 0.0

        detection_rate_delta = proposed_detection_rate - baseline_detection_rate
        fpr_delta = proposed_fpr - baseline_fpr

        if detection_rate_delta >= 0 and fpr_delta <= 0:
            recommendation: Literal["DEPLOY", "REVIEW", "DO NOT DEPLOY"] = "DEPLOY"
            recommendation_reason = (
                "Detection rate did not drop and the false-positive rate did not rise."
            )
        elif detection_rate_delta <= 0:
            recommendation = "DO NOT DEPLOY"
            recommendation_reason = (
                f"Detection rate would fall by {abs(detection_rate_delta):.1%}."
            )
        else:
            recommendation = "REVIEW"
            recommendation_reason = (
                f"Detection rate improves by {detection_rate_delta:.1%} but the "
                f"false-positive rate also rises by {fpr_delta:.1%} -- a human tradeoff call."
            )

        logger.info(
            "eval.backtest_completed",
            job_id=job_id,
            organization_id=organization_id,
            runs_analyzed=len(runs),
            recommendation=recommendation,
        )

        return BacktestReport(
            job_id=job_id,
            organization_id=organization_id,
            runs_analyzed=len(runs),
            date_range=(min(started_ats), max(started_ats)) if started_ats else None,
            baseline_detection_rate=baseline_detection_rate,
            baseline_fpr=baseline_fpr,
            baseline_blocks=real_blocks,
            baseline_escalations=real_escalations,
            proposed_detection_rate=proposed_detection_rate,
            proposed_fpr=proposed_fpr,
            proposed_blocks=proposed_blocks,
            proposed_escalations=proposed_escalations,
            incidents_prevented_delta=proposed_detected_incidents - real_detected_incidents,
            false_positive_delta=proposed_fp_clean - real_fp_clean,
            detection_rate_delta=detection_rate_delta,
            fpr_delta=fpr_delta,
            changed_runs=changed_runs,
            recommendation=recommendation,
            recommendation_reason=recommendation_reason,
        )

    async def simulate_run(
        self, session_id: str, organization_id: str, proposed_policy: ProposedPolicy
    ) -> dict[str, Any]:
        """Synchronous single-run replay -- no job queue, this is fast enough
        to answer inline (used by POST /api/v1/eval/simulate-run/{session_id}).
        """
        run: Run | None = await self._recorder.get_run(session_id, organization_id)
        if run is None:
            return {
                "session_id": session_id,
                "found": False,
                "would_be_prevented": False,
                "prevented_at_step": None,
                "real_max_action": None,
                "proposed_max_action": None,
            }

        events = await self._recorder.get_events(session_id, organization_id)
        real_severity = 0
        proposed_severity = 0
        prevented_at_step: int | None = None
        real_max_action = "ALLOW"
        proposed_max_action = "ALLOW"
        for event in events:
            real_action = event.enforcement_action
            proposed_action = self._evaluate_event(event, proposed_policy)
            if _SEVERITY.get(real_action, 0) >= real_severity:
                real_severity = _SEVERITY.get(real_action, 0)
                real_max_action = real_action
            if _SEVERITY.get(proposed_action, 0) >= proposed_severity:
                proposed_severity = _SEVERITY.get(proposed_action, 0)
                proposed_max_action = proposed_action
            if (
                prevented_at_step is None
                and proposed_severity >= _DETECT_THRESHOLD
                and real_severity < _DETECT_THRESHOLD
            ):
                prevented_at_step = event.step_index

        return {
            "session_id": session_id,
            "found": True,
            "would_be_prevented": prevented_at_step is not None,
            "prevented_at_step": prevented_at_step,
            "real_max_action": real_max_action,
            "proposed_max_action": proposed_max_action,
        }
