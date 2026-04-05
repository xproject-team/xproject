"""Database queries for the inventory module — pure data access, no business logic."""
from sqlalchemy.ext.asyncio import AsyncSession


class InventoryRepository:
    """Handles all SQL operations for InventoryItem records."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
