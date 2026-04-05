"""Business logic for the predictions module — orchestrates feature engineering and inference."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.predictions.features import build_features
from app.modules.predictions.ml_model import DemandModel


class PredictionService:
    """Coordinates feature building and ML inference for demand predictions."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.model = DemandModel()
