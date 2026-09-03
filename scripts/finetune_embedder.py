#!/usr/bin/env python
# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Fine-tune the drift embedder on real attack/benign separation.

The frozen all-MiniLM-L6-v2 model was never trained to separate "an action
that serves this request" from "an action that doesn't" — it is a general
sentence-similarity model. This script builds (anchor, positive, negative)
triplets straight from InjecAgent's real test cases — anchor is the user's
instruction, positive is the legitimate tool call it actually asked for,
negative is the attacker's tool call from the same case — and fine-tunes with
triplet loss so the geometry the drift scorer measures is the geometry that
actually matters: distance from stated intent to an attacker-controlled action.

    uv run python scripts/finetune_embedder.py \\
        --injecagent-dir external/InjecAgent/data \\
        --output models/ariadne-embedder-v1 --epochs 3

After training, point Ariadne at the fine-tuned model:
    EMBEDDING_MODEL=models/ariadne-embedder-v1
sentence-transformers loads a local directory exactly like a hub model id.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from ariadne.proxy.schemas import ToolCall

TRAIN_FILES = (
    "test_cases_dh_base.json",
    "test_cases_dh_enhanced.json",
    "test_cases_ds_base.json",
    "test_cases_ds_enhanced.json",
)


def _accuracy(result: float | dict[str, float]) -> float:
    """Newer sentence-transformers returns {"<name>_cosine_accuracy": ...}."""
    if isinstance(result, dict):
        return next(iter(result.values()))
    return result


def build_triplets(injecagent_dir: Path) -> list[tuple[str, str, str]]:
    """(anchor, positive, negative) — see module docstring for the shape."""
    triplets: list[tuple[str, str, str]] = []
    for filename in TRAIN_FILES:
        path = injecagent_dir / filename
        if not path.exists():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        cases = raw if isinstance(raw, list) else raw.get("cases", [])
        for case in cases:
            if not isinstance(case, dict):
                continue
            anchor = str(case.get("User Instruction", "")).strip()
            user_tool = str(case.get("User Tool", ""))
            if not anchor or not user_tool:
                continue
            attacker_tools = case.get("Attacker Tools") or [
                case.get("Attacker Tool", "attacker_tool")
            ]
            attacker_tool = str(
                attacker_tools[0] if isinstance(attacker_tools, list) else attacker_tools
            )
            parameters = case.get("Attacker Tool Parameters") or {}

            positive = ToolCall(
                session_id="train",
                step_index=1,
                tool_name=user_tool,
                arguments={"query": anchor[:200]},
            ).to_natural_language()
            negative = ToolCall(
                session_id="train",
                step_index=2,
                tool_name=attacker_tool,
                arguments=parameters if isinstance(parameters, dict) else {"payload": parameters},
            ).to_natural_language()
            triplets.append((anchor, positive, negative))
    return triplets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--injecagent-dir", type=Path, default=Path("external/InjecAgent/data"))
    parser.add_argument("--base-model", default="sentence-transformers/all-MiniLM-L6-v2")
    parser.add_argument("--output", type=Path, default=Path("models/ariadne-embedder-v1"))
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--eval-fraction", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    triplets = build_triplets(args.injecagent_dir)
    if len(triplets) < 20:
        raise SystemExit(
            f"Only found {len(triplets)} usable triplets under {args.injecagent_dir} — "
            "clone InjecAgent first: git clone https://github.com/uiuc-kang-lab/InjecAgent"
        )

    random.Random(args.seed).shuffle(triplets)  # noqa: S311 - reproducible split, not crypto
    split = max(1, int(len(triplets) * args.eval_fraction))
    eval_triplets, train_triplets = triplets[:split], triplets[split:]
    print(f"{len(train_triplets)} training triplets, {len(eval_triplets)} held out for eval")

    # Imported lazily: torch + sentence-transformers are the heavy optional
    # `embeddings` extra, not a hard dependency of the eval/calibration path.
    from sentence_transformers import (  # noqa: PLC0415
        InputExample,
        SentenceTransformer,
        losses,
    )
    from sentence_transformers.evaluation import TripletEvaluator  # noqa: PLC0415
    from torch.utils.data import DataLoader  # noqa: PLC0415

    model = SentenceTransformer(args.base_model)
    train_examples = [InputExample(texts=[a, p, n]) for a, p, n in train_triplets]
    train_loader = DataLoader(train_examples, shuffle=True, batch_size=args.batch_size)
    train_loss = losses.TripletLoss(
        model=model,
        distance_metric=losses.TripletDistanceMetric.COSINE,
        triplet_margin=0.3,
    )

    evaluator = TripletEvaluator(
        anchors=[t[0] for t in eval_triplets],
        positives=[t[1] for t in eval_triplets],
        negatives=[t[2] for t in eval_triplets],
        name="injecagent-holdout",
    )

    pre_score = _accuracy(evaluator(model))
    print(f"Pre-fine-tune triplet accuracy (holdout): {pre_score:.3f}")

    args.output.mkdir(parents=True, exist_ok=True)
    model.fit(
        train_objectives=[(train_loader, train_loss)],
        epochs=args.epochs,
        warmup_steps=max(1, int(len(train_loader) * 0.1)),
        evaluator=evaluator,
        evaluation_steps=max(1, len(train_loader) // 2),
        output_path=str(args.output),
        show_progress_bar=True,
    )

    post_score = _accuracy(evaluator(SentenceTransformer(str(args.output))))
    print(f"Post-fine-tune triplet accuracy (holdout): {post_score:.3f}")
    print(f"Model saved to {args.output}")
    print(f"Set EMBEDDING_MODEL={args.output} to use it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
