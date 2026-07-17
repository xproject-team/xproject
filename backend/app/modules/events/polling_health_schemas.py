"""Schema for GET /events/{event_id}/polling-health.

Day 4 (Jul-19 sprint) observability endpoint — lets the dashboard show
whether Slesh polling is alive without an SSH session.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PollingHealthResponse(BaseModel):
    last_run_at: datetime | None
    seconds_since_last_run: float | None
    last_status: str | None
    last_error: str | None
    consecutive_failures: int
    is_healthy: bool
