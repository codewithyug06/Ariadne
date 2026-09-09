# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Blocks SSRF through the "connect your agent" upstream URL.

An org admin controls `upstream_mcp_url` (ariadne/api/connect.py), and
"Test Connection" makes *this server* issue an outbound HTTP request to
whatever URL is given. Without this check, a malicious or compromised org
account could point that request at Ariadne's own internal network --
a cloud metadata endpoint, another tenant's internal service, localhost
admin ports -- and use the reachable/unreachable + latency response as an
oracle for what's there. Rejecting every resolved address that isn't a plain public unicast address
closes that off. Only POST /upstream/test calls this -- PUT /upstream just
stores the string and never connects anywhere itself, so there is nothing
to validate there yet (see connect.py's module docstring: the live proxy
doesn't read the stored URL at all today).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUpstreamURLError(ValueError):
    """The given URL resolves somewhere Ariadne must never connect to."""


def _is_unsafe(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_private
        or addr.is_unspecified
        or addr.is_reserved
        or addr.is_multicast
    )


async def validate_public_upstream_url(url: str) -> None:
    """Raise UnsafeUpstreamURLError unless every address `url`'s host
    resolves to is a plain public unicast address."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUpstreamURLError(f"unsupported URL scheme {parsed.scheme!r}")
    if not parsed.hostname:
        raise UnsafeUpstreamURLError("URL has no hostname")

    try:
        # getaddrinfo is blocking -- run off the event loop like any other
        # real DNS resolution would need to be.
        infos = await asyncio.to_thread(
            socket.getaddrinfo,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )
    except socket.gaierror as exc:
        raise UnsafeUpstreamURLError(f"could not resolve host {parsed.hostname!r}") from exc

    for _family, _type, _proto, _canonname, sockaddr in infos:
        raw_ip = sockaddr[0]
        addr = ipaddress.ip_address(raw_ip)
        if _is_unsafe(addr):
            raise UnsafeUpstreamURLError(
                f"host {parsed.hostname!r} resolves to a disallowed address ({raw_ip})"
            )
