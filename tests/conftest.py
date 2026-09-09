# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Shared pytest fixtures: deterministic embeddings, isolated DB, mock upstream MCP."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import pytest_asyncio
from fastapi import FastAPI

from ariadne.audit.recorder import AuditRecorder
from ariadne.config import Settings
from ariadne.db.session import Database
from ariadne.drift.embedder import ActionEmbedder, HashingEmbedder
from ariadne.drift.scorer import TrajectoryScorer
from ariadne.drift.window import SlidingWindow
from ariadne.enforcement.engine import HybridEnforcementEngine
from ariadne.graph.builder import ProvenanceGraphBuilder
from ariadne.graph.store import NetworkXGraphStore
from ariadne.intent.anchor import IntentAnchor, IntentAnchorGenerator
from ariadne.intent.decomposer import IntentDecomposer
from ariadne.intent.schemas import RiskLevel
from ariadne.proxy.interceptor import ToolCallInterceptor
from ariadne.streaming import DriftStreamHub


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--real-embedder",
        action="store_true",
        default=False,
        help="Exercise the sentence-transformers/GPU path instead of the deterministic stand-in.",
    )


@pytest.fixture(scope="session")
def use_real_embedder(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--real-embedder"))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Isolated settings: temp database, no external services, no LLM.

    _env_file=None is load-bearing, not decorative: without it,
    pydantic-settings still reads the real project .env (per
    ariadne/config.py's `env_file=".env"`), so a developer's local secrets —
    JWT_SECRET_KEY, ARIADNE_API_KEYS, etc. — silently leak into every test's
    Settings and enable auth the tests never expect.
    """
    return Settings(
        _env_file=None,
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path.as_posix()}/test.db",
        UPSTREAM_MCP_URL="http://upstream.test/mcp",
        EMBEDDING_DEVICE="cpu",
        OLLAMA_URL="http://localhost:1",  # deliberately unreachable
        ARCADEDB_URL=None,
        OPA_URL=None,
        HITL_WEBHOOK_URL=None,
        LOG_LEVEL="WARNING",
    )


class DeterministicEmbedder:
    """Vectors that are stable across runs and controllable from a test.

    Wraps the hashing backend so unrelated text really is near-orthogonal,
    and lets a test pin an exact vector for a phrase when a scenario needs a
    specific geometry.
    """

    def __init__(self, dimension: int = 384) -> None:
        self._inner = HashingEmbedder(dimension)
        self._pinned: dict[str, np.ndarray] = {}

    @property
    def dimension(self) -> int:
        return self._inner.dimension

    @property
    def backend(self) -> str:
        return "deterministic-test"

    def pin(self, text: str, vector: np.ndarray) -> None:
        norm = float(np.linalg.norm(vector))
        self._pinned[text] = (vector / norm).astype(np.float32) if norm else vector.astype(np.float32)

    def embed_text(self, text: str) -> np.ndarray:
        if text in self._pinned:
            return self._pinned[text]
        return self._inner.embed_text(text)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        return np.vstack([self.embed_text(text) for text in texts])


@pytest.fixture
def embedder(settings: Settings, use_real_embedder: bool) -> Iterator[ActionEmbedder]:
    ActionEmbedder.reset()
    backend: Any = None if use_real_embedder else DeterministicEmbedder(settings.embedding_dimension)
    instance = ActionEmbedder(backend=backend, settings=settings)
    yield instance
    ActionEmbedder.reset()


@pytest.fixture
def scorer(settings: Settings) -> TrajectoryScorer:
    return TrajectoryScorer(settings)


@pytest.fixture
def window(settings: Settings) -> SlidingWindow:
    return SlidingWindow("test-session", settings.drift_window_size)


@pytest.fixture
def graph_store() -> NetworkXGraphStore:
    return NetworkXGraphStore()


@pytest.fixture
def graph_builder(graph_store: NetworkXGraphStore, settings: Settings) -> ProvenanceGraphBuilder:
    return ProvenanceGraphBuilder(graph_store, settings)


@pytest.fixture
def enforcement_engine(settings: Settings) -> HybridEnforcementEngine:
    return HybridEnforcementEngine(settings=settings)


@pytest_asyncio.fixture
async def database(settings: Settings) -> AsyncIterator[Database]:
    db = Database(settings)
    await db.create_all()
    yield db
    await db.close()


@pytest_asyncio.fixture
async def recorder(database: Database, settings: Settings) -> AsyncIterator[AuditRecorder]:
    audit = AuditRecorder(database, settings)
    await audit.start()
    yield audit
    await audit.stop()


@pytest.fixture
def anchors(embedder: ActionEmbedder, settings: Settings) -> IntentAnchorGenerator:
    """Anchor generator with the LLM path disabled — heuristic decomposition only."""
    decomposer = IntentDecomposer(settings)
    decomposer._llm_available = False  # noqa: SLF001 - deliberate offline pin for tests
    return IntentAnchorGenerator(embedder=embedder, decomposer=decomposer, settings=settings)


@pytest.fixture
def stream_hub() -> DriftStreamHub:
    return DriftStreamHub()


@pytest.fixture
def interceptor(
    embedder: ActionEmbedder,
    scorer: TrajectoryScorer,
    graph_builder: ProvenanceGraphBuilder,
    enforcement_engine: HybridEnforcementEngine,
    anchors: IntentAnchorGenerator,
    recorder: AuditRecorder,
    stream_hub: DriftStreamHub,
    settings: Settings,
) -> ToolCallInterceptor:
    return ToolCallInterceptor(
        embedder=embedder,
        scorer=scorer,
        graph_builder=graph_builder,
        engine=enforcement_engine,
        anchors=anchors,
        recorder=recorder,
        stream_hub=stream_hub,
        settings=settings,
    )


@pytest.fixture
def session_id() -> str:
    return f"test-{uuid.uuid4()}"


@pytest.fixture
def make_anchor(embedder: ActionEmbedder):  # type: ignore[no-untyped-def]
    """Build an anchor directly, bypassing decomposition."""

    def _make(
        session_id: str,
        text: str = "Summarise the quarterly sales report for the leadership team.",
        constraints: list[str] | None = None,
        disallowed: list[str] | None = None,
    ) -> IntentAnchor:
        return IntentAnchor(
            session_id=session_id,
            raw_text=text,
            embedding=embedder.embed_text(text),
            goal=text,
            constraints=constraints or [],
            disallowed_actions=disallowed or [],
            risk_level=RiskLevel.LOW,
            decomposition_source="test",
        )

    return _make


# ---- Mock upstream MCP server --------------------------------------------


def create_mock_upstream() -> FastAPI:
    """A minimal MCP server exposing `echo`, used to prove the proxy is transparent."""
    upstream = FastAPI(title="mock-upstream-mcp")
    upstream.state.calls = []

    @upstream.post("/mcp")
    async def handle(payload: dict[str, Any]) -> dict[str, Any]:
        upstream.state.calls.append(payload)
        method = payload.get("method")
        request_id = payload.get("id")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "mock-upstream", "version": "1.0.0"},
                    "capabilities": {"tools": {}},
                },
            }
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
                        {"name": "echo", "description": "Echoes its input back."},
                        {"name": "read_file", "description": "Reads a file."},
                    ]
                },
            }
        if method in ("tools/call", "tools/execute"):
            params = payload.get("params", {})
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {"type": "text", "text": f"echo:{params.get('arguments', {})}"}
                    ],
                    "isError": False,
                },
            }
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }

    return upstream


@pytest.fixture
def mock_upstream() -> FastAPI:
    return create_mock_upstream()
