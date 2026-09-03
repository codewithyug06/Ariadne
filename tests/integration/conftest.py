# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Integration fixtures: a live Ariadne app wired to a mock upstream MCP server."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import numpy as np
import pytest_asyncio
from fastapi import FastAPI

from ariadne.config import Settings
from ariadne.drift.embedder import ActionEmbedder
from ariadne.main import create_app
from tests.conftest import DeterministicEmbedder, create_mock_upstream


@dataclass
class Stack:
    """Everything a test needs to drive and inspect a running Ariadne."""

    app: FastAPI
    client: httpx.AsyncClient
    upstream: FastAPI
    embedder: DeterministicEmbedder
    settings: Settings

    def on_mission(self, *texts: str) -> None:
        """Pin these renderings close to the anchor (cosine distance ~0.05)."""
        for text in texts:
            self.embedder.pin(text, _near(self._anchor_vector(), 0.05))

    def off_mission(self, *texts: str, distance: float = 0.95) -> None:
        """Pin these renderings far from the anchor."""
        for text in texts:
            self.embedder.pin(text, _near(self._anchor_vector(), distance))

    def escalating(self, texts: list[str], start: float = 0.30, step: float = 0.20) -> None:
        """Pin a sequence whose distance climbs steadily — a slow-burn shape."""
        for index, text in enumerate(texts):
            self.embedder.pin(text, _near(self._anchor_vector(), min(1.0, start + index * step)))

    def set_anchor_text(self, text: str) -> None:
        self._anchor_text = text
        self.embedder.pin(text, _unit_vector(seed=7))

    def _anchor_vector(self) -> np.ndarray:
        return self.embedder.embed_text(getattr(self, "_anchor_text", ""))


def _unit_vector(seed: int, dimension: int = 384) -> np.ndarray:
    rng = np.random.default_rng(seed)
    vector = rng.normal(size=dimension)
    return (vector / np.linalg.norm(vector)).astype(np.float32)


def _near(anchor: np.ndarray, distance: float, seed: int | None = None) -> np.ndarray:
    """A unit vector at exactly `distance` cosine distance from `anchor`."""
    rng = np.random.default_rng(seed if seed is not None else int(distance * 10_000) + 1)
    orthogonal = rng.normal(size=anchor.shape).astype(np.float64)
    orthogonal -= anchor * float(np.dot(orthogonal, anchor))
    orthogonal /= np.linalg.norm(orthogonal)
    similarity = 1.0 - distance
    vector = similarity * anchor + np.sqrt(max(0.0, 1.0 - similarity**2)) * orthogonal
    return (vector / np.linalg.norm(vector)).astype(np.float32)


@pytest_asyncio.fixture
async def stack(settings: Settings) -> AsyncIterator[Stack]:
    """Boot Ariadne with deterministic embeddings and a mock upstream.

    Embeddings are pinned rather than computed so integration tests assert on
    proxy behaviour, not on how a particular sentence-transformer happens to
    place two strings. Embedding quality is measured separately, by the eval
    harness against the real model.
    """
    upstream = create_mock_upstream()
    backend = DeterministicEmbedder(settings.embedding_dimension)

    # Seed the singleton before lifespan so the app picks up the test backend.
    ActionEmbedder.reset()
    ActionEmbedder._instance = ActionEmbedder(backend=backend, settings=settings)  # noqa: SLF001

    app = create_app(settings)

    async with app.router.lifespan_context(app):
        upstream_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=upstream), base_url="http://upstream.test"
        )
        app.state.http_client = upstream_client
        app.state.proxy._client = upstream_client  # noqa: SLF001

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://ariadne.test"
        ) as client:
            yield Stack(
                app=app,
                client=client,
                upstream=upstream,
                embedder=backend,
                settings=settings,
            )

        await upstream_client.aclose()

    ActionEmbedder.reset()


async def initialize_session(
    stack: Stack, session_id: str, user_request: str
) -> httpx.Response:
    """Perform the MCP handshake that establishes the intent anchor."""
    stack.set_anchor_text(user_request)
    return await stack.client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "userRequest": user_request,
                "clientInfo": {"name": "test-orchestrator", "version": "1.0"},
            },
        },
        headers={"X-Ariadne-Session-Id": session_id},
    )


async def call_tool(
    stack: Stack,
    session_id: str,
    tool_name: str,
    arguments: dict[str, object] | None = None,
    request_id: int = 1,
) -> httpx.Response:
    return await stack.client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments or {}},
        },
        headers={"X-Ariadne-Session-Id": session_id},
    )


def rendering(step_index: int, tool_name: str, arguments: dict[str, object] | None = None) -> str:
    """The exact string the embedder will see for a given call."""
    from ariadne.proxy.schemas import ToolCall  # noqa: PLC0415

    return ToolCall(
        session_id="pin",
        step_index=step_index,
        tool_name=tool_name,
        arguments=arguments or {},
    ).to_natural_language()
