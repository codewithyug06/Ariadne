# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Feature 7: Data Flywheel / Trajectory Store.

Unit-level: constructs AuditEvent/RunSummary objects directly (no proxy, no
HTTP stack) and drives TrajectoryRecorder against the real `database` fixture
(an in-memory SQLite DB via tests/conftest.py) -- there's no existing
recorder-style unit-test precedent in tests/unit that avoids a DB entirely,
and the whole point of this class is what it persists, so a real session
round-trip is more honest than mocking the session.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from ariadne.audit.schemas import AuditEvent, RunSummary
from ariadne.audit.trajectory_recorder import TrajectoryRecorder
from ariadne.db.models import TrajectoryRecord
from ariadne.db.session import Database
from ariadne.proxy.schemas import utcnow


def _make_event(
    step_index: int,
    enforcement_action: str = "ALLOW",
    drift_score: float | None = 10.0,
    slope: float | None = 0.5,
    triggered_rule: str | None = None,
    narrative: dict[str, object] | None = None,
    risk_dimensions: dict[str, object] | None = None,
    node_id: str | None = None,
) -> AuditEvent:
    payload: dict[str, object] = {}
    if risk_dimensions is not None:
        payload["risk_dimensions"] = risk_dimensions
    return AuditEvent(
        event_id=str(uuid.uuid4()),
        session_id="test-session",
        step_index=step_index,
        tool_name="some_tool",
        enforcement_action=enforcement_action,
        triggered_rule=triggered_rule,
        drift_score=drift_score,
        slope=slope,
        node_id=node_id,
        payload=payload,
        narrative=narrative,
    )


def _make_risk_dims(intent: float = 1.0, tool: float = 2.0, privilege: float = 3.0,
                     identity: float = 4.0, data: float = 5.0) -> dict[str, object]:
    def dim(value: float) -> dict[str, object]:
        return {"value": value, "label": "low", "contributing_factor": None}

    return {
        "intent": dim(intent),
        "tool": dim(tool),
        "privilege": dim(privilege),
        "identity": dim(identity),
        "data": dim(data),
        "aggregate": (intent + tool + privilege + identity + data) / 5,
    }


def _make_summary(final_status: str = "CLEAN") -> RunSummary:
    return RunSummary(
        session_id="test-session",
        started_at=utcnow(),
        ended_at=utcnow(),
        total_steps=3,
        final_status=final_status,
    )


async def _get_record(database: Database, session_id: str) -> TrajectoryRecord:
    async with database.session() as session:
        row = await session.scalar(
            select(TrajectoryRecord).where(TrajectoryRecord.session_id == session_id)
        )
        assert row is not None
        return row


class TestTrajectoryRecorder:
    async def test_hard_rule_block_is_auto_labeled_confirmed_attack(
        self, database: Database
    ) -> None:
        session_id = f"block-hard-{uuid.uuid4()}"
        events = [
            _make_event(0, "ALLOW"),
            _make_event(1, "WARN"),
            _make_event(
                2,
                "BLOCK",
                triggered_rule="deny-secrets-exfil",
                risk_dimensions=_make_risk_dims(),
            ),
        ]
        for event in events:
            event.session_id = session_id

        recorder = TrajectoryRecorder(database)
        await recorder.record_session(session_id, events, _make_summary("BLOCKED"))

        row = await _get_record(database, session_id)
        assert row.confirmed_attack is True
        assert row.label_source == "auto_policy"
        assert row.final_enforcement_action == "BLOCK"

    async def test_drift_score_only_block_is_left_unlabeled(self, database: Database) -> None:
        session_id = f"block-drift-{uuid.uuid4()}"
        events = [
            _make_event(0, "ALLOW"),
            _make_event(1, "ESCALATE"),
            _make_event(2, "BLOCK", triggered_rule=None, drift_score=95.0),
        ]
        for event in events:
            event.session_id = session_id

        recorder = TrajectoryRecorder(database)
        await recorder.record_session(session_id, events, _make_summary("BLOCKED"))

        row = await _get_record(database, session_id)
        assert row.confirmed_attack is None
        assert row.label_source is None
        assert row.final_enforcement_action == "BLOCK"

    async def test_allow_session_is_unlabeled(self, database: Database) -> None:
        session_id = f"allow-{uuid.uuid4()}"
        events = [_make_event(0, "ALLOW"), _make_event(1, "ALLOW")]
        for event in events:
            event.session_id = session_id

        recorder = TrajectoryRecorder(database)
        await recorder.record_session(session_id, events, _make_summary("CLEAN"))

        row = await _get_record(database, session_id)
        assert row.confirmed_attack is None
        assert row.final_enforcement_action == "ALLOW"

    async def test_curve_lengths_match_step_count(self, database: Database) -> None:
        session_id = f"curves-{uuid.uuid4()}"
        events = [_make_event(i, "ALLOW", drift_score=float(i), slope=float(i)) for i in range(5)]
        for event in events:
            event.session_id = session_id

        recorder = TrajectoryRecorder(database)
        await recorder.record_session(session_id, events, _make_summary("CLEAN"))

        row = await _get_record(database, session_id)
        assert row.step_count == 5
        assert len(row.drift_curve) == 5
        assert len(row.slope_curve) == 5
        assert len(row.r2_curve) == 5

    async def test_narrative_first_divergence_and_trigger_are_pulled_from_events(
        self, database: Database
    ) -> None:
        session_id = f"narrative-{uuid.uuid4()}"
        events = [
            _make_event(0, "ALLOW"),
            _make_event(
                1,
                "WARN",
                narrative={
                    "summary": "drifting",
                    "trigger": "off_mission_distance",
                    "first_divergence_step": 1,
                },
            ),
        ]
        for event in events:
            event.session_id = session_id

        recorder = TrajectoryRecorder(database)
        await recorder.record_session(session_id, events, _make_summary("WARNED"))

        row = await _get_record(database, session_id)
        assert row.first_divergence_step == 1
        assert row.root_cause_trigger == "off_mission_distance"

    async def test_risk_dimensions_default_to_zero_when_absent(self, database: Database) -> None:
        session_id = f"no-risk-{uuid.uuid4()}"
        events = [_make_event(0, "ALLOW")]
        for event in events:
            event.session_id = session_id

        recorder = TrajectoryRecorder(database)
        await recorder.record_session(session_id, events, _make_summary("CLEAN"))

        row = await _get_record(database, session_id)
        assert row.intent_score == 0.0
        assert row.tool_score == 0.0
        assert row.privilege_score == 0.0
        assert row.identity_score == 0.0
        assert row.data_score == 0.0

    async def test_write_failure_is_caught_and_never_raises(self, database: Database) -> None:
        """The recorder must never fail the caller -- session-end must not break."""

        class ExplodingDatabase:
            def session(self) -> None:  # type: ignore[override]
                raise RuntimeError("boom")

        recorder = TrajectoryRecorder(ExplodingDatabase())  # type: ignore[arg-type]
        # Must not raise.
        await recorder.record_session("whatever", [], _make_summary("CLEAN"))
