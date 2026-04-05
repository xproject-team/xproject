"""Feature engineering for the demand prediction ML model.

Transforms raw inventory and sales data into the feature vectors expected by
the trained model. All feature logic lives here so that training and inference
use identical transformations — never split feature code between notebooks and
service code.

Planned features (16-dimensional vector):
  [0]  hour_of_day (sin/cos encoded × 2)
  [2]  day_of_week (sin/cos encoded × 2)
  [4]  running_consumption_rate (units/hour)
  [5]  current_stock_pct
  [6]  tickets_scanned_last_30m
  [7]  ticket_scan_velocity_trend
  [8]  bar_id (one-hot, up to 4 bars)
  [12] historical_avg_demand_same_hour
  [13] historical_peak_demand
  [14] event_elapsed_fraction
  [15] weather_proxy (reserved)
"""
import numpy as np


async def build_features(event_id: int, sku: str, db) -> np.ndarray:
    """Build a 16-dimensional feature vector for the given event and SKU.

    Args:
        event_id: The active event to build features for.
        sku: The product SKU to predict demand for.
        db: Async database session for fetching raw data.

    Returns:
        A float32 numpy array of shape (16,).
    """
    # TODO: implement feature engineering
    return np.zeros(16, dtype=np.float32)
