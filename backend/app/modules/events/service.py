"""Business logic for the events module — orchestrates repository calls."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.repository import EventRepository


class EventService:
    """Contains all business logic for event operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.repo = EventRepository(db)
