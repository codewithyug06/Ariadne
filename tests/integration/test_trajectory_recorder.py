# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Feature 7: Data Flywheel -- end-to-end session -> TrajectoryRecord -> API.

The recorder's own labeling/curve-building logic is covered at the unit
level (tests/unit/test_trajectory_recorder.py); this file only exercises
what needs the full API/DB stack: that ending a real session produces a row
reachable through the admin export/label/stats endpoints.
"""

from __future__ import annotations

import json
import uuid

from tests.integration.conftest import Stack, call_tool
from tests.integration.test_agents import end_session, init_with_agent


class TestTrajectoryExportAndLabeling:
    async def test_ending_a_session_produces_an_exportable_trajectory(
        self, stack: Stack
    ) -> None:
        session_id = f"traj-{uuid.uuid4()}"
        stack.on_mission("summarise the quarterly report")

        await init_with_agent(stack, session_id, "summarise the quarterly report")
        await call_tool(stack, session_id, "read_file", {"path": "report.csv"})
        ended = await end_session(stack, session_id)
        assert ended.status_code == 200

        export = await stack.client.get("/api/v1/admin/trajectories/export")
        assert export.status_code == 200
        lines = [line for line in export.text.splitlines() if line.strip()]
        rows = [json.loads(line) for line in lines]
        matches = [row for row in rows if row["session_id"] == session_id]
        assert len(matches) == 1
        row = matches[0]
        assert row["step_count"] == len(row["drift_curve"]) == len(row["slope_curve"])
        assert len(row["r2_curve"]) == row["step_count"]
        assert row["confirmed_attack"] is None
        assert row["label_source"] is None

    async def test_labeling_a_trajectory_sets_confirmed_attack_and_timestamp(
        self, stack: Stack
    ) -> None:
        session_id = f"traj-label-{uuid.uuid4()}"
        stack.on_mission("read the config file")

        await init_with_agent(stack, session_id, "read the config file")
        await call_tool(stack, session_id, "read_file", {"path": "config.yaml"})
        await end_session(stack, session_id)

        export = await stack.client.get("/api/v1/admin/trajectories/export")
        rows = [json.loads(line) for line in export.text.splitlines() if line.strip()]
        trajectory_id = next(row["id"] for row in rows if row["session_id"] == session_id)

        labeled = await stack.client.post(
            f"/api/v1/admin/trajectories/{trajectory_id}/label",
            json={"confirmed_attack": True, "label_source": "human_review"},
        )
        assert labeled.status_code == 200
        body = labeled.json()
        assert body["confirmed_attack"] is True
        assert body["label_source"] == "human_review"
        assert body["labeled_at"] is not None

    async def test_labeling_an_unknown_trajectory_404s(self, stack: Stack) -> None:
        response = await stack.client.post(
            "/api/v1/admin/trajectories/does-not-exist/label",
            json={"confirmed_attack": False, "label_source": "human_review"},
        )
        assert response.status_code == 404

    async def test_stats_reflects_recorded_trajectories(self, stack: Stack) -> None:
        session_id = f"traj-stats-{uuid.uuid4()}"
        stack.on_mission("list the files")

        await init_with_agent(stack, session_id, "list the files")
        await call_tool(stack, session_id, "read_file", {"path": "a.txt"})
        await end_session(stack, session_id)

        stats = await stack.client.get("/api/v1/admin/trajectories/stats")
        assert stats.status_code == 200
        body = stats.json()
        assert body["total"] >= 1
        assert sum(body["by_confirmed_attack"].values()) == body["total"]
        assert sum(body["by_final_enforcement_action"].values()) == body["total"]
