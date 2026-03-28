"""Database queries for the events module — pure data access, no business logic."""
from sqlalchemy.ext.asyncio import AsyncSession


class EventRepository:
    """Handles all SQL operations for Event records."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
