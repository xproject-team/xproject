"""ML predictor placeholder — NOT SHIPPED in v1.0.

This file exists so the BasePredictor interface has two distinct
implementations as a design forcing function. Track 2 will replace
the NotImplementedError stubs with real scikit-learn logic.

Track 2 scope (dedicated session):
  1. Analyze Slesh 2024/2025 CSVs as training data
  2. Engineer features per Backend Bible §11.1 (guest_count, event_type,
     season, day_of_week, ticket_velocity, VIP_ratio, historical patterns)
  3. Train GradientBoostingRegressor for quantity predictions
  4. Train RandomForestClassifier for risk flag detection
  5. Persist trained model to disk (e.g. via joblib)
  6. Flip is_ready() from False to a real check

Until then: is_ready() returns False, so the service layer always
falls back to HeuristicPredictor.

Spec: docs/predictions-module-spec.md §5.2 + §12 (Track 2).
"""
from __future__ import annotations

from uuid import UUID

from app.modules.predictions.predictors.base import (
    BasePredictor,
    PredictorResult,
)


class MLPredictor(BasePredictor):
    """Placeholder for the scikit-learn prediction engine.

    Intentionally never ready in v1.0. Flipping is_ready() to real logic
    is the single integration point for Track 2 — no other code changes.
    """

    @property
    def predictor_type(self) -> str:
        return "ml"

    def minimum_events_required(self) -> int:
        # Per Backend Bible §11: GradientBoosting needs 15–25 events to
        # produce stable fit. Below this threshold we don't trust the
        # output and fall back to heuristic.
        return 15

    async def is_ready(self, tenant_id: UUID) -> bool:
        # v1.0: always False. Service always selects heuristic.
        # Track 2: check for trained model file on disk AND event-count
        # threshold. Something like:
        #     return model_path.exists() and await self._count_events(...) >= 15
        return False

    async def predict(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> PredictorResult:
        # Should never be called in v1.0 because select_predictor() will
        # route to HeuristicPredictor when is_ready() is False.
        raise NotImplementedError(
            "MLPredictor ships in Track 2. See docs/predictions-module-spec.md §12."
        )
