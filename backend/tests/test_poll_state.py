"""Unit tests for poll_state — pure window math.

Locks in the cursor logic, overlap window, and explicit-window helper
that drive both live polling (B6) and historical backfill (B7).

These tests use a tiny in-memory stub for SleshPollState (the SQLAlchemy
model) so they run with no DB. The stub exposes only the attributes
compute_window reads; that\'s sufficient for testing pure math.

Spec: docs/slesh-integration-roadmap.md \u00a7B6.4 + \u00a7B7 (explicit_window).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.pos.poll_state import (
    PollWindow,
    compute_window,
    explicit_window,
)


# ─── In-memory stub for SleshPollState ──────────────────────────────────
@dataclass
class _StubState:
    last_seen_ts: int


# Reference timestamp: 2025-08-03 19:30:00 UTC = 1754249400000 ms
REF_TS_MS = 1754249400000
REF_DT    = datetime(2025, 8, 3, 19, 30, tzinfo=timezone.utc)


# ─── PollWindow ─────────────────────────────────────────────────────────

def test_pollwindow_width_seconds_basic():
    w = PollWindow(
        since_ts = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
        until_ts = datetime(2025, 1, 1, 12, 30, tzinfo=timezone.utc),
    )
    assert w.width_seconds == 1800.0


def test_pollwindow_width_seconds_zero():
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert PollWindow(since_ts=t, until_ts=t).width_seconds == 0.0


# ─── compute_window — cursor-based ──────────────────────────────────────

def test_compute_window_default_overlap_60s():
    """Default overlap is 60s; window starts at cursor - 60s."""
    state = _StubState(last_seen_ts=REF_TS_MS)
    until = REF_DT + timedelta(minutes=5)

    w = compute_window(state, until_ts=until)

    expected_since = REF_DT - timedelta(seconds=60)
    assert w.since_ts == expected_since
    assert w.until_ts == until
    assert w.width_seconds == pytest.approx(360.0)  # 5min + 60s overlap


def test_compute_window_custom_overlap():
    state = _StubState(last_seen_ts=REF_TS_MS)
    until = REF_DT + timedelta(minutes=5)

    w = compute_window(state, until_ts=until, overlap_seconds=10)

    expected_since = REF_DT - timedelta(seconds=10)
    assert w.since_ts == expected_since
    assert w.width_seconds == pytest.approx(310.0)


def test_compute_window_zero_overlap():
    """overlap_seconds=0 means since=cursor exactly."""
    state = _StubState(last_seen_ts=REF_TS_MS)
    until = REF_DT + timedelta(minutes=5)

    w = compute_window(state, until_ts=until, overlap_seconds=0)
    assert w.since_ts == REF_DT


def test_compute_window_since_clamped_when_cursor_after_until():
    """Defensive: if cursor is in the future relative to until_ts,
    since collapses to until - overlap to keep window non-negative."""
    state = _StubState(last_seen_ts=REF_TS_MS)
    # until_ts BEFORE the cursor (clock skew scenario)
    until = REF_DT - timedelta(minutes=5)

    w = compute_window(state, until_ts=until, overlap_seconds=60)

    # Should clamp to until - 60s, not produce negative window
    assert w.since_ts == until - timedelta(seconds=60)
    assert w.since_ts < w.until_ts


def test_compute_window_default_until_uses_now(monkeypatch):
    """When until_ts=None, defaults to datetime.now(UTC)."""
    state = _StubState(last_seen_ts=REF_TS_MS)
    w = compute_window(state, until_ts=None)
    # We can\'t assert exact now() but we can assert tz-aware UTC and recent
    now = datetime.now(tz=timezone.utc)
    assert w.until_ts.tzinfo == timezone.utc
    assert (now - w.until_ts).total_seconds() < 5  # within 5 seconds


def test_compute_window_returns_tz_aware_utc():
    """Both since and until are always tz-aware UTC."""
    state = _StubState(last_seen_ts=REF_TS_MS)
    until = datetime(2025, 8, 3, 19, 35)  # naive
    w = compute_window(state, until_ts=until)

    assert w.since_ts.tzinfo is not None
    assert w.until_ts.tzinfo is not None


# ─── explicit_window — backfill mode ────────────────────────────────────

def test_explicit_window_basic():
    since = datetime(2025, 8, 3, 19, 0, tzinfo=timezone.utc)
    until = datetime(2025, 8, 3, 19, 30, tzinfo=timezone.utc)

    w = explicit_window(since_ts=since, until_ts=until)

    assert w.since_ts == since
    assert w.until_ts == until
    assert w.width_seconds == 1800.0


def test_explicit_window_naive_inputs_get_utc():
    since = datetime(2025, 8, 3, 19, 0)   # naive
    until = datetime(2025, 8, 3, 19, 30)  # naive

    w = explicit_window(since_ts=since, until_ts=until)

    assert w.since_ts.tzinfo == timezone.utc
    assert w.until_ts.tzinfo == timezone.utc


def test_explicit_window_rejects_inverted_bounds():
    """since >= until is a programmer error; raise loudly."""
    since = datetime(2025, 8, 3, 19, 30, tzinfo=timezone.utc)
    until = datetime(2025, 8, 3, 19, 0,  tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="must be < until"):
        explicit_window(since_ts=since, until_ts=until)


def test_explicit_window_rejects_equal_bounds():
    same = datetime(2025, 8, 3, 19, 30, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="must be < until"):
        explicit_window(since_ts=same, until_ts=same)
