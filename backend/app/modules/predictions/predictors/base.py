"""Abstract prediction engine interface.

Every prediction backend (heuristic today, ML in Track 2) implements this
interface. The service layer, API, and frontend are engine-agnostic — swap
the backend without touching any consumer.

Spec: docs/predictions-module-spec.md §5.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Union
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.predictions.schemas import (
    PredictionData,
    PredictionInsufficientData,
)


# A predictor returns EITHER a full snapshot OR a structured "not enough data"
# sentinel. Callers pattern-match on the type, never catch exceptions.
PredictorResult = Union[PredictionData, PredictionInsufficientData]


class BasePredictor(ABC):
    """Abstract prediction engine.

    Implementations:
      - HeuristicPredictor : historical averages + scaling. Ships in v1.0.
      - MLPredictor        : scikit-learn GradientBoostingRegressor. Track 2.

    Both produce the same PredictionData shape. The service layer stores
    the shape with the engine's label (predictor_type) so the UI can
    disclose which engine produced it — this is honest UX.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── Abstract interface ────────────────────────────────────────────────

    @property
    @abstractmethod
    def predictor_type(self) -> str:
        """Engine identifier. Stored on the row. Must match one of the
        PredictorType literal values: 'heuristic' or 'ml'.
        """
        ...

    @abstractmethod
    def minimum_events_required(self) -> int:
        """How many completed historical events this engine needs before
        producing usable output.

        HeuristicPredictor requires 1 (can scale from a single data point).
        MLPredictor requires 15 (per Backend Bible §11 — insufficient fit
        below that threshold).
        """
        ...

    @abstractmethod
    async def is_ready(self, tenant_id: UUID) -> bool:
        """Whether this engine CAN currently serve tenant_id.

        HeuristicPredictor: True if the tenant has ≥minimum_events_required
        completed historical events.
        MLPredictor: True if a trained model file exists for this tenant AND
        the minimum-events threshold is satisfied. (Track 2.)
        """
        ...

    @abstractmethod
    async def predict(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> PredictorResult:
        """Produce a prediction for the given event.

        Returns:
            PredictionData on success.
            PredictionInsufficientData when history is below threshold.

        Does NOT raise for "no data" — that's a valid outcome. Only raises
        for genuine engine failures (bad input, corrupt model, DB error).
        Service layer converts those into status='failed' with the reason.
        """
        ...
