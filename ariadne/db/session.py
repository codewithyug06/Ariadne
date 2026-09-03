# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Async SQLAlchemy engine and session management."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ariadne.config import Settings, get_settings
from ariadne.db.models import Base
from ariadne.logging import get_logger

logger = get_logger(__name__)


class Database:
    """Owns the engine and session factory for the process."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._ensure_sqlite_directory(self._settings.database_url)
        self._engine: AsyncEngine = create_async_engine(
            self._settings.database_url,
            echo=False,
            future=True,
            pool_pre_ping=True,
        )
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )

    @staticmethod
    def _ensure_sqlite_directory(database_url: str) -> None:
        """SQLite will not create a missing parent directory; do it for it."""
        marker = "sqlite+aiosqlite:///"
        if not database_url.startswith(marker):
            return
        raw_path = database_url[len(marker) :]
        if raw_path in ("", ":memory:") or raw_path.startswith(":memory:"):
            return
        parent = Path(raw_path).expanduser().resolve().parent
        parent.mkdir(parents=True, exist_ok=True)

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    async def create_all(self) -> None:
        """Create tables if absent.

        Alembic owns schema evolution; this exists so a fresh dev box and the
        test suite start without a migration step.
        """
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        logger.info("db.schema_ready", url=_redact(self._settings.database_url))

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Transactional scope around a series of operations."""
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def close(self) -> None:
        await self._engine.dispose()
        logger.info("db.closed")


def _redact(database_url: str) -> str:
    """Strip credentials before a URL reaches the logs."""
    if "@" not in database_url:
        return database_url
    scheme, _, remainder = database_url.partition("://")
    _credentials, _, host = remainder.rpartition("@")
    return f"{scheme}://***@{host}"
