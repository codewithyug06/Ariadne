# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""ariadne/gateway/upstream_client.py's UpstreamMCPClient, called directly.

SSRF protection (ariadne/gateway/url_safety.py) lives at the API layer
(ariadne/api/connect.py), not in this client -- so
tests/integration/test_connect_api.py can no longer exercise the genuinely-
reachable path through the route (its only real TCP listener available in
CI is on 127.0.0.1, which the route now correctly refuses to touch). This
file proves the client itself still works against a real server, one layer
below that gate.
"""

from __future__ import annotations

import asyncio
import socket
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
import uvicorn

from ariadne.gateway.upstream_client import UpstreamMCPClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from mock_upstream_server import app as mock_app  # noqa: E402


@pytest_asyncio.fixture
async def real_mock_upstream_url() -> AsyncIterator[str]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    config = uvicorn.Config(mock_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)

    yield f"http://127.0.0.1:{port}/mcp"

    server.should_exit = True
    await task


async def test_reaches_a_real_server_and_reports_its_info(real_mock_upstream_url: str) -> None:
    client = UpstreamMCPClient()
    result = await client.test_connection(real_mock_upstream_url, {})
    assert result.reachable is True
    assert result.latency_ms is not None
    assert result.server_info is not None
    assert result.server_info["name"] == "mock-upstream"
    assert result.error is None


async def test_connection_refused_is_reported_as_unreachable() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]

    client = UpstreamMCPClient()
    result = await client.test_connection(f"http://127.0.0.1:{closed_port}/mcp", {})
    assert result.reachable is False
    assert result.error is not None
