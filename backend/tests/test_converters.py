"""Unit tests for app.modules.pos.converters — boundary conversions.

These tests lock in the contract for converting Slesh's wire format to
XProject domain types:

  - Money:      int cents          -> Decimal('x.xx')   (NEVER float)
  - Timestamps: int Unix ms (UTC)  -> tz-aware datetime
  - Names:      dict[locale->str]  -> single str (cascade)

WHY THIS FILE EXISTS:
The converters are the only place where wire-format quirks become domain
types. Every dashboard number, every alert threshold, every report Decimal
flows through these functions. A subtle bug here (e.g. float for money,
naive datetime, wrong locale fallback) corrupts every downstream feature.

Discipline locked in here:
  - cents_to_decimal returns Decimal — float is forbidden for money
  - timestamps are always tz-aware — naive datetimes are forbidden
  - locale fallback fires warnings exactly once per unique miss
  - None inputs propagate as None (no silent default values)

Spec reference: docs/slesh-integration-roadmap.md §B2.9.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.modules.pos.converters import (
    EUROPE_ROME,
    cents_to_decimal,
    decimal_to_cents,
    unix_ms_to_datetime,
    datetime_to_unix_ms,
    to_europe_rome,
    localized_name,
)


# ─── 1. Money: cents -> Decimal ─────────────────────────────────────────────

@pytest.mark.parametrize("cents,expected", [
    (800,    Decimal("8.00")),     # typical drink (€8.00)
    (1250,   Decimal("12.50")),    # premium (€12.50)
    (0,      Decimal("0.00")),     # free welcome drink
    (1,      Decimal("0.01")),     # €0.01 minimum
    (100000, Decimal("1000.00")),  # big-ticket order
])
def test_cents_to_decimal_happy_path(cents: int, expected: Decimal):
    """Integer cents convert exactly to 2-decimal Decimal."""
    result = cents_to_decimal(cents)
    assert result == expected
    assert isinstance(result, Decimal)


def test_cents_to_decimal_returns_decimal_not_float():
    """Money MUST be Decimal, never float (precision risk)."""
    result = cents_to_decimal(800)
    assert not isinstance(result, float), (
        "float for money is forbidden — would lose precision (0.1+0.2!=0.3)"
    )


def test_cents_to_decimal_none_propagates():
    """None input -> None output (no silent default)."""
    assert cents_to_decimal(None) is None


def test_cents_to_decimal_quantizes_to_two_places():
    """Output is always 'x.xx' — never 'x.x' or 'x'."""
    # Decimal('8.00') string repr should always be '8.00', not '8' or '8.0'
    result = cents_to_decimal(800)
    assert str(result) == "8.00"


# ─── 2. Money: Decimal -> cents (round-trip safety) ────────────────────────

def test_decimal_to_cents_round_trip():
    """cents -> Decimal -> cents preserves the exact value."""
    for cents in (800, 0, 1, 1250, 100000):
        round_trip = decimal_to_cents(cents_to_decimal(cents))
        assert round_trip == cents


def test_decimal_to_cents_handles_fractional_inputs():
    """Decimal with sub-cent precision rounds HALF_UP to int cents."""
    assert decimal_to_cents(Decimal("12.345")) == 1235  # rounds up
    assert decimal_to_cents(Decimal("12.344")) == 1234  # rounds down


def test_decimal_to_cents_none_propagates():
    assert decimal_to_cents(None) is None


# ─── 3. Timestamps: Unix ms -> tz-aware datetime ────────────────────────────

# Real value from the brand_my fixture: 2024-05-24 16:55:58.657 UTC
SUNDANCE_MS = 1716569758657


def test_unix_ms_to_datetime_returns_utc_by_default():
    """Default call returns a UTC-aware datetime."""
    dt = unix_ms_to_datetime(SUNDANCE_MS)
    assert dt is not None
    assert dt.tzinfo == timezone.utc


def test_unix_ms_to_datetime_preserves_ms_precision():
    """Millisecond precision survives the round trip."""
    dt = unix_ms_to_datetime(SUNDANCE_MS)
    assert dt.microsecond == 657_000  # 657 ms = 657_000 µs


def test_unix_ms_to_datetime_to_europe_rome():
    """Passing tz=EUROPE_ROME shifts to local Italian wall-clock time."""
    dt_utc  = unix_ms_to_datetime(SUNDANCE_MS)
    dt_rome = unix_ms_to_datetime(SUNDANCE_MS, tz=EUROPE_ROME)
    # Same instant, different wall-clock representation
    assert dt_utc == dt_rome
    # But the displayed hour should differ (UTC+1 in winter, UTC+2 in DST)
    assert dt_rome.hour != dt_utc.hour


def test_unix_ms_to_datetime_none_propagates():
    assert unix_ms_to_datetime(None) is None


def test_datetime_to_unix_ms_round_trip():
    """ms -> datetime -> ms preserves the exact integer."""
    assert datetime_to_unix_ms(unix_ms_to_datetime(SUNDANCE_MS)) == SUNDANCE_MS


def test_datetime_to_unix_ms_assumes_utc_for_naive_datetime():
    """Naive datetime is interpreted as UTC (defensive default)."""
    naive = datetime(2024, 5, 24, 16, 55, 58, 657_000)  # no tzinfo
    aware = naive.replace(tzinfo=timezone.utc)
    assert datetime_to_unix_ms(naive) == datetime_to_unix_ms(aware)


def test_to_europe_rome_shorthand():
    """to_europe_rome converts any tz-aware datetime to Europe/Rome."""
    dt_utc = unix_ms_to_datetime(SUNDANCE_MS)
    rome = to_europe_rome(dt_utc)
    assert rome.tzinfo == EUROPE_ROME


# ─── 4. Localized name resolution ───────────────────────────────────────────

def test_localized_name_direct_hit():
    """Requested locale present -> returns it."""
    assert localized_name({"it": "Mojito", "en": "Mojito"}, locale="it") == "Mojito"


def test_localized_name_cascades_to_english():
    """If 'it' is missing, falls back to 'en'."""
    assert localized_name({"en": "Beer"}, locale="it") == "Beer"


def test_localized_name_cascades_to_any_available():
    """If neither 'it' nor 'en' is present, returns any non-empty value."""
    result = localized_name({"es": "Cerveza", "fr": "Bière"}, locale="it")
    assert result in {"Cerveza", "Bière"}


def test_localized_name_empty_dict_returns_empty_string():
    """Empty dict -> '' (no crash)."""
    assert localized_name({}, locale="it") == ""


def test_localized_name_none_returns_empty_string():
    """None input -> '' (no crash)."""
    assert localized_name(None) == ""


def test_localized_name_passthrough_when_already_string():
    """Forward-compat: if Slesh ever returns a plain string, pass it through."""
    assert localized_name("Already a string") == "Already a string"


def test_localized_name_warning_dedup(caplog):
    """The same missing-locale context only emits ONE warning, not many.

    This is the Sundance-protection feature: when 5,000 wristband orders
    hit the same product with a missing translation, we want one warning,
    not 5,000 log entries flooding the system.
    """
    import logging
    caplog.set_level(logging.WARNING)

    # Use a unique context to avoid pollution from other tests sharing
    # the process-level dedup set.
    ctx = "test_dedup_unique_context_12345"
    for _ in range(5):
        localized_name({"en": "X"}, locale="it", context=ctx)

    matching = [r for r in caplog.records if ctx in r.getMessage()]
    assert len(matching) == 1, (
        f"expected exactly 1 warning for repeated calls, got {len(matching)}"
    )
