# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Feature 10: contextual tool-risk scoring.

Feature 2's RiskDimensionScorer._score_tool() judged a tool call purely from
its name -- "delete_production_database" and "delete_draft_comment" scored
identically because both match the "delete" marker. That is a reasonable
floor (an attacker can pick an innocuous-sounding tool name, but an org's
tool catalog is fixed, so the name itself is still signal), but it is blind
to everything that makes a call actually dangerous *in context*: what
arguments were passed, and whether this exact tool/argument shape is routine
for this session or brand new.

ContextualToolRiskScorer layers three signals on top of each other:

1. Static base risk -- the original name-pattern floor, unchanged, reused
   from ``ariadne.enforcement.risk_dimensions.static_base_risk`` rather than
   re-implemented, so the two modules never drift out of sync on what counts
   as a "high risk" tool name.
2. Argument-level context -- what the call is actually doing (an email to an
   unknown domain, a path under /prod/, a credential-shaped key, a large
   numeric amount, an explicitly prohibited action).
3. Session novelty -- is this tool/pattern new for this session, or has it
   been seen (or over-used) already?

Org-specific tool overrides always win: if an operator has pinned a tool's
risk to a fixed number, that number *is* the answer, full stop -- no
argument or novelty signal can push it up or down. This lets an org silence
a noisy tool it knows is safe, or permanently flag one it knows is not,
without fighting the heuristics below.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from ariadne.config import Settings, get_settings
from ariadne.enforcement.risk_dimensions import _all_keys, _jsonable, static_base_risk
from ariadne.proxy.schemas import ToolCall

if TYPE_CHECKING:
    from ariadne.intent.anchor import IntentAnchor

#: Domains treated as internal/known-safe for the purposes of the email and
#: URL argument-context checks. Deliberately a short, generic seed list
#: rather than something org-configurable -- Feature 10's brief does not ask
#: for a settings-backed allowlist, and org_tool_overrides already gives
#: operators an escape hatch for any tool this default gets wrong.
_SAFE_EMAIL_DOMAINS = ("corp.com", "internal.example.com", "company.internal")
_SAFE_URL_HOSTS = ("corp.com", "internal.example.com", "company.internal")

_EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
_URL_RE = re.compile(r"https?://([^\s\"'<>/]+)")
_PROD_PATH_MARKERS = ("/prod/", "/production/", "/live/", "production", "prod")
_CREDENTIAL_KEY_MARKERS = ("token", "key", "secret", "password", "api_key")

#: Caps applied per the spec: no single layer's modifier may exceed this,
#: regardless of how many individual triggers fire within it.
_ARGUMENT_MODIFIER_CAP = 50.0
_NOVELTY_MODIFIER_CAP = 15.0

#: Novelty modifier magnitudes.
_FIRST_USE_HIGH_RISK_BONUS = 10.0
_FIRST_USE_GENERIC_BONUS = 5.0
_RAPID_REPETITION_BONUS = 15.0
_RAPID_REPETITION_WINDOW = 10
_RAPID_REPETITION_THRESHOLD = 5
#: Base risk above which a tool's *first* use in a session is treated as the
#: stronger "first use of something dangerous" signal rather than the
#: generic "never seen this tool before" signal.
_HIGH_BASE_RISK_CUTOFF = 40.0


class ContextualRiskScore(BaseModel):
    """The contextual tool-risk verdict for one call."""

    value: float
    base_risk: float
    argument_modifier: float
    novelty_modifier: float
    explanation: str


class ContextualToolRiskScorer:
    """Three-layer tool risk: static base + argument context + session novelty.

    Org tool overrides always win when present.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def score(
        self,
        tool_call: ToolCall,
        session_history: list[ToolCall],
        org_tool_overrides: dict[str, float],
        *,
        intent_anchor: IntentAnchor | None = None,
    ) -> ContextualRiskScore:
        if tool_call.tool_name in org_tool_overrides:
            override = org_tool_overrides[tool_call.tool_name]
            return ContextualRiskScore(
                value=override,
                base_risk=override,
                argument_modifier=0.0,
                novelty_modifier=0.0,
                explanation=(
                    f"Org override: tool '{tool_call.tool_name}' fixed at {override}"
                ),
            )

        base = self._static_base_risk(tool_call.tool_name)
        arg_mod, arg_factors = self._argument_context_modifier_detail(tool_call, intent_anchor)
        nov_mod, nov_factor = self._novelty_modifier_detail(tool_call, session_history)
        final = min(100.0, base + arg_mod + nov_mod)
        explanation = self._explain(tool_call, base, arg_mod, nov_mod, arg_factors, nov_factor)
        return ContextualRiskScore(
            value=final,
            base_risk=base,
            argument_modifier=arg_mod,
            novelty_modifier=nov_mod,
            explanation=explanation,
        )

    def _static_base_risk(self, tool_name: str) -> float:
        """The name-pattern floor.

        Delegates to ``risk_dimensions.static_base_risk`` (a bare module
        function with no class dependencies) rather than re-implementing the
        HIGH/LOW marker table here, so there is exactly one source of truth
        for "what does this tool's name alone suggest". Feature 2's
        `RiskDimensionScorer._score_tool` now delegates the other direction
        (to this class), so importing back into risk_dimensions here would be
        circular if done eagerly at module scope -- risk_dimensions.py avoids
        that by importing ContextualToolRiskScorer lazily inside its
        constructor instead of at module level.
        """
        return static_base_risk(tool_name)

    def _argument_context_modifier(self, tool_call: ToolCall) -> float:
        """Public-facing single-value modifier (spec shape). See detail variant."""
        value, _ = self._argument_context_modifier_detail(tool_call, None)
        return value

    def _argument_context_modifier_detail(
        self, tool_call: ToolCall, intent_anchor: IntentAnchor | None
    ) -> tuple[float, list[str]]:
        args = tool_call.arguments
        args_text = _stringify_arguments(args)
        total = 0.0
        factors: list[str] = []

        email_match = _EMAIL_RE.search(args_text)
        if email_match and not _domain_is_safe(email_match.group(1), _SAFE_EMAIL_DOMAINS):
            total += 25.0
            factors.append(f"email address to external/unknown domain '{email_match.group(1)}'")

        url_match = _URL_RE.search(args_text)
        if url_match and not _domain_is_safe(url_match.group(1), _SAFE_URL_HOSTS):
            total += 20.0
            factors.append(f"external URL not in the known-safe allowlist ('{url_match.group(1)}')")

        if any(marker in args_text.lower() for marker in _PROD_PATH_MARKERS):
            total += 30.0
            factors.append("argument references a production/live path")

        key_haystack = " ".join(_all_keys(args)).lower()
        if any(marker in key_haystack for marker in _CREDENTIAL_KEY_MARKERS):
            total += 35.0
            factors.append("credential-like argument key name")

        threshold = self._settings.large_transaction_threshold
        if threshold > 0.0 and _any_numeric_exceeds(args, threshold):
            total += 25.0
            factors.append(f"numeric argument exceeds large-transaction threshold {threshold}")

        if intent_anchor is not None:
            violations = intent_anchor.violated_prohibitions(tool_call.to_natural_language())
            if violations:
                total += 30.0
                factors.append(f"argument matches disallowed action: {violations[0]}")

        return min(total, _ARGUMENT_MODIFIER_CAP), factors

    def _novelty_modifier(self, tool_call: ToolCall, history: list[ToolCall]) -> float:
        value, _ = self._novelty_modifier_detail(tool_call, history)
        return value

    def _novelty_modifier_detail(
        self, tool_call: ToolCall, history: list[ToolCall]
    ) -> tuple[float, str | None]:
        """Session-novelty modifier.

        Disambiguating the spec's two "first use" bullets (they overlap --
        a tool's first appearance in a session is, definitionally, also a
        tool that "never appeared in history at all"): the higher-value
        signal wins. A first-ever use of a *high-base-risk* tool gets the
        larger +10 "first use of something dangerous" bonus; a first-ever use
        of anything else gets the smaller generic +5 "new pattern" bonus.
        They never stack with each other. Rapid repetition is a separate,
        mutually exclusive case (it requires the tool to already be in
        history), so it cannot co-occur with either "first use" branch.
        """
        prior_same_tool = [call for call in history if call.tool_name == tool_call.tool_name]

        if not prior_same_tool:
            base = self._static_base_risk(tool_call.tool_name)
            if base > _HIGH_BASE_RISK_CUTOFF:
                return _FIRST_USE_HIGH_RISK_BONUS, "first use of a high-base-risk tool this session"
            return _FIRST_USE_GENERIC_BONUS, "tool never appeared earlier in this session"

        recent_window = history[-_RAPID_REPETITION_WINDOW:]
        recent_same_tool = sum(1 for call in recent_window if call.tool_name == tool_call.tool_name)
        if recent_same_tool > _RAPID_REPETITION_THRESHOLD:
            return (
                _RAPID_REPETITION_BONUS,
                f"rapid repetition: called {recent_same_tool} times in the last "
                f"{len(recent_window)} steps",
            )

        return 0.0, None

    def _explain(
        self,
        tool_call: ToolCall,
        base: float,
        arg_mod: float,
        nov_mod: float,
        arg_factors: list[str],
        nov_factor: str | None,
    ) -> str:
        parts = [f"'{tool_call.tool_name}' base risk {base:.1f}"]
        if arg_factors:
            parts.append("argument context: " + "; ".join(arg_factors))
        if nov_factor:
            parts.append(f"novelty: {nov_factor}")
        if not arg_factors and not nov_factor:
            parts.append("no argument or novelty signals triggered")
        return "; ".join(parts)


def _domain_is_safe(host: str, safe_hosts: tuple[str, ...]) -> bool:
    host = host.lower()
    return any(host == safe or host.endswith("." + safe) for safe in safe_hosts)


def _stringify_arguments(args: dict[str, Any]) -> str:
    import json

    return json.dumps(_jsonable(args), default=str)


def _any_numeric_exceeds(value: Any, threshold: float) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value > threshold
    if isinstance(value, dict):
        return any(_any_numeric_exceeds(nested, threshold) for nested in value.values())
    if isinstance(value, list):
        return any(_any_numeric_exceeds(item, threshold) for item in value)
    return False
