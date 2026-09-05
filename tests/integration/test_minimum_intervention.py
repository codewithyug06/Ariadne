# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Feature 11: Minimum Intervention Finder.

Follows the same synthetic-data fixture pattern as
tests/integration/test_backtester.py -- Run + Event rows are inserted
directly, bypassing the live interception pipeline, since the finder must
only ever read stored data.
"""

from __future__ import annotations

import uuid

import pytest

from ariadne.db.models import LEGACY_ORG_ID, Event, Run
from tests.integration.conftest import Stack


async def _seed_run(
    stack: Stack,
    *,
    session_id: str,
    final_status: str,
    events: list[dict[str, object]],
    organization_id: str = LEGACY_ORG_ID,
) -> None:
    database = stack.app.state.database
    async with database.session() as session:
        session.add(
            Run(
                session_id=session_id,
                organization_id=organization_id,
                total_steps=len(events),
                final_status=final_status,
                max_drift_score=max((e.get("drift_score") or 0.0) for e in events)
                if events
                else 0.0,
            )
        )
        for index, event in enumerate(events):
            session.add(
                Event(
                    event_id=f"{session_id}-evt-{index}",
                    organization_id=organization_id,
                    session_id=session_id,
                    step_index=index,
                    tool_name=str(event["tool_name"]),
                    enforcement_action=str(event["enforcement_action"]),
                    triggered_rule=event.get("triggered_rule"),  # type: ignore[arg-type]
                    drift_score=event.get("drift_score"),  # type: ignore[arg-type]
                    payload_json=event.get("payload_json", {}),  # type: ignore[arg-type]
                )
            )


async def _seed_incident(
    stack: Stack, organization_id: str = LEGACY_ORG_ID, *, trigger: str | None = None
) -> str:
    """A 4-step session that ends BLOCKed at step 3 with a high drift score.

    Steps 0-2 are ALLOW at moderate drift; step 3 is the real BLOCK, at
    drift 92, optionally carrying a narrative trigger (payload_json ->
    "narrative" -> "trigger", matching ariadne/audit/schemas.py's storage
    convention).
    """
    session_id = f"incident-{uuid.uuid4().hex[:8]}"
    block_payload: dict[str, object] = {}
    if trigger is not None:
        block_payload["narrative"] = {"trigger": trigger}
    await _seed_run(
        stack,
        session_id=session_id,
        final_status="BLOCKED",
        events=[
            {"tool_name": "read_file", "enforcement_action": "ALLOW", "drift_score": 20.0},
            {"tool_name": "list_files", "enforcement_action": "ALLOW", "drift_score": 40.0},
            {"tool_name": "write_file", "enforcement_action": "WARN", "drift_score": 60.0},
            {
                "tool_name": "delete_all_production_databases",
                "enforcement_action": "BLOCK",
                "triggered_rule": "no_privilege_escalation",
                "drift_score": 92.0,
                "payload_json": block_payload,
            },
        ],
        organization_id=organization_id,
    )
    return session_id


async def _seed_clean_runs(
    stack: Stack, count: int, organization_id: str = LEGACY_ORG_ID
) -> None:
    for i in range(count):
        session_id = f"clean-{uuid.uuid4().hex[:8]}-{i}"
        await _seed_run(
            stack,
            session_id=session_id,
            final_status="CLEAN",
            events=[
                {"tool_name": "read_file", "enforcement_action": "ALLOW", "drift_score": 15.0},
                {"tool_name": "list_files", "enforcement_action": "ALLOW", "drift_score": 18.0},
            ],
            organization_id=organization_id,
        )


class TestMinimumInterventionFinder:
    async def test_ranks_known_candidates_by_disruption_score(self, stack: Stack) -> None:
        session_id = await _seed_incident(stack)
        await _seed_clean_runs(stack, 3)

        # early-block: catches at step 0 (drift_block below 20) -> earliest,
        #   0 false positives on clean sample (clean drift caps at 18).
        # late-block: catches at step 3 only (drift_block just below 92) ->
        #   late, 0 false positives.
        # noisy-block: catches at step 0 but ALSO blocks every clean run
        #   (drift_block below 15) -> earliest but costly false positives.
        response = await stack.client.post(
            "/api/v1/eval/minimum-intervention",
            json={
                "incident_session_id": session_id,
                "candidate_policies": [
                    {"name": "early-block", "drift_block": 19.0},
                    {"name": "late-block", "drift_block": 91.0},
                    {"name": "noisy-block", "drift_block": 10.0},
                ],
                "clean_run_sample_size": 200,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()

        by_name = {c["policy_name"]: c for c in body["candidates"]}
        assert by_name["early-block"]["prevented"] is True
        assert by_name["early-block"]["prevented_at_step"] == 0
        assert by_name["early-block"]["new_false_positives_on_clean_sample"] == 0
        assert by_name["late-block"]["prevented_at_step"] == 3
        assert by_name["noisy-block"]["new_false_positives_on_clean_sample"] == 3

        # early-block should win: earliest and no false positives.
        assert body["recommended"]["policy_name"] == "early-block"
        assert by_name["early-block"]["disruption_score"] < by_name["late-block"]["disruption_score"]
        assert by_name["early-block"]["disruption_score"] < by_name["noisy-block"]["disruption_score"]

    async def test_non_preventing_candidate_excluded_from_recommendation(
        self, stack: Stack
    ) -> None:
        session_id = await _seed_incident(stack)

        response = await stack.client.post(
            "/api/v1/eval/minimum-intervention",
            json={
                "incident_session_id": session_id,
                "candidate_policies": [
                    {"name": "too-loose", "drift_block": 200.0},
                    {"name": "works", "drift_block": 50.0},
                ],
                "clean_run_sample_size": 0,
            },
        )
        assert response.status_code == 200
        body = response.json()
        by_name = {c["policy_name"]: c for c in body["candidates"]}

        assert by_name["too-loose"]["prevented"] is False
        assert by_name["too-loose"]["prevented_at_step"] is None
        # still present in the full candidate list
        assert "too-loose" in by_name
        assert body["recommended"]["policy_name"] == "works"

    async def test_no_candidate_prevents_incident(self, stack: Stack) -> None:
        session_id = await _seed_incident(stack)

        response = await stack.client.post(
            "/api/v1/eval/minimum-intervention",
            json={
                "incident_session_id": session_id,
                "candidate_policies": [
                    {"name": "way-too-loose-1", "drift_block": 200.0},
                    {"name": "way-too-loose-2", "drift_block": 300.0},
                ],
                "clean_run_sample_size": 0,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["recommended"] is None
        assert "No candidate" in body["recommendation_reason"]
        assert body["recommendation_reason"]  # non-empty, specific

    async def test_recommendation_reason_references_step_and_fp_count(
        self, stack: Stack
    ) -> None:
        session_id = await _seed_incident(stack)
        await _seed_clean_runs(stack, 2)

        response = await stack.client.post(
            "/api/v1/eval/minimum-intervention",
            json={
                "incident_session_id": session_id,
                "candidate_policies": [{"name": "winner", "drift_block": 19.0}],
                "clean_run_sample_size": 200,
            },
        )
        body = response.json()
        recommended = body["recommended"]
        assert recommended is not None
        reason = body["recommendation_reason"]
        assert recommended["policy_name"] in reason
        assert str(recommended["prevented_at_step"]) in reason
        assert str(recommended["new_false_positives_on_clean_sample"]) in reason

    async def test_auto_generated_candidates_include_root_cause(self, stack: Stack) -> None:
        session_id = await _seed_incident(stack, trigger="privilege escalation attempt")

        response = await stack.client.post(
            "/api/v1/eval/minimum-intervention",
            json={"incident_session_id": session_id, "clean_run_sample_size": 0},
        )
        assert response.status_code == 200
        body = response.json()
        names = [c["policy_name"] for c in body["candidates"]]
        # 3 block thresholds + 3 escalate thresholds + 1 root-cause-specific
        assert len(names) == 7
        assert "root-cause-privilege-escalation" in names

    async def test_auto_generated_candidates_without_root_cause_match(
        self, stack: Stack
    ) -> None:
        session_id = await _seed_incident(stack, trigger=None)

        response = await stack.client.post(
            "/api/v1/eval/minimum-intervention",
            json={"incident_session_id": session_id, "clean_run_sample_size": 0},
        )
        assert response.status_code == 200
        body = response.json()
        # 3 block thresholds + 3 escalate thresholds, no root-cause candidate
        assert len(body["candidates"]) == 6

    async def test_zero_clean_sample_skips_false_positive_check(self, stack: Stack) -> None:
        session_id = await _seed_incident(stack)
        await _seed_clean_runs(stack, 5)

        response = await stack.client.post(
            "/api/v1/eval/minimum-intervention",
            json={
                "incident_session_id": session_id,
                "candidate_policies": [
                    {"name": "would-be-noisy", "drift_block": 1.0},
                ],
                "clean_run_sample_size": 0,
            },
        )
        assert response.status_code == 200
        body = response.json()
        for candidate in body["candidates"]:
            assert candidate["new_false_positives_on_clean_sample"] == 0

    async def test_cross_org_incident_returns_404(self, stack: Stack) -> None:
        other_org = uuid.uuid4().hex
        session_id = await _seed_incident(stack, organization_id=other_org)

        response = await stack.client.post(
            "/api/v1/eval/minimum-intervention",
            json={"incident_session_id": session_id, "clean_run_sample_size": 0},
        )
        assert response.status_code == 404

    async def test_unknown_session_id_returns_404(self, stack: Stack) -> None:
        response = await stack.client.post(
            "/api/v1/eval/minimum-intervention",
            json={"incident_session_id": "does-not-exist", "clean_run_sample_size": 0},
        )
        assert response.status_code == 404
