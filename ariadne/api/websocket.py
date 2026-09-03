# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Live drift streaming to the dashboard."""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ariadne.drift.schemas import DriftUpdate
from ariadne.logging import get_logger
from ariadne.streaming import DriftStreamHub

logger = get_logger(__name__)

router = APIRouter(tags=["websocket"])

#: Sent when no update has flowed for this long, so proxies and load balancers
#: do not reap an idle-but-healthy dashboard connection.
KEEPALIVE_SECONDS = 20.0


@router.websocket("/runs/{session_id}/live")
async def stream_run(websocket: WebSocket, session_id: str) -> None:
    """Stream a single run's drift updates, replaying what has already happened."""
    await _stream(websocket, session_id)


@router.websocket("/alerts/live")
async def stream_alerts(websocket: WebSocket) -> None:
    """Stream ESCALATE/BLOCK events across every active session."""
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
