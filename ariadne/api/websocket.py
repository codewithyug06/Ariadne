# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Live drift streaming to the dashboard."""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ariadne.auth.ws_tickets import consume_ticket
from ariadne.drift.schemas import DriftUpdate
from ariadne.logging import get_logger
from ariadne.streaming import DriftStreamHub

logger = get_logger(__name__)

router = APIRouter(tags=["websocket"])

#: Sent when no update has flowed for this long, so proxies and load balancers
#: do not reap an idle-but-healthy dashboard connection.
KEEPALIVE_SECONDS = 20.0

#: A browser's WebSocket handshake cannot set custom headers, so a credential
#: has to travel in the URL. Rather than put the JWT access token itself
#: there (a query string ends up in access logs and browser history — a
#: leaked log line would leak a live, Bearer-equivalent credential), the
#: dashboard exchanges its access token for a single-use ticket over a
#: normal, header-authenticated POST /api/v1/auth/ws-ticket call first. Only
#: the dashboard uses these WebSocket routes; machine callers hitting /mcp
#: never need this path.
POLICY_VIOLATION_CLOSE_CODE = 1008


def _authorized(websocket: WebSocket, ticket: str | None) -> bool:
    settings = websocket.app.state.settings
    if not (settings.api_keys or settings.jwt_secret_key):
        return True  # auth disabled entirely (dev, nothing configured)
    if ticket is None:
        return False
    return consume_ticket(ticket) is not None


@router.websocket("/runs/{session_id}/live")
async def stream_run(websocket: WebSocket, session_id: str, ticket: str | None = None) -> None:
    """Stream a single run's drift updates, replaying what has already happened."""
    if not _authorized(websocket, ticket):
        await websocket.close(code=POLICY_VIOLATION_CLOSE_CODE)
        return
    await _stream(websocket, session_id)


@router.websocket("/alerts/live")
async def stream_alerts(websocket: WebSocket, ticket: str | None = None) -> None:
    """Stream ESCALATE/BLOCK events across every active session."""
    if not _authorized(websocket, ticket):
        await websocket.close(code=POLICY_VIOLATION_CLOSE_CODE)
        return
    await _stream(websocket, None, alerts_only=True)


async def _stream(websocket: WebSocket, session_id: str | None, alerts_only: bool = False) -> None:
    hub: DriftStreamHub = websocket.app.state.stream_hub
    await websocket.accept()
    queue = hub.subscribe(session_id)

    try:
        if session_id is not None:
            for buffered in hub.history(session_id):
                await websocket.send_json(buffered.model_dump(mode="json"))

        while True:
            update: DriftUpdate
            try:
                update = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
            except TimeoutError:
                await websocket.send_json({"type": "keepalive"})
                continue

            if alerts_only and update.enforcement_action not in ("ESCALATE", "BLOCK"):
                continue
            await websocket.send_json(update.model_dump(mode="json"))

    except WebSocketDisconnect:
        logger.debug("websocket.disconnected", session_id=session_id)
    except (RuntimeError, ConnectionError) as exc:
        # Client vanished mid-send, or the transport closed under us.
        logger.debug(
            "websocket.transport_closed",
            session_id=session_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
    finally:
        hub.unsubscribe(queue, session_id)
        with contextlib.suppress(RuntimeError):
            await websocket.close()
