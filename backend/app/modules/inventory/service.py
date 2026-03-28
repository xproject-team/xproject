"""Business logic for the inventory module — stock tracking, depletion, restock logic."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory.repository import InventoryRepository


class InventoryService:
    """Contains all business logic for inventory operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.repo = InventoryRepository(db)
