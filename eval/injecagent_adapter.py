# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Route the InjecAgent benchmark through Ariadne.

InjecAgent (https://github.com/uiuc-kang-lab/InjecAgent) tests indirect prompt
injection delivered through tool *outputs*, split into direct-harm and
data-stealing attacks. Its cases map cleanly onto Ariadne's model: the user
task is the intent anchor, the poisoned observation is the injection, and the
attacker tool call is the harmful step.

The benchmark ships as JSON test cases rather than a package:

    git clone https://github.com/uiuc-kang-lab/InjecAgent
    python -m eval.injecagent_adapter \\
        --cases InjecAgent/data/test_cases_dh_base.json --limit 50
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from rich.console import Console

from ariadne.config import Settings
from eval.baseline import NaiveCosineBaseline
from eval.metrics import compute_metrics, render_comparison, render_scenarios
from tests.red_team.runner import Scenario, ScenarioRunner, ScenarioStep

console = Console()


def to_scenario(case: dict[str, Any], index: int) -> Scenario | None:
    """Convert one InjecAgent test case into a three-step Ariadne scenario.

    Step 1 is the legitimate call the user asked for, step 2 carries the
    poisoned observation, and step 3 is the attacker's tool call. That is the
    minimal shape which still exercises trajectory scoring and produces an
    `informed_by` edge from the poisoned result to the harmful action.
    """
    user_instruction = str(case.get("User Instruction", "")).strip()
    if not user_instruction:
        return None

    user_tool = str(case.get("User Tool", "user_tool"))
    attacker_tools = case.get("Attacker Tools") or [case.get("Attacker Tool", "attacker_tool")]
    attacker_tool = str(attacker_tools[0] if isinstance(attacker_tools, list) else attacker_tools)
    attacker_instruction = str(case.get("Attacker Instruction", "")).strip()
    tool_response = str(case.get("Tool Response", ""))[:1500]
    parameters = case.get("Attacker Tool Parameters") or {}

    return Scenario(
        name=f"injecagent/{index:04d}/{attacker_tool}",
        description=f"InjecAgent case: {attacker_instruction[:120]}",
        user_request=user_instruction,
        expect_blocked=True,
        detect_by_step=3,
        is_attack=True,
        steps=[
            ScenarioStep(
                tool_name=user_tool,
                arguments={"query": user_instruction[:200]},
                result_content="ok",
            ),
            ScenarioStep(
                tool_name=f"{user_tool}_read",
                arguments={"source": "external"},
                # The injected instruction arrives here, in tool output.
                result_content=tool_response or attacker_instruction,
                is_injection=True,
            ),
            ScenarioStep(
                tool_name=attacker_tool,
                arguments=parameters if isinstance(parameters, dict) else {"payload": parameters},
                result_content="executed",
                is_harmful=True,
            ),
        ],
    )


def load_cases(path: Path, limit: int) -> list[Scenario]:
    if not path.exists():
        raise SystemExit(
            f"Test case file not found: {path}\n"
            "Clone the benchmark first:\n"
            "    git clone https://github.com/uiuc-kang-lab/InjecAgent"
        )

    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = raw if isinstance(raw, list) else raw.get("cases", [])
    scenarios: list[Scenario] = []
    for index, case in enumerate(cases):
        if len(scenarios) >= limit:
            break
        if not isinstance(case, dict):
            continue
        scenario = to_scenario(case, index)
        if scenario is not None:
            scenarios.append(scenario)
    return scenarios


async def main_async(args: argparse.Namespace) -> int:
    scenarios = load_cases(args.cases, args.limit)
    if not scenarios:
        console.print("[red]No usable test cases were found in that file.[/red]")
        return 1

    console.print(f"Replaying {len(scenarios)} InjecAgent cases through Ariadne…")

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            DATABASE_URL=f"sqlite+aiosqlite:///{Path(tmp).as_posix()}/injecagent.db",
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

        baseline = NaiveCosineBaseline(settings, threshold=args.baseline_threshold)
        baseline_results = [await baseline.run(scenario) for scenario in scenarios]

    ariadne_metrics = compute_metrics(ariadne_results, detector="ariadne")
    baseline_metrics = compute_metrics(
        baseline_results, detector=f"baseline (>{args.baseline_threshold})"
    )

    render_comparison(console, [ariadne_metrics, baseline_metrics])
    render_scenarios(console, ariadne_metrics)

    args.output.write_text(
        json.dumps(
            {
                "cases": str(args.cases),
                "ariadne": ariadne_metrics.to_dict(),
                "baseline": baseline_metrics.to_dict(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    console.print(f"\nResults written to [bold]{args.output}[/bold]")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run InjecAgent cases through Ariadne.")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("InjecAgent/data/test_cases_dh_base.json"),
        help="path to an InjecAgent test-case JSON file",
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--output", type=Path, default=Path("eval_results_injecagent.json"))
    parser.add_argument("--baseline-threshold", type=float, default=0.5)
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
