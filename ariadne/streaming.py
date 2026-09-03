# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""In-process fan-out of live drift updates to dashboard subscribers."""

from __future__ import annotations

import asyncio
from collections import deque

from ariadne.drift.schemas import DriftUpdate
from ariadne.logging import get_logger

logger = get_logger(__name__)

#: Per-subscriber buffer. A dashboard that stops reading loses old frames
#: rather than applying backpressure to the interception hot path.
SUBSCRIBER_QUEUE_SIZE = 256

#: Replayed to a client that connects mid-run so its chart is not blank.
REPLAY_BUFFER_SIZE = 200


class DriftStreamHub:
    """Publishes DriftUpdate events to WebSocket subscribers per session.

    Publishing is synchronous and non-blocking by design: it is called from
    the interception path, where a slow consumer must never add latency to a
    tool call.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[DriftUpdate]]] = {}
        self._global_subscribers: set[asyncio.Queue[DriftUpdate]] = set()
        self._history: dict[str, deque[DriftUpdate]] = {}

    def publish(self, update: DriftUpdate) -> None:
        """Fan an update out to every interested subscriber. Never raises."""
        history = self._history.setdefault(update.session_id, deque(maxlen=REPLAY_BUFFER_SIZE))
        history.append(update)

        targets = list(self._subscribers.get(update.session_id, set())) + list(
            self._global_subscribers
        )
        for queue in targets:
            try:
                queue.put_nowait(update)
            except asyncio.QueueFull:
                logger.warning(
                    "streaming.subscriber_lagging",
                    session_id=update.session_id,
                    step_index=update.step_index,
                )

    def subscribe(self, session_id: str | None = None) -> asyncio.Queue[DriftUpdate]:
        """Register a subscriber. `None` subscribes to every session (alert bar)."""
        queue: asyncio.Queue[DriftUpdate] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        if session_id is None:
            self._global_subscribers.add(queue)
        else:
            self._subscribers.setdefault(session_id, set()).add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[DriftUpdate], session_id: str | None = None) -> None:
        if session_id is None:
            self._global_subscribers.discard(queue)
            return
        subscribers = self._subscribers.get(session_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            del self._subscribers[session_id]

    def history(self, session_id: str) -> list[DriftUpdate]:
        """Buffered updates for a session, for replay on connect."""
        return list(self._history.get(session_id, ()))

    def discard_session(self, session_id: str) -> None:
        self._history.pop(session_id, None)

    @property
    def subscriber_count(self) -> int:
        return sum(len(group) for group in self._subscribers.values()) + len(
            self._global_subscribers
        )
