# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Types for drift trajectory scoring."""

from __future__ import annotations

from datetime import datetime
from typing import Any

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
    #: Feature 8 (drift extrapolation engine). Goodness-of-fit of the
    #: least-squares line over the window's distances, in [0, 1]. This is the
    #: same R-squared TrajectoryScorer already computes internally as its
    #: "fit quality gate" (see ariadne/drift/scorer.py::_r_squared /
    #: _slope_confidence) but did not previously surface anywhere on
    #: DriftScore/AuditEvent. Defaults to 0.0 so existing callers/tests that
    #: construct a DriftScore directly (without this field) keep working —
    #: 0.0 is also the conservative choice: "not enough evidence to trust the
    #: trend," which is exactly the right default for a field that is only
    #: meaningful once actually populated by the scorer.
    r_squared: float = Field(default=0.0, ge=0.0, le=1.0)
    #: Feature 9 (calibrated/versioned risk scores). Which CalibrationProfile
    #: version's WARN/ESCALATE/BLOCK cutoffs were in effect when this score
    #: was computed. Defaults to "" (not None) for backward compat with
    #: existing direct constructions in tests, mirroring r_squared's
    #: always-populate-a-safe-default approach above rather than
    #: r_squared's own float default -- an empty string reads unambiguously
    #: as "not stamped" wherever this is displayed, without needing an
    #: Optional check everywhere it's formatted into text.
    calibration_version: str = Field(default="")
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
    #: Feature 1 (drift narrative engine) — populated best-effort, never
    #: required, so older dashboard clients tolerate them being null.
    narrative_summary: str | None = None
    narrative_trigger: str | None = None
    #: Feature 8 (drift extrapolation engine) — the full DriftProjection dump
    #: (or None when projection was skipped/failed/gated by low R-squared).
    #: Typed as a plain dict rather than importing DriftProjection here to
    #: avoid a schemas<->extrapolator import cycle (extrapolator.py already
    #: imports DriftScore/SlidingWindow from this module).
    projection: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=utcnow)
