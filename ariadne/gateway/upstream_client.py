# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Talks to a customer's own MCP tool server on their behalf.

Scope note: only `test_connection` is implemented. The original spec this
was adapted from also asked for `forward_tool_call`, used by a full
multi-tenant MCP gateway that authenticates callers, resolves their org's
upstream, and forwards intercepted calls there instead of the single
global `settings.upstream_mcp_url` ariadne/proxy/mcp_proxy.py forwards
every session to today. Building `forward_tool_call` without that gateway
wiring it in would be dead code -- nothing would ever call it, and nothing
here changes what a real tool call does. `test_connection` stands alone:
it powers ariadne/api/connect.py's "Test Connection" button, which is a
complete, independently useful feature (confirm a customer's tool server
is reachable before they wire anything else up).

Uses httpcore directly, not httpx, so the TCP connection can be pinned to
the exact IP `ariadne.gateway.url_safety.resolve_pinned_upstream` already
validated -- never re-resolving the hostname. Without that, a second,
independent DNS lookup at connect time could hand back a different
(unsafe) address than the one just checked (DNS rebinding). TLS
certificate verification and SNI still use the real hostname; only the
TCP dial target is pinned.
"""

from __future__ import annotations

import json as _json
import ssl
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpcore

from ariadne.gateway.url_safety import (
    ResolvedUpstream,
    UnsafeUpstreamURLError,
    resolve_pinned_upstream,
)

#: Hard cap on how much of an upstream's response this will ever read. A
#: customer's tool server is not a trusted party -- a compromised or simply
#: misbehaving one could otherwise stream gigabytes into memory from a
#: single connection test.
_MAX_RESPONSE_BYTES = 65_536

#: Defensive caps on the headers an org admin can ask this to send to their
#: own upstream. Not about protecting the admin's own account -- about
#: bounding how much data this server will hold in memory / put on the wire
#: for a single outbound request, and refusing header names/values with
#: embedded control characters (CR/LF) that a lower-level HTTP
#: implementation might not itself guard against.
MAX_UPSTREAM_HEADERS = 20
MAX_HEADER_NAME_LENGTH = 128
MAX_HEADER_VALUE_LENGTH = 4096


class InvalidUpstreamHeadersError(ValueError):
    """Rejected before ever attempting to send these headers anywhere."""


def validate_upstream_headers(headers: dict[str, str]) -> None:
    if len(headers) > MAX_UPSTREAM_HEADERS:
        raise InvalidUpstreamHeadersError(
            f"too many headers ({len(headers)} > {MAX_UPSTREAM_HEADERS})"
        )
    for name, value in headers.items():
        if not name or len(name) > MAX_HEADER_NAME_LENGTH:
            raise InvalidUpstreamHeadersError(f"invalid header name length: {name!r}")
        if len(value) > MAX_HEADER_VALUE_LENGTH:
            raise InvalidUpstreamHeadersError(f"header {name!r} value too long")
        if any(ch in name for ch in "\r\n") or any(ch in value for ch in "\r\n"):
            raise InvalidUpstreamHeadersError(f"header {name!r} contains a control character")


@dataclass(frozen=True)
class ConnectionTestResult:
    reachable: bool
    latency_ms: float | None
    server_info: dict[str, Any] | None
    error: str | None


class _PinnedBackend(httpcore.AnyIOBackend):
    """A network backend that always dials one fixed IP.

    httpcore calls `connect_tcp(host, port, ...)` with the request's
    hostname, then separately negotiates TLS using that same hostname for
    SNI/certificate verification -- overriding only the dial target here
    (never what TLS verifies against) is what closes the DNS-rebinding gap
    without weakening certificate validation.
    """

    def __init__(self, pinned_ip: str) -> None:
        super().__init__()
        self._pinned_ip = pinned_ip

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 -- overrides base class signature
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> Any:
        return await super().connect_tcp(
            self._pinned_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class UpstreamMCPClient:
    """Speaks JSON-RPC 2.0 to a customer-configured MCP tool server."""

    async def test_connection(
        self,
        upstream_url: str,
        upstream_headers: dict[str, str],
        *,
        resolved: ResolvedUpstream | None = None,
    ) -> ConnectionTestResult:
        """Send an MCP `initialize` request and report whether it answered.

        Used by the dashboard's "Test Connection" button before an org's
        upstream config is trusted for anything else.

        `resolved`: pass this when the caller already ran
        `resolve_pinned_upstream` itself (ariadne/api/connect.py does, to
        return a clean 400 before this is even called) -- resolving DNS a
        second time here would reopen the exact rebinding window pinning
        exists to close. Left unset, this resolves on its own, for callers
        that just want a one-shot reachability check.
        """
        try:
            validate_upstream_headers(upstream_headers)
        except InvalidUpstreamHeadersError as exc:
            return ConnectionTestResult(
                reachable=False, latency_ms=None, server_info=None, error=str(exc)
            )

        if resolved is None:
            try:
                resolved = await resolve_pinned_upstream(upstream_url)
            except UnsafeUpstreamURLError as exc:
                return ConnectionTestResult(
                    reachable=False, latency_ms=None, server_info=None, error=str(exc)
                )

        payload = _json.dumps(
            {
                "jsonrpc": "2.0",
                "id": str(uuid4()),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "ariadne-connection-tester"},
                },
            }
        ).encode()
        host_header = resolved.hostname.encode()
        if resolved.port not in (80, 443):
            host_header += f":{resolved.port}".encode()
        headers: list[tuple[bytes, bytes]] = [
            (b"host", host_header),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
        ]
        headers.extend((name.encode(), value.encode()) for name, value in upstream_headers.items())

        ssl_context = ssl.create_default_context() if resolved.scheme == "https" else None
        pool = httpcore.AsyncConnectionPool(
            network_backend=_PinnedBackend(resolved.ip), ssl_context=ssl_context, retries=0
        )
        parsed_url = httpcore.URL(
            scheme=resolved.scheme.encode(),
            host=resolved.hostname.encode(),
            port=resolved.port,
            target=_request_target(upstream_url).encode(),
        )
        request = httpcore.Request(
            method="POST",
            url=parsed_url,
            headers=headers,
            content=payload,
            extensions={
                "timeout": {"connect": 5.0, "read": 10.0, "write": 10.0, "pool": 10.0}
            },
        )
        started = time.perf_counter()
        response = None
        try:
            # handle_async_request (not the .request() convenience method,
            # which eagerly reads the whole body with no size limit) so the
            # response can be read through _read_capped below instead.
            response = await pool.handle_async_request(request)
            latency_ms = (time.perf_counter() - started) * 1000.0
            if response.status >= 400:
                return ConnectionTestResult(
                    reachable=False,
                    latency_ms=None,
                    server_info=None,
                    error=f"upstream returned status {response.status}",
                )
            body = await _read_capped(response)
            data = _json.loads(body)
        except (httpcore.ConnectError, httpcore.ConnectTimeout, httpcore.TimeoutException) as exc:
            return ConnectionTestResult(
                reachable=False, latency_ms=None, server_info=None, error=str(exc)
            )
        except ValueError as exc:  # non-JSON or oversized response body
            return ConnectionTestResult(
                reachable=False, latency_ms=None, server_info=None, error=str(exc)
            )
        finally:
            await pool.aclose()

        server_info = data.get("result", {}).get("serverInfo") if isinstance(data, dict) else None
        return ConnectionTestResult(
            reachable=True,
            latency_ms=round(latency_ms, 1),
            server_info=server_info if isinstance(server_info, dict) else None,
            error=None,
        )


def _request_target(url: str) -> str:
    parts = urlsplit(url)
    target = parts.path or "/"
    if parts.query:
        target += f"?{parts.query}"
    return target


async def _read_capped(response: httpcore.Response) -> bytes:
    total = 0
    chunks: list[bytes] = []
    try:
        async for chunk in response.aiter_stream():
            total += len(chunk)
            if total > _MAX_RESPONSE_BYTES:
                raise ValueError(f"upstream response exceeded {_MAX_RESPONSE_BYTES} bytes")
            chunks.append(chunk)
    finally:
        await response.aclose()
    return b"".join(chunks)
