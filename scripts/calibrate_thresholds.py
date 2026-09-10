#!/usr/bin/env python
# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Empirically calibrate DRIFT_SCORE_{WARN,ESCALATE,BLOCK} against real attack data.

Runs a large sample of real InjecAgent attack cases plus Ariadne's benign
control scenarios through the *real* pipeline (real MiniLM embeddings, real
scorer, real graph), records each scenario's peak drift score and whether it
was actually an attack, then grid-searches ESCALATE/BLOCK cutoffs for the
threshold that maximises detection rate subject to a false-positive-rate
ceiling. This replaces guessing at thresholds with a decision made from data.

    uv run python scripts/calibrate_thresholds.py \\
        --injecagent-dir external/InjecAgent/data --limit 80 --max-fpr 0.05
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ariadne.config import Settings
from eval.injecagent_adapter import load_cases
from tests.red_team.runner import Scenario, ScenarioResult, ScenarioRunner
from tests.red_team.scenarios.controls import (
    FOCUSED_SUMMARY,
    LATERAL_RESEARCH,
    LEGITIMATE_PAYMENT,
    MULTI_STEP_DEVOPS,
)

CONTROLS = [FOCUSED_SUMMARY, LATERAL_RESEARCH, LEGITIMATE_PAYMENT, MULTI_STEP_DEVOPS]

console = Console()


@dataclass(frozen=True)
class LabeledScore:
    name: str
    is_attack: bool
    max_drift_score: float


async def collect(settings: Settings, scenarios: list[Scenario]) -> list[LabeledScore]:
    runner = ScenarioRunner(settings)
    await runner.start()
    try:
        results: list[ScenarioResult] = [await runner.run(scenario) for scenario in scenarios]
    finally:
        await runner.stop()
    return [
        LabeledScore(result.scenario.name, result.scenario.is_attack, result.max_drift_score)
        for result in results
    ]


def sweep(scores: list[LabeledScore], max_fpr: float) -> tuple[float, float, dict[str, float]]:
    """Grid-search (escalate, block) cutoffs on a 0.5-point grid.

    Returns the pair maximising attack detection (peak score >= escalate)
    subject to false_positive_rate <= max_fpr on the benign set, and the
    resulting metrics.
    """
    attacks = [s.max_drift_score for s in scores if s.is_attack]
    benign = [s.max_drift_score for s in scores if not s.is_attack]
    if not attacks or not benign:
        raise SystemExit("Need at least one attack and one benign scenario to calibrate.")

    best: tuple[float, float, dict[str, float]] | None = None
    for step in range(20, 191):  # 10.0 .. 95.0 on a 0.5-point grid
        escalate = step * 0.5
        fp = sum(1 for b in benign if b >= escalate) / len(benign)
        if fp > max_fpr:
            continue
        detected = sum(1 for a in attacks if a >= escalate) / len(attacks)
        block = min(95.0, escalate + 20.0)
        metrics = {"detection_rate": detected, "false_positive_rate": fp}
        if best is None or detected > best[2]["detection_rate"]:
            best = (escalate, block, metrics)
    if best is None:
        # Nothing meets the FPR ceiling — fall back to the highest cutoff
        # that minimises FPR, and let the caller see the number is bad.
        escalate = max(benign) + 0.5
        fp = sum(1 for b in benign if b >= escalate) / len(benign)
        detected = sum(1 for a in attacks if a >= escalate) / len(attacks)
        best = (
            escalate,
            min(95.0, escalate + 20.0),
            {"detection_rate": detected, "false_positive_rate": fp},
        )
    return best


async def main_async(args: argparse.Namespace) -> int:
    injecagent_dir = args.injecagent_dir
    files = [
        injecagent_dir / "test_cases_dh_base.json",
        injecagent_dir / "test_cases_dh_enhanced.json",
        injecagent_dir / "test_cases_ds_base.json",
        injecagent_dir / "test_cases_ds_enhanced.json",
    ]
    scenarios: list[Scenario] = []
    for path in files:
        if not path.exists():
            console.print(f"[yellow]Skipping missing {path}[/yellow]")
            continue
        scenarios.extend(load_cases(path, args.limit))

    scenarios.extend(CONTROLS)

    attack_count = sum(1 for s in scenarios if s.is_attack)
    benign_count = len(scenarios) - attack_count
    console.print(
        f"Calibrating on {len(scenarios)} scenarios "
        f"({attack_count} attack, {benign_count} benign)…"
    )

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            DATABASE_URL=f"sqlite+aiosqlite:///{Path(tmp).as_posix()}/calibrate.db",
            ARCADEDB_URL=None,
            OPA_URL=None,
            HITL_WEBHOOK_URL=None,
            LOG_LEVEL="WARNING",
            EMBEDDING_DEVICE="auto",
        )
        scores = await collect(settings, scenarios)

    escalate, block, metrics = sweep(scores, args.max_fpr)

    table = Table(title="Threshold calibration result")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Samples", f"{len(scores)} ({attack_count} attack / {benign_count} benign)")
    table.add_row("Recommended ESCALATE", f"{escalate:.1f}")
    table.add_row("Recommended BLOCK", f"{block:.1f}")
    table.add_row("Detection rate at this cutoff", f"{metrics['detection_rate']:.0%}")
    table.add_row("False positive rate at this cutoff", f"{metrics['false_positive_rate']:.0%}")
    console.print(table)

    args.output.write_text(
        json.dumps(
            {
                "sample_size": len(scores),
                "attack_count": attack_count,
                "benign_count": benign_count,
                "recommended_escalate": escalate,
                "recommended_block": block,
                "metrics": metrics,
                "scores": [
                    {
                        "name": s.name,
                        "is_attack": s.is_attack,
                        "max_drift_score": s.max_drift_score,
                    }
                    for s in scores
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    console.print(f"Raw scores + recommendation written to [bold]{args.output}[/bold]")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--injecagent-dir", type=Path, default=Path("external/InjecAgent/data"))
    parser.add_argument("--limit", type=int, default=40, help="cases per InjecAgent file")
    parser.add_argument("--max-fpr", type=float, default=0.05)
    parser.add_argument("--output", type=Path, default=Path("threshold_calibration.json"))
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
