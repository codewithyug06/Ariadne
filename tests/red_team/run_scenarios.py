# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Run every red-team scenario through Ariadne and the naive baseline."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from rich.console import Console

from ariadne.config import Settings
from ariadne.drift.embedder import ActionEmbedder
from ariadne.logging import configure_logging
from eval.baseline import NaiveCosineBaseline
from eval.metrics import EvalMetrics, compute_metrics, render_comparison, render_scenarios
from tests.red_team.runner import Scenario, ScenarioResult, ScenarioRunner
from tests.red_team.scenarios import (
    goal_hijack,
    memory_poisoning,
    privilege_escalation,
    slow_burn_injection,
)
from tests.red_team.scenarios.controls import CONTROL_SCENARIOS

ATTACK_SCENARIOS: list[Scenario] = [
    slow_burn_injection.SCENARIO,
    goal_hijack.SCENARIO,
    privilege_escalation.SCENARIO,
    memory_poisoning.SCENARIO,
]

ALL_SCENARIOS: list[Scenario] = [*ATTACK_SCENARIOS, *CONTROL_SCENARIOS]


def build_settings(database_path: Path) -> Settings:
    return Settings(
        DATABASE_URL=f"sqlite+aiosqlite:///{database_path.as_posix()}",
        OLLAMA_URL="http://localhost:11434",
        ARCADEDB_URL=None,
        OPA_URL=None,
        HITL_WEBHOOK_URL=None,
        LOG_LEVEL="WARNING",
        EMBEDDING_DEVICE="auto",
    )


async def run_ariadne(
    scenarios: list[Scenario], settings: Settings
) -> list[ScenarioResult]:
    runner = ScenarioRunner(settings)
    await runner.start()
    try:
        return [await runner.run(scenario) for scenario in scenarios]
    finally:
        await runner.stop()


async def run_baseline(
    scenarios: list[Scenario], settings: Settings, threshold: float
) -> list[ScenarioResult]:
    baseline = NaiveCosineBaseline(settings, threshold=threshold)
    return [await baseline.run(scenario) for scenario in scenarios]


async def main_async(args: argparse.Namespace) -> int:
    configure_logging(args.log_level, json_output=False)
    console = Console()

    scenarios = ALL_SCENARIOS
    if args.only:
        wanted = set(args.only)
        scenarios = [scenario for scenario in scenarios if scenario.name in wanted]
        if not scenarios:
            console.print(f"[red]No scenario matched {sorted(wanted)}[/red]")
            return 2

    with tempfile.TemporaryDirectory() as tmp:
        settings = build_settings(Path(tmp) / "redteam.db")

        embedder = ActionEmbedder.instance(settings)
        console.print(
            f"[bold]Ariadne red-team suite[/bold] — {len(scenarios)} scenarios, "
            f"embedder: {embedder.backend}"
        )
        if embedder.is_degraded:
            console.print(
                "[yellow]Warning: running on the hashing fallback embedder. "
                "Install the embeddings extra for representative results:[/yellow]\n"
                "  uv pip install sentence-transformers torch"
            )

        ariadne_results = await run_ariadne(scenarios, settings)
        ariadne_metrics = compute_metrics(ariadne_results, detector="ariadne")

        entries: list[EvalMetrics] = [ariadne_metrics]
        payload = {"ariadne": ariadne_metrics.to_dict()}

        if not args.no_baseline:
            baseline_results = await run_baseline(scenarios, settings, args.baseline_threshold)
            baseline_metrics = compute_metrics(
                baseline_results, detector=f"baseline (>{args.baseline_threshold})"
            )
            entries.append(baseline_metrics)
            payload["baseline"] = baseline_metrics.to_dict()

    render_comparison(console, entries)
    render_scenarios(console, ariadne_metrics)

    if args.output:
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        console.print(f"\nResults written to [bold]{args.output}[/bold]")

    failures = [
        entry["name"] for entry in ariadne_metrics.per_scenario if not entry["passed"]
    ]
    if failures:
        console.print(f"\n[red]{len(failures)} scenario(s) did not meet expectations:[/red]")
        for name in failures:
            console.print(f"  - {name}")
        return 1

    console.print("\n[green]All scenarios met their expected outcome.[/green]")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Ariadne red-team suite.")
    parser.add_argument("--output", type=Path, help="write results JSON here")
    parser.add_argument(
        "--no-baseline", action="store_true", help="skip the naive cosine comparison"
    )
    parser.add_argument(
        "--baseline-threshold", type=float, default=0.5, help="baseline cosine cutoff"
    )
    parser.add_argument("--only", nargs="*", help="run only these scenario names")
    parser.add_argument("--log-level", default="WARNING")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
