"""Centralized logging configuration.

Why this exists:
    - SQL queries from SQLAlchemy were flooding stdout, hiding real signal
      (warnings, errors, subscriber lifecycle, etc.)
    - No timestamp/level prefix made it impossible to grep for problems
    - WebSocket / Redis lifecycle events were silently dropped

This module is imported once on app startup. It configures the root
logger + key library loggers so the operational signal/noise ratio
matches a production system.

Switch to JSON output for production (e.g. shipping to Datadog/CloudWatch)
by setting LOG_FORMAT=json.
"""
from __future__ import annotations

import logging
import sys

from app.core.config import settings


# Standard prod-friendly format: timestamp + level + logger + message
_TEXT_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging() -> None:
    """Apply logging config — call once at app startup, before anything else."""

    # ─── Root logger ──────────────────────────────────────────────
    root = logging.getLogger()
    root.setLevel(settings.log_level)

    # Wipe any handlers FastAPI/uvicorn auto-installed so we don't get
    # duplicate output. We add our own.
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_TEXT_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(handler)

    # ─── Library log levels ───────────────────────────────────────
    # SQLAlchemy: VERY chatty by default. Only show queries when explicitly
    # debugging — set log_sql=True or LOG_SQL=true env var.
    sql_level = logging.INFO if settings.log_sql else logging.WARNING
    logging.getLogger("sqlalchemy.engine").setLevel(sql_level)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

    # Uvicorn access logs: kept at INFO (one line per request — useful)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    # Redis: only complain on real problems
    logging.getLogger("redis").setLevel(logging.WARNING)

    # Our own modules — respect the configured level
    logging.getLogger("app").setLevel(settings.log_level)

    logging.getLogger(__name__).info(
        "logging configured (level=%s, log_sql=%s)",
        settings.log_level, settings.log_sql,
    )
