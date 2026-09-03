# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Types for drift trajectory scoring."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ariadne.proxy.schemas import utcnow


class TrajectoryPoint(BaseModel):
    """One (step, distance) sample inside the sliding window."""

    step_index: int
    raw_distance: float
    timestamp: datetime = Field(default_factory=utcnow)


class DriftScore(BaseModel):
    """Full scoring output — every component is surfaced to the dashboard.

    The composite `drift_score` is deliberately not the whole story: an
    operator triaging an alert needs to see whether it came from distance
    (this one action is off-mission) or slope (the run is escalating).
    """

    session_id: str
    step_index: int
    raw_distance: float
    slope: float
    drift_score: float = Field(ge=0.0, le=100.0)
    window_size: int
    timestamp: datetime = Field(default_factory=utcnow)

    @property
    def slope_is_escalating(self) -> bool:
        return self.slope > 0.0


class DriftUpdate(BaseModel):
    """The message pushed to dashboard WebSocket clients on every interception."""

    session_id: str
    step_index: int
    tool_name: str
    drift_score: float
    slope: float
    raw_distance: float
    enforcement_action: str
    reason: str = ""
    node_id: str | None = None
    timestamp: datetime = Field(default_factory=utcnow)
