# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Structured representation of what the user actually asked for."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class GoalConstraint(BaseModel):
    """One extracted constraint, kept separate from free-text so it is testable."""

    text: str
    kind: str = "constraint"


class DecomposedIntent(BaseModel):
    """The decomposer's output contract — this is what the LLM must return."""

    goal: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    disallowed_actions: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW

    @property
    def is_heuristic(self) -> bool:
        """True when this came from the offline fallback rather than an LLM."""
        return self.goal.startswith("[heuristic] ")


class IntentAnchorSummary(BaseModel):
    """Serialisable view of an anchor, minus the embedding vector."""

    session_id: str
    raw_text: str
    goal: str
    constraints: list[str]
    disallowed_actions: list[str]
    risk_level: RiskLevel
    embedding_dimension: int
    decomposition_source: str
