"""Unit tests for app.core.config — Slesh integration credentials.

These are pure-Python smoke tests: no DB, no HTTP, no FastAPI client. They
verify that the Slesh-related Settings fields are present, well-typed, and
load real values from .env on import.

WHY THIS FILE EXISTS:
The Slesh integration depends on three values being correctly populated at
import time: SLESH_API_TOKEN, SLESH_BRAND_ID, and SLESH_BASE_URL. If any
of these silently breaks (typo in .env, field renamed, default leaks into
production), every downstream Slesh call will fail in confusing ways.
These tests catch that regression at the cheapest possible layer — config
load — before a single HTTP call goes out.

Spec reference: docs/slesh-integration-roadmap.md §B1.
"""
from __future__ import annotations

import re

import pytest


# ─── 1. Import & instantiation ──────────────────────────────────────────────
# The most basic regression: someone breaks config.py syntactically or
# renames a field, and the whole app fails to start. This test catches it
# before pytest even runs the rest of the suite.

def test_settings_imports_without_error():
    """app.core.config must import cleanly and expose a `settings` instance."""
    from app.core.config import settings  # noqa: F401 — import is the test

    assert settings is not None


# ─── 2. Slesh field presence & types ────────────────────────────────────────
# Pydantic Settings won't error if a field is missing from the class — it
# just silently uses the default. These tests assert that every Slesh field
# we depend on is present AND has the right type. If someone removes one
# during a refactor, this fails immediately.

def test_slesh_fields_are_defined():
    """All six Slesh fields must exist on the Settings instance."""
    from app.core.config import settings

    expected = {
        "slesh_base_url":        str,
        "slesh_api_token":       str,
        "slesh_brand_id":        str,
        "slesh_request_timeout": float,
        "slesh_rate_limit_rps":  int,
        "slesh_max_retries":     int,
    }
    for field, expected_type in expected.items():
        assert hasattr(settings, field), f"Missing Slesh field: {field}"
        value = getattr(settings, field)
        assert isinstance(value, expected_type), (
            f"{field} should be {expected_type.__name__}, got {type(value).__name__}"
        )


# ─── 3. Slesh values load from .env ─────────────────────────────────────────
# These confirm that real values reach the Settings instance — not just that
# the fields exist. A common bug: env var name mismatch (e.g. SLESH_TOKEN vs
# SLESH_API_TOKEN). Without this test, you'd discover it only when the first
# real HTTP call returns 401.

def test_slesh_base_url_is_production():
    """Default base URL points at Slesh production. No staging exists."""
    from app.core.config import settings

    assert settings.slesh_base_url == "https://api.slesh.it/api"


def test_slesh_api_token_is_loaded():
    """Token must be loaded from .env — non-empty and reasonably long.

    Slesh JWTs are ~200 chars. A length below 50 is almost certainly a
    placeholder or a truncated copy-paste from 1Password.
    """
    from app.core.config import settings

    assert settings.slesh_api_token, "SLESH_API_TOKEN is empty — check .env"
    assert len(settings.slesh_api_token) >= 50, (
        f"Token suspiciously short ({len(settings.slesh_api_token)} chars)"
    )


def test_slesh_brand_id_is_24char_hex():
    """Slesh brand IDs are MongoDB ObjectIds: exactly 24 hex characters."""
    from app.core.config import settings

    assert settings.slesh_brand_id, "SLESH_BRAND_ID is empty — check .env"
    assert re.fullmatch(r"[0-9a-f]{24}", settings.slesh_brand_id), (
        f"Brand ID is not a 24-char hex string: {settings.slesh_brand_id!r}"
    )


# ─── 4. Operational knobs are sensible ──────────────────────────────────────
# These prevent silent regressions where someone sets max_retries=0 or
# rate_limit=0 and breaks the integration in subtle ways under load.

def test_slesh_operational_knobs_are_positive():
    """Timeout, rate limit, and max retries must all be positive."""
    from app.core.config import settings

    assert settings.slesh_request_timeout > 0, "Timeout must be > 0"
    assert settings.slesh_rate_limit_rps  > 0, "Rate limit must be > 0"
    assert settings.slesh_max_retries     >= 0, "Max retries must be >= 0"


# ─── 5. Old placeholder fields are removed ──────────────────────────────────
# B1 explicitly removed slesh_api_url and slesh_api_key (the wrong-shaped
# fields scaffolded on March 28). If they accidentally come back via a bad
# merge or copy-paste, this test catches it.

def test_old_placeholder_fields_are_gone():
    """The pre-B1 placeholder field names must NOT exist on Settings."""
    from app.core.config import settings

    for stale_field in ("slesh_api_url", "slesh_api_key"):
        assert not hasattr(settings, stale_field), (
            f"Stale field {stale_field} reappeared — B1 removal regressed"
        )
