"""Isolated async DB session for alerts tests.

Uses NullPool so every AsyncSessionLocal() call gets its own connection
with no sharing across tests — eliminates the asyncpg 'another operation
is in progress' error that occurs when tests share the app's global pool.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

from app.core.config import settings


# Separate engine — NullPool means no connection reuse across sessions
_test_engine = create_async_engine(
    settings.database_url,
    poolclass=NullPool,
    echo=False,
)

TestSessionLocal = async_sessionmaker(
    _test_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)
