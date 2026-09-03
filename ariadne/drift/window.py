# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Sliding window over an execution sequence's drift distances."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator

from ariadne.drift.schemas import TrajectoryPoint


class SlidingWindow:
    """Bounded FIFO of the most recent drift distances for one session.

    The window is what makes slope meaningful: it bounds how far back an
    escalation has to reach to still be visible, so a long benign run does
    not dilute a five-step attack into a flat line.
    """

    __slots__ = ("_points", "_max_size", "session_id")

    def __init__(self, session_id: str, max_size: int = 5) -> None:
        if max_size < 2:
            raise ValueError(f"window size must be >= 2, got {max_size}")
        self.session_id = session_id
        self._max_size = max_size
        self._points: deque[TrajectoryPoint] = deque(maxlen=max_size)

    def push(self, step_index: int, raw_distance: float) -> TrajectoryPoint:
        """Append a sample, evicting the oldest once the window is full."""
        point = TrajectoryPoint(step_index=step_index, raw_distance=raw_distance)
        self._points.append(point)
        return point

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def points(self) -> list[TrajectoryPoint]:
        return list(self._points)

    @property
    def distances(self) -> list[float]:
        return [point.raw_distance for point in self._points]

    @property
    def step_indices(self) -> list[int]:
        return [point.step_index for point in self._points]

    @property
    def is_full(self) -> bool:
        return len(self._points) == self._max_size

    def clear(self) -> None:
        self._points.clear()

    def __len__(self) -> int:
        return len(self._points)

    def __iter__(self) -> Iterator[TrajectoryPoint]:
        return iter(self._points)

    def __repr__(self) -> str:
        return (
            f"SlidingWindow(session_id={self.session_id!r}, "
            f"size={len(self._points)}/{self._max_size})"
        )


class WindowRegistry:
    """One window per live session, created on demand."""

    def __init__(self, max_size: int = 5) -> None:
        self._max_size = max_size
        self._windows: dict[str, SlidingWindow] = {}

    def get(self, session_id: str) -> SlidingWindow:
        window = self._windows.get(session_id)
        if window is None:
            window = SlidingWindow(session_id, self._max_size)
            self._windows[session_id] = window
        return window

    def discard(self, session_id: str) -> None:
        """Release a finished session's window."""
        self._windows.pop(session_id, None)

    def __len__(self) -> int:
        return len(self._windows)
