# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Multi-dimensional risk scoring: intent, tool, privilege, identity, data.

Drift scoring (ariadne/drift/scorer.py) answers one question -- "how far has
this action drifted, semantically, from the stated intent?" That is a strong
signal but a narrow one: a call can be dangerous along an axis drift never
sees at all (a graph-derived privilege-escalation edge, a credential-shaped
argument, an unverified caller identity). RiskDimensionScorer produces five
independent 0-100 scores plus a weighted aggregate so the enforcement engine
can react to whichever dimension is worst, not just to semantic distance.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from ariadne.config import Settings, get_settings
from ariadne.graph.schemas import EdgeType
from ariadne.proxy.schemas import ToolCall, utcnow

if TYPE_CHECKING:
    from ariadne.drift.schemas import DriftScore
    from ariadne.graph.builder import ProvenanceGraphBuilder
    from ariadne.intent.anchor import IntentAnchor
    from ariadne.proxy.schemas import SessionState

RiskLabel = Literal["aligned", "elevated", "critical"]

#: Substrings matched case-insensitively against a tool name that indicate a
#: mutating / outbound / privileged action.
HIGH_RISK_TOOL_MARKERS = (
    "write",
    "delete",
    "drop",
    "remove",
    "destroy",
    "send",
    "email",
    "pay",
    "charge",
    "transfer",
    "invoice",
    "upload",
    "publish",
    "admin",
    "grant",
    "revoke",
)

#: Substrings matched case-insensitively against a tool name that indicate a
#: read-only / observational action.
LOW_RISK_TOOL_MARKERS = (
    "read",
    "list",
    "search",
    "get",
    "fetch",
    "view",
    "summarize",
)

#: Base risk assigned to a tool whose name matches a high-risk marker.
_HIGH_RISK_BASE = 75.0
#: Base risk assigned to a tool whose name matches a low-risk marker.
_LOW_RISK_BASE = 12.0
#: Base risk for a tool name that matches neither list.
_UNKNOWN_RISK_BASE = 35.0

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_CREDENTIAL_KEY_MARKERS = ("token", "key", "secret", "password", "api_key")


def static_base_risk(tool_name: str) -> float:
    """The static, name-only risk baseline for a tool, on a 0-100 scale.

    Deliberately a module-level function rather than a method on
    RiskDimensionScorer: a future feature needs this exact lookup and importing
    it from a class defined in this module (which also imports the graph
    builder, intent anchor, and drift schemas) risks a circular import the
    moment that future module sits between this one and one of those. A bare
    function has none of those dependencies to drag along.
    """
    name = tool_name.lower()
    if any(marker in name for marker in HIGH_RISK_TOOL_MARKERS):
        return _HIGH_RISK_BASE
    if any(marker in name for marker in LOW_RISK_TOOL_MARKERS):
        return _LOW_RISK_BASE
    return _UNKNOWN_RISK_BASE


def _label_for(value: float) -> RiskLabel:
    """Shared aligned/elevated/critical banding used by every dimension."""
    if value > 70.0:
        return "critical"
    if value >= 40.0:
        return "elevated"
    return "aligned"


class DimensionScore(BaseModel):
    """One dimension's contribution to the overall risk picture."""

    value: float = Field(ge=0.0, le=100.0)
    label: RiskLabel
    contributing_factor: str | None = None


class RiskDimensionReport(BaseModel):
    """The full five-dimension breakdown for one tool call."""

    intent: DimensionScore
    tool: DimensionScore
    privilege: DimensionScore
    identity: DimensionScore
    data: DimensionScore
    aggregate: float = Field(ge=0.0, le=100.0)
    timestamp: datetime = Field(default_factory=utcnow)


class RiskDimensionScorer:
    """Scores a tool call along five independent risk dimensions."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        # Feature 10 (contextual tool-risk scoring). Imported here, inside
        # __init__, rather than at module level: contextual_tool_risk.py
        # imports `static_base_risk` from *this* module at its own module
        # scope, so an eager top-level import here would be circular. By the
        # time any instance of this class is constructed, this module has
        # already finished executing top-to-bottom, so the deferred import
        # always resolves cleanly.
        from ariadne.enforcement.contextual_tool_risk import (  # noqa: PLC0415
            ContextualToolRiskScorer,
        )

        self._tool_risk_scorer = ContextualToolRiskScorer(self._settings)

    async def score_all(
        self,
        tool_call: ToolCall,
        intent_anchor: "IntentAnchor | None",
        drift_score: "DriftScore | None",
        graph: "ProvenanceGraphBuilder | None",
        session_context: "SessionState | None" = None,
        session_history: list[ToolCall] | None = None,
        org_tool_overrides: dict[str, float] | None = None,
    ) -> RiskDimensionReport:
        """Score every dimension and combine them into a weighted aggregate."""
        intent = self._score_intent(drift_score)
        tool = self._score_tool(
            tool_call,
            session_history=session_history,
            org_tool_overrides=org_tool_overrides,
            intent_anchor=intent_anchor,
        )
        privilege = await self._score_privilege(tool_call, graph, session_context)
        identity = self._score_identity(tool_call, session_context)
        data = self._score_data(tool_call, intent_anchor)
        aggregate = self._aggregate(intent, tool, privilege, identity, data)
        return RiskDimensionReport(
            intent=intent,
            tool=tool,
            privilege=privilege,
            identity=identity,
            data=data,
            aggregate=aggregate,
        )

    def _score_intent(self, drift_score: "DriftScore | None") -> DimensionScore:
        """Maps the existing drift score directly onto the risk scale.

        No new computation here on purpose: drift already *is* the intent-
        alignment signal, so this dimension exists to let it participate in
        the weighted aggregate alongside the other four rather than being
        re-derived.
        """
        if drift_score is None:
            return DimensionScore(value=0.0, label="aligned", contributing_factor=None)
        value = max(0.0, min(100.0, drift_score.drift_score))
        label = _label_for(value)
        factor = f"drift score {value:.1f}" if label != "aligned" else None
        return DimensionScore(value=value, label=label, contributing_factor=factor)

    def _score_tool(
        self,
        tool_call: ToolCall,
        session_history: list[ToolCall] | None = None,
        org_tool_overrides: dict[str, float] | None = None,
        intent_anchor: "IntentAnchor | None" = None,
    ) -> DimensionScore:
        """Feature 10: delegates to ContextualToolRiskScorer.

        Feature 2's static name-pattern lookup (``static_base_risk`` above)
        is kept as the floor every contextual score is built on -- it is no
        longer this method's entire answer, just its starting point.
        """
        result = self._tool_risk_scorer.score(
            tool_call,
            session_history or [],
            org_tool_overrides or {},
            intent_anchor=intent_anchor,
        )
        label = _label_for(result.value)
        factor = result.explanation if label != "aligned" else None
        return DimensionScore(value=result.value, label=label, contributing_factor=factor)

    async def _score_privilege(
        self,
        tool_call: ToolCall,
        graph: "ProvenanceGraphBuilder | None",
        session_context: "SessionState | None",
    ) -> DimensionScore:
        """Graph-derived privilege signal: escalation edges and ungranted capabilities.

        Two independent checks, either of which is enough to flag the call:

        1. An ESCALATES_PRIVILEGE edge sourced from one of the last ~5 nodes in
           this session's graph (ariadne/graph/builder.py's
           _infer_privilege_escalation already writes these whenever a tool
           name/argument matches a privilege marker and the session was never
           granted that capability).
        2. The tool itself falls outside the session's granted capabilities --
           but only once the session has been granted *something*. A session
           that never registered any grants (the common case in this
           codebase today; grant_capabilities is opt-in) would otherwise have
           every single call flagged as "outside granted capabilities", which
           is not a useful signal -- it would just be restating "no grants
           were configured."
        """
        if graph is None:
            return DimensionScore(value=0.0, label="aligned", contributing_factor=None)

        session_graph = await graph.session_graph(tool_call.session_id)
        recent_node_ids = {node.id for node in session_graph.nodes[-5:]}
        escalation_edge = any(
            edge.edge_type == EdgeType.ESCALATES_PRIVILEGE and edge.source_id in recent_node_ids
            for edge in session_graph.edges
        )
        if escalation_edge:
            return DimensionScore(
                value=90.0,
                label="critical",
                contributing_factor="ESCALATES_PRIVILEGE edge present among recent graph nodes",
            )

        granted = graph.granted_capabilities(tool_call.session_id)
        outside_granted = bool(granted) and tool_call.tool_name.lower() not in granted
        if outside_granted:
            return DimensionScore(
                value=55.0,
                label="elevated",
                contributing_factor="tool is outside the session's granted capabilities",
            )

        return DimensionScore(value=8.0, label="aligned", contributing_factor=None)

    def _score_identity(
        self, tool_call: ToolCall, session_context: "SessionState | None"
    ) -> DimensionScore:
        """Heuristic risk from the caller-supplied `calling_agent_id`.

        IMPORTANT: this is a heuristic over an unverified, caller-supplied
        string (ariadne/proxy/schemas.py ToolCall.calling_agent_id, default
        "unknown"). There is no SPIFFE/workload-identity system, mTLS client
        certificate binding, or any other cryptographic identity mechanism in
        this codebase -- an attacker can put any string they like in this
        field. Treat this dimension as "does the caller look unidentified",
        not "is the caller who they claim to be".

        FOLLOW-UP LIMITATION: the original design called for boosting this
        score when the identity string has a prior Event row with
        enforcement_action == "BLOCK" in this org's audit history. That
        requires a DB handle, and RiskDimensionScorer -- like
        HybridEnforcementEngine, whose constructor takes only
        hard_layer/soft_layer/settings -- doesn't have one today. Threading a
        database session through score_all() for this one check would be a
        new dependency on a scorer that is otherwise pure/in-memory, forced in
        for a single heuristic. Scoring identity from in-memory signals only
        (the "unknown" check) keeps the scorer's dependency shape consistent
        with the rest of the enforcement path; the prior-BLOCK-history check
        is left as a follow-up once a DB handle is threaded through
        deliberately (e.g. alongside a future audit-trail-aware dimension).
        """
        agent_id = tool_call.calling_agent_id
        if agent_id == "unknown":
            return DimensionScore(
                value=45.0,
                label="elevated",
                contributing_factor="calling_agent_id was not supplied (default 'unknown')",
            )
        return DimensionScore(value=10.0, label="aligned", contributing_factor=None)

    def _score_data(
        self, tool_call: ToolCall, intent_anchor: "IntentAnchor | None"
    ) -> DimensionScore:
        """Scans call arguments for sensitive-data shapes and prohibition violations."""
        total = 0.0
        factors: list[str] = []

        args_text = json.dumps(_jsonable(tool_call.arguments), default=str)

        if _EMAIL_RE.search(args_text):
            total += 25.0
            factors.append("email address found in arguments")
        if _URL_RE.search(args_text):
            total += 20.0
            factors.append("external URL found in arguments")

        key_haystack = " ".join(_all_keys(tool_call.arguments)).lower()
        if any(marker in key_haystack for marker in _CREDENTIAL_KEY_MARKERS):
            total += 35.0
            factors.append("credential-like argument key name")

        if intent_anchor is not None:
            violations = intent_anchor.violated_prohibitions(tool_call.to_natural_language())
            if violations:
                total += 30.0
                factors.append(f"violates stated prohibition: {violations[0]}")

        total = min(total, 100.0)
        label = _label_for(total)
        return DimensionScore(
            value=total, label=label, contributing_factor=factors[0] if factors else None
        )

    def _aggregate(
        self,
        intent: DimensionScore,
        tool: DimensionScore,
        privilege: DimensionScore,
        identity: DimensionScore,
        data: DimensionScore,
    ) -> float:
        settings = self._settings
        total = (
            intent.value * settings.intent_weight
            + tool.value * settings.tool_weight
            + privilege.value * settings.privilege_weight
            + identity.value * settings.identity_weight
            + data.value * settings.data_weight
        )
        return max(0.0, min(100.0, total))


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value


def _all_keys(value: Any) -> list[str]:
    """Recursively collect every dict key in a JSON-serialisable structure."""
    keys: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            keys.append(str(key))
            keys.extend(_all_keys(nested))
    elif isinstance(value, list):
        for item in value:
            keys.extend(_all_keys(item))
    return keys
