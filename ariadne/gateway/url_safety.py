# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Blocks SSRF through the "connect your agent" upstream URL.

An org admin controls `upstream_mcp_url` (ariadne/api/connect.py), and
"Test Connection" makes *this server* issue an outbound HTTP request to
whatever URL is given. Without this check, a malicious or compromised org
account could point that request at Ariadne's own internal network --
a cloud metadata endpoint, another tenant's internal service, localhost
admin ports -- and use the reachable/unreachable + latency response as an
oracle for what's there. Rejecting every resolved address that isn't a
plain public unicast address closes that off. Only POST /upstream/test
calls this -- PUT /upstream just stores the string and never connects
anywhere itself, so there is nothing to validate there yet (see connect.py's
module docstring: the live proxy doesn't read the stored URL at all today).

`resolve_pinned_upstream` exists (rather than just validating and letting
the HTTP client re-resolve DNS itself) to close a DNS-rebinding
time-of-check-to-time-of-use gap: a hostname under attacker control can
answer the validation lookup with a safe public IP and a second,
independent lookup moments later -- the one the HTTP client would
otherwise perform when actually connecting -- with 127.0.0.1 or an
internal address, since nothing requires the two lookups to agree.
Resolving exactly once and handing the caller the literal IP to connect to
(ariadne/gateway/upstream_client.py does exactly that, never re-resolving)
removes the second lookup entirely.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse


class UnsafeUpstreamURLError(ValueError):
    """The given URL resolves somewhere Ariadne must never connect to."""


@dataclass(frozen=True)
class ResolvedUpstream:
    scheme: str
    hostname: str
    port: int
    #: The literal IP address to actually connect to -- already validated
    #: safe. Callers must connect to this exact address, never re-resolve
    #: `hostname` themselves.
    ip: str


def _is_unsafe(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_private
        or addr.is_unspecified
        or addr.is_reserved
        or addr.is_multicast
    )


async def resolve_pinned_upstream(url: str) -> ResolvedUpstream:
    """Resolve `url`'s host exactly once, verify every candidate address is
    a plain public unicast address, and return one to connect to.

    Raises UnsafeUpstreamURLError on a bad scheme, missing host, resolution
    failure, or any resolved (or attacker-offered) disallowed address.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUpstreamURLError(f"unsupported URL scheme {parsed.scheme!r}")
    if not parsed.hostname:
        raise UnsafeUpstreamURLError("URL has no hostname")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        # getaddrinfo is blocking -- run off the event loop like any other
        # real DNS resolution would need to be. This is the ONLY resolution
        # of this hostname for this request; the caller must reuse `.ip`
        # rather than resolving again.
        infos = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, port)
    except socket.gaierror as exc:
        raise UnsafeUpstreamURLError(f"could not resolve host {parsed.hostname!r}") from exc

    if not infos:
        raise UnsafeUpstreamURLError(f"could not resolve host {parsed.hostname!r}")

    safe_ip: str | None = None
    for _family, _type, _proto, _canonname, sockaddr in infos:
        raw_ip = str(sockaddr[0])
        addr = ipaddress.ip_address(raw_ip)
        if _is_unsafe(addr):
            raise UnsafeUpstreamURLError(
                f"host {parsed.hostname!r} resolves to a disallowed address ({raw_ip})"
            )
        if safe_ip is None:
            safe_ip = raw_ip

    if safe_ip is None:  # unreachable: every entry above either raised or set safe_ip
        raise UnsafeUpstreamURLError(f"could not resolve host {parsed.hostname!r}")
    return ResolvedUpstream(scheme=parsed.scheme, hostname=parsed.hostname, port=port, ip=safe_ip)


async def validate_public_upstream_url(url: str) -> None:
    """Raise UnsafeUpstreamURLError unless every address `url`'s host
    resolves to is a plain public unicast address.

    A fast-fail check for callers that only want the validation, not a
    pinned connection target (e.g. an early-exit error message before doing
    other work). Prefer `resolve_pinned_upstream` for anything that goes on
    to actually connect -- calling both would re-resolve DNS a second time,
    reopening the rebinding window this module exists to close.
    """
    await resolve_pinned_upstream(url)
