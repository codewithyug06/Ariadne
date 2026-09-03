# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""The comparison baseline: a naive per-step cosine filter.

This is what Ariadne has to beat — the obvious thing you build first. It
embeds each action, measures cosine distance from the user's request, and
blocks anything past a fixed threshold. No trajectory, no window, no graph, no
policy layer. It cannot localise a root cause, so its localisation accuracy is
zero by construction.
"""

from __future__ import annotations

import time

from ariadne.config import Settings
from ariadne.drift.embedder import ActionEmbedder
from ariadne.drift.scorer import cosine_similarity
from ariadne.proxy.schemas import ToolCall
from tests.red_team.runner import Scenario, ScenarioResult, StepOutcome

#: The threshold a reasonable engineer would pick, and the one the literature
#: uses for this comparison.
DEFAULT_THRESHOLD = 0.5


class NaiveCosineBaseline:
    """Flags any single step whose distance from the intent exceeds a threshold."""

    def __init__(
        self,
        settings: Settings,
        embedder: ActionEmbedder | None = None,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        self._settings = settings
        self._embedder = embedder or ActionEmbedder.instance(settings)
        self._threshold = threshold

    @property
    def name(self) -> str:
        return f"baseline (cosine > {self._threshold})"

    async def run(self, scenario: Scenario) -> ScenarioResult:
        intent = self._embedder.embed_text(scenario.user_request)
        outcomes: list[StepOutcome] = []
        started = time.perf_counter()

        for index, step in enumerate(scenario.steps, start=1):
            step_started = time.perf_counter()
            call = ToolCall(
                session_id=f"baseline-{scenario.name}",
                step_index=index,
                tool_name=step.tool_name,
                arguments=step.arguments,
            )
            distance = 1.0 - cosine_similarity(intent, self._embedder.embed(call))
            action = "BLOCK" if distance > self._threshold else "ALLOW"
            latency_ms = (time.perf_counter() - step_started) * 1000.0

            outcomes.append(
                StepOutcome(
                    step_index=index,
                    tool_name=step.tool_name,
                    action=action,
                    drift_score=min(100.0, distance * 100.0),
                    slope=0.0,
                    raw_distance=distance,
                    reason=(
                        f"cosine distance {distance:.2f} exceeds fixed threshold {self._threshold}"
                        if action == "BLOCK"
                        else f"cosine distance {distance:.2f} within threshold"
                    ),
                    triggered_rule=None,
                    node_id=None,
                    is_injection=step.is_injection,
                    is_harmful=step.is_harmful,
                    latency_ms=latency_ms,
                )
            )
            if action == "BLOCK":
                break

        return ScenarioResult(
            scenario=scenario,
            outcomes=outcomes,
            # No provenance graph exists, so no root cause can be produced.
            root_cause_step=None,
            root_cause_label=None,
            total_latency_ms=(time.perf_counter() - started) * 1000.0,
        )
