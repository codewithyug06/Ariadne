# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Short-lived, single-use tickets for authenticating WebSocket handshakes.

A browser's WebSocket handshake cannot set an Authorization header, so the
dashboard used to pass its JWT access token as a `?token=` query parameter
instead. That put a real, Bearer-equivalent credential into browser history
and any access log the connection passed through. This module replaces it:
the dashboard exchanges its access token for a ticket (over a normal,
header-authenticated REST call), then opens the WebSocket with `?ticket=`
instead. A leaked ticket is worthless within seconds and cannot be replayed.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

#: Long enough to cover the REST round-trip + WebSocket handshake, short
#: enough that a leaked ticket (log line, proxy trace) is useless by the
#: time anyone could act on it.
TICKET_TTL_SECONDS = 30.0


@dataclass(slots=True, frozen=True)
class TicketPayload:
    user_id: str
    role: str
    organization_id: str


_tickets: dict[str, tuple[TicketPayload, float]] = {}


def _evict_expired() -> None:
    now = time.monotonic()
    expired = [ticket for ticket, (_, expires_at) in _tickets.items() if expires_at <= now]
    for ticket in expired:
        del _tickets[ticket]


def issue_ticket(user_id: str, role: str, organization_id: str) -> str:
    _evict_expired()
    ticket = secrets.token_urlsafe(32)
    _tickets[ticket] = (
        TicketPayload(user_id=user_id, role=role, organization_id=organization_id),
        time.monotonic() + TICKET_TTL_SECONDS,
    )
    return ticket


def consume_ticket(ticket: str) -> TicketPayload | None:
    """Validate and immediately invalidate a ticket — single use only."""
    _evict_expired()
    entry = _tickets.pop(ticket, None)
    if entry is None:
        return None
    payload, expires_at = entry
    if expires_at <= time.monotonic():
        return None
    return payload
