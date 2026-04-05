"""Business logic for the alerts module — triggers evaluation, manages acknowledgements."""
from sqlalchemy.ext.asyncio import AsyncSession


class AlertService:
    """Orchestrates alert evaluation and delivery."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
