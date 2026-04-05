"""Statistical anomaly detection algorithms.

Each detector is a standalone async function that accepts a time-series of
measurements and returns an anomaly score: 0.0 = perfectly normal, 1.0 = highly anomalous.

Algorithms planned:
  - zscore_detector   — flags sudden spikes (|z| > threshold)
  - iqr_detector      — flags outlier quantities using IQR fences
  - cusum_detector    — detects gradual drift (CUmulative SUM)
  - isolation_forest  — multivariate detection (sklearn IsolationForest)

Each detector must implement the signature:
    async def detect(series: list[float], **kwargs) -> float
"""
