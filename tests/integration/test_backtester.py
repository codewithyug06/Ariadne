# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Feature 5A: policy backtesting engine.

Deliberately runs with REDIS_URL unset throughout -- the whole point of the
feature is that it degrades gracefully to in-process execution, and this
suite is what proves that path, not the arq/Redis one (which needs a real
broker and isn't exercised here).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import pytest

from ariadne.db.models import LEGACY_ORG_ID, Event, Run
from tests.integration.conftest import Stack


def test_redis_url_is_unset_for_this_suite() -> None:
    assert os.environ.get("REDIS_URL") is None


async def _await_report(stack: Stack, job_id: str) -> dict[str, Any]:
    """The in-process job runs on an asyncio.create_task the POST route
    schedules but does not await -- give the event loop a few turns to let it
    finish before reading the report, same as the underlying AuditRecorder
    drain queue tests do with recorder.flush().
    """
    for _ in range(50):
        status = await stack.client.get(f"/api/v1/eval/backtest/{job_id}")
        if status.json()["status"] == "complete":
            break
        await asyncio.sleep(0.02)
    response = await stack.client.get(f"/api/v1/eval/backtest/{job_id}/report")
    assert response.status_code == 200, response.text
    return dict(response.json())


async def _seed_run(
    stack: Stack,
    *,
    session_id: str,
    final_status: str,
    events: list[dict[str, object]],
    organization_id: str = LEGACY_ORG_ID,
) -> None:
    """Insert a Run + its Events directly, bypassing the live interception
    pipeline entirely -- the backtester must only ever read stored data, so
    seeding it this way is a more direct test of that contract than driving
    the full MCP handshake would be.
    """
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


async def _seed_synthetic_data(stack: Stack, organization_id: str = LEGACY_ORG_ID) -> dict[str, str]:
    """3 real incidents (high drift, BLOCK, a triggered_rule) + 2 clean runs
    (ALLOW, low drift). Ground-truth signal used: final_status != "CLEAN" OR
    any event.triggered_rule is non-null (documented in backtester.py).
    """
    ids: dict[str, str] = {}

    for i in range(3):
        session_id = f"backtest-incident-{i}-{uuid.uuid4().hex[:8]}"
        await _seed_run(
            stack,
            session_id=session_id,
            final_status="BLOCKED",
            events=[
                {
                    "tool_name": "read_file",
                    "enforcement_action": "ALLOW",
                    "drift_score": 10.0,
                },
                {
                    "tool_name": "delete_all_production_databases",
                    "enforcement_action": "BLOCK",
                    "triggered_rule": "no_privilege_escalation",
                    "drift_score": 92.0,
                },
            ],
            organization_id=organization_id,
        )
        ids[f"incident_{i}"] = session_id

    for i in range(2):
        session_id = f"backtest-clean-{i}-{uuid.uuid4().hex[:8]}"
        await _seed_run(
            stack,
            session_id=session_id,
            final_status="CLEAN",
            events=[
                {
                    "tool_name": "read_file",
                    "enforcement_action": "ALLOW",
                    "drift_score": 12.0,
                },
                {
                    "tool_name": "list_files",
                    "enforcement_action": "ALLOW",
                    "drift_score": 15.0,
                },
            ],
            organization_id=organization_id,
        )
        ids[f"clean_{i}"] = session_id

    return ids


async def _seed_missed_detection_incidents(stack: Stack) -> None:
    """3 real incidents (ground-truthed via final_status="BLOCKED") whose
    stored per-event decisions never actually reached ESCALATE/BLOCK -- the
    original live policy missed them (recorded a WARN at drift 60, below the
    default escalate threshold of 66.5). A tighter proposed drift_block can
    then genuinely *prevent* something the baseline missed, which the
    already-caught fixture in _seed_synthetic_data cannot demonstrate (its
    incidents are already BLOCKed at drift 92, so no threshold change can
    improve on them).
    """
    for i in range(3):
        session_id = f"backtest-missed-{i}-{uuid.uuid4().hex[:8]}"
        await _seed_run(
            stack,
            session_id=session_id,
            final_status="BLOCKED",
            events=[
                {"tool_name": "read_file", "enforcement_action": "ALLOW", "drift_score": 10.0},
                {
                    "tool_name": "suspicious_action",
                    "enforcement_action": "WARN",
                    "drift_score": 60.0,
                },
            ],
        )
    for i in range(2):
        session_id = f"backtest-missed-clean-{i}-{uuid.uuid4().hex[:8]}"
        await _seed_run(
            stack,
            session_id=session_id,
            final_status="CLEAN",
            events=[
                {"tool_name": "read_file", "enforcement_action": "ALLOW", "drift_score": 10.0},
                {"tool_name": "list_files", "enforcement_action": "ALLOW", "drift_score": 12.0},
            ],
        )


class TestBacktester:
    async def test_tighter_threshold_prevents_more_incidents(self, stack: Stack) -> None:
        await _seed_missed_detection_incidents(stack)

        response = await stack.client.post(
            "/api/v1/eval/backtest",
            json={
                "proposed_policy": {"name": "tighter", "drift_block": 50.0},
                "run_filter": {},
            },
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]

        report = await _await_report(stack, job_id)
        # Baseline recorded only a WARN (drift 60 < default escalate 66.5) for
        # each incident -- undetected. A drift_block of 50 pushes that same
        # drift 60 into BLOCK, so the proposed policy catches what the
        # baseline missed.
        assert report["incidents_prevented_delta"] > 0
        assert report["runs_analyzed"] == 5

    async def test_looser_threshold_does_not_increase_false_positives(
        self, stack: Stack
    ) -> None:
        await _seed_synthetic_data(stack)

        response = await stack.client.post(
            "/api/v1/eval/backtest",
            json={
                "proposed_policy": {"name": "looser", "drift_block": 200.0, "drift_escalate": 150.0},
                "run_filter": {},
            },
        )
        job_id = response.json()["job_id"]
        report = await _await_report(stack, job_id)
        assert report["fpr_delta"] <= 0

    async def test_block_everything_policy_is_not_recommended_for_deploy(
        self, stack: Stack
    ) -> None:
        await _seed_synthetic_data(stack)

        response = await stack.client.post(
            "/api/v1/eval/backtest",
            json={
                "proposed_policy": {
                    "name": "block-everything",
                    "action": "BLOCK",
                    "tool_name_patterns": ["*"],
                },
                "run_filter": {},
            },
        )
        job_id = response.json()["job_id"]
        report = await _await_report(stack, job_id)
        # Baseline already detects all 3 incidents (drift 92 >= default
        # block), so block-everything cannot improve detection
        # (detection_rate_delta == 0) while it drives the false-positive rate
        # from 0% to 100% on the clean runs -- per the recommendation ladder
        # in backtester.py, detection_rate_delta <= 0 is DO NOT DEPLOY.
        assert report["detection_rate_delta"] == pytest.approx(0.0)
        assert report["fpr_delta"] > 0
        assert report["recommendation"] == "DO NOT DEPLOY"

    async def test_simulate_run_on_a_block_session(self, stack: Stack) -> None:
        ids = await _seed_synthetic_data(stack)
        session_id = ids["incident_0"]

        response = await stack.client.post(
            f"/api/v1/eval/simulate-run/{session_id}",
            json={"name": "tighter", "drift_block": 50.0},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["found"] is True
        assert body["session_id"] == session_id
        assert body["real_max_action"] == "BLOCK"

    async def test_tenant_isolation_org_b_sees_zero_runs(self, stack: Stack) -> None:
        # Org isolation here follows the run_filter semantics used by every
        # other org-scoped list route (list_runs, list_agents, ...): a
        # cross-org query returns an empty/zero result set rather than a 404,
        # since a backtest is a bulk analysis over "my org's data", not a
        # lookup of one specific resource that could be owned by someone else.
        other_org = uuid.uuid4().hex
        await _seed_synthetic_data(stack, organization_id=other_org)

        response = await stack.client.post(
            "/api/v1/eval/backtest",
            json={"proposed_policy": {"name": "any"}, "run_filter": {}},
        )
        job_id = response.json()["job_id"]
        report = await _await_report(stack, job_id)
        assert report["runs_analyzed"] == 0

    async def test_report_markdown_format(self, stack: Stack) -> None:
        await _seed_synthetic_data(stack)
        response = await stack.client.post(
            "/api/v1/eval/backtest",
            json={"proposed_policy": {"name": "any"}, "run_filter": {}},
        )
        job_id = response.json()["job_id"]
        await _await_report(stack, job_id)
        markdown = await stack.client.get(
            f"/api/v1/eval/backtest/{job_id}/report", params={"format": "markdown"}
        )
        assert markdown.status_code == 200
        assert "Recommendation" in markdown.text
