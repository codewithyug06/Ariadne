# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Intent anchor generation, decomposition, and caching."""

from __future__ import annotations

import httpx
import numpy as np
import pytest

from ariadne.config import Settings
from ariadne.drift.embedder import ActionEmbedder
from ariadne.intent.anchor import IntentAnchorGenerator
from ariadne.intent.decomposer import IntentDecomposer
from ariadne.intent.schemas import DecomposedIntent, RiskLevel


class TestHeuristicFallback:
    """The offline path. Ariadne must protect a run on a host with no LLM."""

    async def test_unreachable_ollama_degrades_instead_of_raising(
        self, settings: Settings
    ) -> None:
        decomposer = IntentDecomposer(settings)
        decomposed, source = await decomposer.decompose("Summarise the sales report.")
        assert source == "heuristic"
        assert decomposed.goal.startswith("[heuristic]")
        await decomposer.aclose()

    async def test_prohibitions_are_mined_from_plain_english(
        self, settings: Settings
    ) -> None:
        decomposer = IntentDecomposer(settings)
        decomposed, _ = await decomposer.decompose(
            "Summarise this document. Do not send any emails and never delete files."
        )
        joined = " ".join(decomposed.disallowed_actions)
        assert "send" in joined
        assert "delete" in joined
        await decomposer.aclose()

    async def test_constraints_are_mined(self, settings: Settings) -> None:
        decomposer = IntentDecomposer(settings)
        decomposed, _ = await decomposer.decompose(
            "Book a flight, but only economy class and under $500."
        )
        joined = " ".join(decomposed.constraints)
        assert "economy" in joined
        await decomposer.aclose()

    @pytest.mark.parametrize(
        ("request_text", "expected"),
        [
            ("Read the changelog.", RiskLevel.LOW),
            ("Send an email to the team.", RiskLevel.MEDIUM),
            ("Transfer the payment to the vendor.", RiskLevel.HIGH),
            ("Delete the old records.", RiskLevel.HIGH),
        ],
    )
    async def test_risk_level_reflects_the_request(
        self, settings: Settings, request_text: str, expected: RiskLevel
    ) -> None:
        decomposer = IntentDecomposer(settings)
        decomposed, _ = await decomposer.decompose(request_text)
        assert decomposed.risk_level is expected
        await decomposer.aclose()

    async def test_empty_request_does_not_crash(self, settings: Settings) -> None:
        decomposer = IntentDecomposer(settings)
        decomposed, source = await decomposer.decompose("   ")
        assert source == "heuristic"
        assert decomposed.goal
        await decomposer.aclose()


class TestLLMDecomposition:
    async def test_valid_llm_json_is_used(self, settings: Settings) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "response": (
                        '{"goal": "Summarise the Q3 report", '
                        '"constraints": ["read-only"], '
                        '"disallowed_actions": ["send email"], '
                        '"risk_level": "medium"}'
                    )
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        decomposer = IntentDecomposer(settings, client=client)
        decomposed, source = await decomposer.decompose("Summarise the Q3 report.")

        assert decomposed.goal == "Summarise the Q3 report"
        assert decomposed.constraints == ["read-only"]
        assert decomposed.risk_level is RiskLevel.MEDIUM
        assert source.startswith("ollama:")
        await client.aclose()

    async def test_markdown_fenced_json_is_recovered(self, settings: Settings) -> None:
        """Instruct-tuned models wrap JSON in fences even when told not to."""
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "response": '```json\n{"goal": "Fetch logs", "risk_level": "low"}\n```'
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        decomposer = IntentDecomposer(settings, client=client)
        decomposed, source = await decomposer.decompose("Fetch the logs.")
        assert decomposed.goal == "Fetch logs"
        assert source.startswith("ollama:")
        await client.aclose()

    async def test_unparseable_output_falls_back_after_retries(
        self, settings: Settings
    ) -> None:
        calls = {"count": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            return httpx.Response(200, json={"response": "I cannot help with that."})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        decomposer = IntentDecomposer(settings, client=client)
        decomposed, source = await decomposer.decompose("Summarise the report.")

        assert source == "heuristic"
        assert decomposed.goal.startswith("[heuristic]")
        # Both models, each retried up to the configured limit.
        assert calls["count"] == settings.decomposer_max_retries * 2
        await client.aclose()

    async def test_server_error_falls_through_to_heuristic(self, settings: Settings) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "model not loaded"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        decomposer = IntentDecomposer(settings, client=client)
        _, source = await decomposer.decompose("Summarise the report.")
        assert source == "heuristic"
        await client.aclose()

    def test_response_parsing_rejects_invalid_shapes(self) -> None:
        assert IntentDecomposer._parse_response("") is None
        assert IntentDecomposer._parse_response("no json here") is None
        assert IntentDecomposer._parse_response('{"constraints": []}') is None  # goal required
        parsed = IntentDecomposer._parse_response('{"goal": "x"}')
        assert isinstance(parsed, DecomposedIntent)


class TestAnchorGeneration:
    async def test_anchor_carries_embedding_and_structure(
        self, anchors: IntentAnchorGenerator, settings: Settings
    ) -> None:
        anchor = await anchors.generate(
            "s1", "Summarise this document. Do not send emails."
        )
        assert anchor.embedding.shape == (settings.embedding_dimension,)
        assert np.linalg.norm(anchor.embedding) == pytest.approx(1.0, abs=1e-5)
        assert anchor.session_id == "s1"
        assert anchor.disallowed_actions

    async def test_anchor_is_cached_per_session(
        self, anchors: IntentAnchorGenerator
    ) -> None:
        first = await anchors.generate("s1", "Summarise the report.")
        second = await anchors.generate("s1", "A completely different request.")
        assert second is first, "an established anchor must not be replaced mid-run"

    async def test_cache_evicts_least_recently_used(
        self, embedder: ActionEmbedder, settings: Settings
    ) -> None:
        decomposer = IntentDecomposer(settings)
        decomposer._llm_available = False  # noqa: SLF001
        generator = IntentAnchorGenerator(
            embedder=embedder, decomposer=decomposer, settings=settings, cache_size=2
        )
        await generator.generate("a", "first")
        await generator.generate("b", "second")
        await generator.generate("c", "third")

        assert len(generator) == 2
        assert generator.get("a") is None
        assert generator.get("c") is not None
        await generator.aclose()

    async def test_summary_excludes_the_raw_vector(
        self, anchors: IntentAnchorGenerator, settings: Settings
    ) -> None:
        anchor = await anchors.generate("s1", "Summarise the report.")
        summary = anchor.summary()
        assert summary.embedding_dimension == settings.embedding_dimension
        assert not hasattr(summary, "embedding")

    async def test_discard_releases_the_session(
        self, anchors: IntentAnchorGenerator
    ) -> None:
        await anchors.generate("s1", "Summarise the report.")
        anchors.discard("s1")
        assert anchors.get("s1") is None
