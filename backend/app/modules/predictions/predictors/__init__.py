"""Pluggable prediction engines.

Public API:
    BasePredictor           — abstract interface every engine implements
    HeuristicPredictor      — today's engine (historical averages + scaling)
    MLPredictor             — Track 2 placeholder (scikit-learn, not shipped)

The service layer chooses the engine via select_predictor(); today it
always returns HeuristicPredictor. When MLPredictor is ready, selection
logic flips to prefer ML when minimum_events_required is satisfied.
"""
from app.modules.predictions.predictors.base import (
    BasePredictor,
    PredictorResult,
)
from app.modules.predictions.predictors.heuristic import HeuristicPredictor
from app.modules.predictions.predictors.ml_placeholder import MLPredictor

__all__ = [
    "BasePredictor",
    "PredictorResult",
    "HeuristicPredictor",
    "MLPredictor",
]
