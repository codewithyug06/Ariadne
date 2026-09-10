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

import pytest
import pytest_asyncio
import uvicorn

from ariadne.gateway.upstream_client import (
    MAX_UPSTREAM_HEADERS,
    UpstreamMCPClient,
    validate_upstream_headers,
)
from ariadne.gateway.url_safety import ResolvedUpstream

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


def _pin_loopback(url: str, port: int) -> ResolvedUpstream:
    # White-box: this file tests the connection mechanics (pinned dial,
    # capped response read, JSON parsing) one layer below the SSRF policy
    # in url_safety.py -- which correctly refuses loopback on its own, and
    # is tested separately in test_url_safety.py. Passing `resolved`
    # bypasses that policy check here on purpose, the same way
    # ariadne/api/connect.py's own resolve step would for a real public
    # host, just pointed at our real local test server instead.
    return ResolvedUpstream(scheme="http", hostname="127.0.0.1", port=port, ip="127.0.0.1")


async def test_reaches_a_real_server_and_reports_its_info(real_mock_upstream_url: str) -> None:
    port = int(real_mock_upstream_url.rsplit(":", 1)[1].split("/")[0])
    client = UpstreamMCPClient()
    result = await client.test_connection(
        real_mock_upstream_url, {}, resolved=_pin_loopback(real_mock_upstream_url, port)
    )
    assert result.reachable is True
    assert result.latency_ms is not None
    assert result.server_info is not None
    assert result.server_info["name"] == "mock-upstream"
    assert result.error is None


async def test_connection_refused_is_reported_as_unreachable() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]

    url = f"http://127.0.0.1:{closed_port}/mcp"
    client = UpstreamMCPClient()
    result = await client.test_connection(url, {}, resolved=_pin_loopback(url, closed_port))
    assert result.reachable is False
    assert result.error is not None


class TestHeaderCaps:
    def test_too_many_headers_rejected(self) -> None:
        headers = {f"X-Header-{i}": "v" for i in range(MAX_UPSTREAM_HEADERS + 1)}
        with pytest.raises(ValueError, match="too many headers"):
            validate_upstream_headers(headers)

    def test_oversized_header_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="too long"):
            validate_upstream_headers({"Authorization": "x" * 5000})

    def test_crlf_in_header_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="control character"):
            validate_upstream_headers({"Authorization": "Bearer x\r\nX-Injected: 1"})

    async def test_too_many_headers_reported_by_test_connection(
        self, real_mock_upstream_url: str
    ) -> None:
        port = int(real_mock_upstream_url.rsplit(":", 1)[1].split("/")[0])
        headers = {f"X-Header-{i}": "v" for i in range(MAX_UPSTREAM_HEADERS + 1)}
        client = UpstreamMCPClient()
        result = await client.test_connection(
            real_mock_upstream_url, headers, resolved=_pin_loopback(real_mock_upstream_url, port)
        )
        assert result.reachable is False
        assert "too many headers" in (result.error or "")


class TestResponseSizeCap:
    async def test_oversized_response_is_reported_as_unreachable(self) -> None:
        from fastapi import FastAPI  # noqa: PLC0415

        oversized_app = FastAPI()

        @oversized_app.post("/mcp")
        async def _oversized() -> dict[str, object]:
            return {"jsonrpc": "2.0", "id": "1", "result": {"padding": "x" * 200_000}}

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        config = uvicorn.Config(oversized_app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.02)

        try:
            url = f"http://127.0.0.1:{port}/mcp"
            client = UpstreamMCPClient()
            result = await client.test_connection(url, {}, resolved=_pin_loopback(url, port))
            assert result.reachable is False
            assert "exceeded" in (result.error or "")
        finally:
            server.should_exit = True
            await task
