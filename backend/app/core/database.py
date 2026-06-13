"""Async SQLAlchemy engine and session factory — all DB sessions come from here."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


def _to_async_url(url: str) -> str:
    """Railway / Heroku-style URLs come back as ``postgres://`` or
    ``postgresql://`` (sync). SQLAlchemy's async engine needs the
    ``+asyncpg`` driver suffix. Rewrite here so a single DATABASE_URL
    env var works locally and in prod without manual mangling."""
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


engine = create_async_engine(_to_async_url(settings.database_url), echo=settings.debug)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides a scoped async database session."""
    async with AsyncSessionLocal() as session:
        yield session
