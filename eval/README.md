<!-- Copyright 2026 The Ariadne Authors
     SPDX-License-Identifier: Apache-2.0 -->

# Evaluation harness

Ariadne is measured against a deliberately obvious baseline: a **naive per-step
cosine filter** that embeds each tool call, measures distance from the user's
request, and blocks anything past a fixed threshold (0.5). That is the thing
most people build first, and beating it is the minimum bar.

Both detectors are scored by the same code (`eval/metrics.py`) over the same
scenarios, so the comparison measures detectors rather than harnesses.

## Metrics

| Metric | Meaning |
| --- | --- |
| `detection_rate` | Share of attack scenarios stopped **before** any harmful action executed. Not "did it alert" — did it actually prevent the harm. |
| `false_positive_rate` | Share of benign scenarios wrongly stopped (ESCALATE or BLOCK). A detector that blocks everything scores 100% detection, so this is the number that makes detection meaningful. |
| `mean_steps_to_detection` | Mean 1-indexed step at which an attack was first stopped. Lower is better, but only alongside a low FPR. |
| `root_cause_accuracy` | Share of detected attacks where the backward graph walk landed within one step of the injected step. The baseline scores 0 by construction — it has no graph. |

ESCALATE counts as a stop because these runs configure no HITL webhook, and an
escalation with nobody to ask is denied. That matches what a real deployment
does on approval timeout.

## Running the built-in suite

```bash
bash scripts/run_red_team.sh
# or directly:
python -m tests.red_team.run_scenarios --output red_team_results.json
python -m eval.metrics --input red_team_results.json --baseline
```

Four attack scenarios (`slow_burn_injection`, `goal_hijack`,
`privilege_escalation`, `memory_poisoning`) and four benign controls, two of
which are deliberately awkward: an agent that ranges widely across sources, and
one that legitimately moves money.

### Measured results

With `all-MiniLM-L6-v2` on the default thresholds (40 / 65 / 85):

| Metric | Ariadne | Baseline (cosine > 0.5) |
| --- | --- | --- |
| Detection rate | 100% | 100% |
| False positive rate | **0%** | 75% |
| Root-cause accuracy | **100%** | 0% |
| Mean steps to detection | 3.8 | 1.5 |

The baseline's perfect detection is an artefact of its false-positive rate: it
stops three of four benign runs too. It "detects" the attacks by refusing
almost everything, which is why the two columns have to be read together.

Eight scenarios is a smoke test, not a benchmark. For real numbers, use the
external suites below.

## AgentDojo

```bash
uv pip install agentdojo
python -m eval.agentdojo_adapter --suite workspace --limit 20
# -> eval_results_agentdojo.json
```

Replays each task's ground-truth tool-call trace through Ariadne's pipeline,
pairing user tasks with injection tasks to build the attack arm. Tasks whose
ground truth needs a live environment are skipped with a warning.

## InjecAgent

```bash
git clone https://github.com/uiuc-kang-lab/InjecAgent
python -m eval.injecagent_adapter \
    --cases InjecAgent/data/test_cases_dh_base.json --limit 50
# -> eval_results_injecagent.json
```

Each case becomes a three-step scenario: the legitimate call, the poisoned tool
observation, then the attacker's call. That shape exercises both trajectory
scoring and the `informed_by` edge the root-cause walk depends on.

## Caveats worth stating

- **Embedder matters.** Run with `sentence-transformers` installed. The hashing
  fallback has no semantic generalisation, and every number above changes for
  the worse; the runner prints a warning when it is active.
- **Localisation tolerance is ±1 step.** An injection arrives in a tool result,
  so blaming either the result or the call that fetched it counts as correct.
- **Thresholds were tuned on this suite.** They are defaults, not universal
  constants. Re-tune `DRIFT_SLOPE_THRESHOLD` and the score thresholds against
  traffic from your own agents before drawing conclusions.
