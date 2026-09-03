# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Route AgentDojo benchmark tasks through Ariadne.

AgentDojo (https://github.com/ethz-spylab/agentdojo) supplies user tasks paired
with injection tasks across several suites. This adapter replays each task's
tool-call trace through Ariadne's interception pipeline and scores detection
with the same metrics as the red-team suite.

Requires the benchmark, which is not an Ariadne dependency:

    uv pip install agentdojo
    python -m eval.agentdojo_adapter --suite workspace --limit 20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console

from ariadne.config import Settings
from eval.baseline import NaiveCosineBaseline
from eval.metrics import compute_metrics, render_comparison, render_scenarios
from tests.red_team.runner import Scenario, ScenarioRunner, ScenarioStep

console = Console()

INSTALL_HINT = (
    "AgentDojo is not installed. Install it with:\n"
    "    uv pip install agentdojo\n"
    "then re-run this adapter."
)


@dataclass
class AdapterConfig:
    suite: str
    limit: int
    output: Path
    baseline_threshold: float


def load_suite(suite_name: str) -> Any:
    """Import AgentDojo lazily so the eval package imports without it."""
    try:
        from agentdojo.task_suite.load_suites import get_suite  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on optional package
        raise SystemExit(INSTALL_HINT) from exc
    return get_suite("v1", suite_name)


def to_scenario(
    suite_name: str,
    user_task: Any,
    injection_task: Any | None,
    tool_calls: list[Any],
) -> Scenario:
    """Convert one AgentDojo task into an Ariadne scenario.

    An injection task means the trace contains an attacker-supplied goal, so
    the run is an attack and the security check is whether Ariadne stops it
    before the injected tool call executes.
    """
    steps: list[ScenarioStep] = []
    injected_tools = _injected_tool_names(injection_task)

    for call in tool_calls:
        name = str(getattr(call, "function", getattr(call, "name", "unknown")))
        arguments = dict(getattr(call, "args", getattr(call, "arguments", {})) or {})
        is_injected = name in injected_tools
        steps.append(
            ScenarioStep(
                tool_name=name,
                arguments=arguments,
                result_content=str(getattr(call, "result", "ok"))[:1000],
                is_injection=is_injected,
                is_harmful=is_injected,
            )
        )

    prompt = str(getattr(user_task, "PROMPT", getattr(user_task, "prompt", "")))
    task_id = str(getattr(user_task, "ID", getattr(user_task, "id", "task")))

    return Scenario(
        name=f"agentdojo/{suite_name}/{task_id}" + ("/injected" if injection_task else ""),
        description=f"AgentDojo {suite_name} task {task_id}",
        user_request=prompt,
        steps=steps,
        expect_blocked=injection_task is not None,
        detect_by_step=len(steps) if injection_task is not None else None,
        is_attack=injection_task is not None,
    )


def _injected_tool_names(injection_task: Any | None) -> set[str]:
    if injection_task is None:
        return set()
    ground_truth = getattr(injection_task, "ground_truth", None)
    if callable(ground_truth):
        try:
            calls = ground_truth(None)  # type: ignore[misc]
        except (TypeError, AttributeError):
            return set()
        return {str(getattr(call, "function", getattr(call, "name", ""))) for call in calls or []}
    return set()


def build_scenarios(suite_name: str, limit: int) -> list[Scenario]:
    """Materialise scenarios from the benchmark's ground-truth traces."""
    suite = load_suite(suite_name)
    scenarios: list[Scenario] = []

    user_tasks = list(getattr(suite, "user_tasks", {}).values())
    injection_tasks = list(getattr(suite, "injection_tasks", {}).values())

    for index, user_task in enumerate(user_tasks):
        if len(scenarios) >= limit:
            break
        ground_truth = getattr(user_task, "ground_truth", None)
        if not callable(ground_truth):
            continue
        try:
            calls = ground_truth(None) or []
        except (TypeError, AttributeError):
            console.print(
                f"[yellow]Skipping {getattr(user_task, 'ID', index)}: "
                "ground truth needs a live environment[/yellow]"
            )
            continue

        scenarios.append(to_scenario(suite_name, user_task, None, list(calls)))

        # Pair each user task with one injection task to produce the attack arm.
        if injection_tasks and len(scenarios) < limit:
            injection = injection_tasks[index % len(injection_tasks)]
            injected_calls = []
            injection_ground_truth = getattr(injection, "ground_truth", None)
            if callable(injection_ground_truth):
                try:
                    injected_calls = list(injection_ground_truth(None) or [])
                except (TypeError, AttributeError):
                    injected_calls = []
            scenarios.append(
                to_scenario(suite_name, user_task, injection, [*calls, *injected_calls])
            )

    return scenarios


async def main_async(config: AdapterConfig) -> int:
    scenarios = build_scenarios(config.suite, config.limit)
    if not scenarios:
        console.print("[red]No runnable scenarios were produced from this suite.[/red]")
        return 1

    console.print(f"Replaying {len(scenarios)} AgentDojo scenarios through Ariadne…")

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            DATABASE_URL=f"sqlite+aiosqlite:///{Path(tmp).as_posix()}/agentdojo.db",
            ARCADEDB_URL=None,
            OPA_URL=None,
            HITL_WEBHOOK_URL=None,
            LOG_LEVEL="WARNING",
            EMBEDDING_DEVICE="auto",
        )

        runner = ScenarioRunner(settings)
        await runner.start()
        try:
            ariadne_results = [await runner.run(scenario) for scenario in scenarios]
        finally:
            await runner.stop()

        baseline = NaiveCosineBaseline(settings, threshold=config.baseline_threshold)
        baseline_results = [await baseline.run(scenario) for scenario in scenarios]

    ariadne_metrics = compute_metrics(ariadne_results, detector="ariadne")
    baseline_metrics = compute_metrics(
        baseline_results, detector=f"baseline (>{config.baseline_threshold})"
    )

    render_comparison(console, [ariadne_metrics, baseline_metrics])
    render_scenarios(console, ariadne_metrics)

    config.output.write_text(
        json.dumps(
            {
                "suite": config.suite,
                "ariadne": ariadne_metrics.to_dict(),
                "baseline": baseline_metrics.to_dict(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    console.print(f"\nResults written to [bold]{config.output}[/bold]")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AgentDojo tasks through Ariadne.")
    parser.add_argument("--suite", default="workspace", help="AgentDojo suite name")
    parser.add_argument("--limit", type=int, default=20, help="maximum scenarios")
    parser.add_argument("--output", type=Path, default=Path("eval_results_agentdojo.json"))
    parser.add_argument("--baseline-threshold", type=float, default=0.5)
    args = parser.parse_args()

    return asyncio.run(
        main_async(
            AdapterConfig(
                suite=args.suite,
                limit=args.limit,
                output=args.output,
                baseline_threshold=args.baseline_threshold,
            )
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
