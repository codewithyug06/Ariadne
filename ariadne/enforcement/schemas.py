# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Decision types produced by the hybrid enforcement engine."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from ariadne.audit.schemas import AuditEvent


class EnforcementAction(str, Enum):
    ALLOW = "ALLOW"
    WARN = "WARN"
    ESCALATE = "ESCALATE"
    BLOCK = "BLOCK"


#: Ordering used to take the strictest of several candidate actions.
ACTION_SEVERITY: dict[str, int] = {
    EnforcementAction.ALLOW.value: 0,
    EnforcementAction.WARN.value: 1,
    EnforcementAction.ESCALATE.value: 2,
    EnforcementAction.BLOCK.value: 3,
}


class PolicyViolation(BaseModel):
    """A single hard-rule finding."""

    rule_name: str
    description: str
    action: EnforcementAction
    matched_on: str
    requires_hitl_token: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class PolicyRule(BaseModel):
    """A declarative hard rule, mirroring one `deny`/`escalate` block in Rego."""

    name: str
    description: str
    action: EnforcementAction = EnforcementAction.BLOCK
    enabled: bool = True
    # Substrings matched case-insensitively against the tool name.
    tool_name_patterns: list[str] = Field(default_factory=list)
    # Substrings matched case-insensitively against the serialised arguments.
    argument_patterns: list[str] = Field(default_factory=list)
    requires_hitl_token: bool = False


class EnforcementDecision(BaseModel):
    """The verdict for one tool call."""

    action: Literal["ALLOW", "WARN", "ESCALATE", "BLOCK"]
    reason: str
    triggered_rule: str | None = None
    drift_score: float | None = None
    blocking_node_id: str | None = None
    requires_hitl_token: bool = False
    layer: Literal["hard", "soft", "none"] = "none"
    violations: list[PolicyViolation] = Field(default_factory=list)
    audit_event: AuditEvent | None = None

    @property
    def blocks(self) -> bool:
        return self.action == EnforcementAction.BLOCK.value
