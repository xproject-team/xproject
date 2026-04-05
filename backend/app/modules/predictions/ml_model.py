"""ML model loading and inference wrapper for demand prediction.

Wraps the trained scikit-learn / joblib model so the rest of the codebase
never imports model-specific libraries directly. Swap the model file and
update DemandModel.predict() without touching any other module.
"""
import numpy as np


class DemandModel:
    """Loads the trained demand prediction model and exposes a predict() method."""

    def __init__(self, model_path: str = "models/demand_model.pkl") -> None:
        self._model = None
        self._model_path = model_path

    def load(self) -> None:
        """Load the serialised model from disk. Call once at application startup."""
        import joblib  # deferred import — only needed when model is used

        self._model = joblib.load(self._model_path)

    def predict(self, features: np.ndarray) -> tuple[float, float]:
        """Run inference on a feature vector.

        Returns:
            (predicted_demand, confidence) — both as float in [0, ∞) and [0, 1].
        """
        if self._model is None:
            return 0.0, 0.0
        # TODO: run inference and extract confidence from model output
        return 0.0, 0.0
