"""Business logic for the anomaly detection module — runs detectors and persists findings."""
from sqlalchemy.ext.asyncio import AsyncSession


class AnomalyService:
    """Orchestrates anomaly detectors and stores detected anomalies."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
