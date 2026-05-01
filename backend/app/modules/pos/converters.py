"""Boundary converters: Slesh wire format -> XProject domain types.

This module is THE ONLY PLACE in the codebase where Slesh's wire-format
quirks are translated into our domain types. It exists for three reasons:

1. **Single source of truth.** Slesh sends money as integer cents, time as
   Unix milliseconds, and product/category names as locale dicts. Without a
   centralised translator, every consumer (ingester, dashboard, reports,
   predictions) would re-implement these conversions, drift apart, and
   eventually disagree about what "the same" Slesh order looked like.

2. **Pure boundary layer.** Schemas (`schemas.py`) faithfully mirror Slesh's
   wire shape. Domain code consumes Decimals and datetimes and strings.
   Converters bridge the two. Each function is pure (no I/O), typed, and
   independently testable against fixtures.

3. **Sundance reliability.** Each converter is non-throwing for the common
   "data is slightly imperfect" cases (missing locale, None timestamp) and
   logs a one-time warning when fallback paths are taken. We never crash
   the polling worker over a missing English translation; we always know
   when a fallback fired and can fix it post-event.

DESIGN CHOICES (locked in B2):
- Money:     int cents -> Decimal('8.00')   (NEVER use float for money)
- Timestamps: int ms (UTC) -> tz-aware datetime in UTC
                            -> optionally converted to Europe/Rome (Sundance)
- Names:     dict[locale -> str] -> single str via cascade
                                    (it -> en -> first available -> "")
- All conversions are reversible where it makes sense (decimal_to_cents,
  datetime_to_unix_ms) for symmetry, future writes, and easier testing.

Spec reference: docs/slesh-integration-roadmap.md §B2.4 + Sync Plan Delta 6.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Module-level constants
# ─────────────────────────────────────────────────────────────────────
EUROPE_ROME: ZoneInfo = ZoneInfo("Europe/Rome")
DEFAULT_LOCALE: str   = "it"          # Omar's primary language; matches Slesh defaults
LOCALE_FALLBACKS: tuple[str, ...] = ("it", "en")   # cascade order

# Track which (caller_context, missing_locale) pairs we've already warned
# about. Process-wide so we don't flood the logs with thousands of "missing
# locale" warnings during a backfill of past events.
_WARNED_LOCALE_FALLBACKS: set[tuple[str, str]] = set()


# ─────────────────────────────────────────────────────────────────────
# Money conversions
# ─────────────────────────────────────────────────────────────────────
def cents_to_decimal(cents: int | None) -> Decimal | None:
    """Convert Slesh's integer cents to a 2-decimal-place Decimal.

    Slesh sends every monetary field as an integer in the smallest currency
    unit (cents for EUR, USD, etc.). A €8.00 drink arrives as 800. This
    function divides by 100 and returns a Decimal — NEVER a float, because
    float arithmetic is not safe for money (0.1 + 0.2 != 0.3).

    Examples:
        >>> cents_to_decimal(800)     # €8.00
        Decimal('8.00')
        >>> cents_to_decimal(0)       # free item
        Decimal('0.00')
        >>> cents_to_decimal(None)    # missing field
        None

    Args:
        cents: Integer cents from Slesh, or None for missing fields.

    Returns:
        Decimal with two decimal places, or None if input was None.
    """
    if cents is None:
        return None
    # Quantize to 2dp so output is always 'x.xx' even for round numbers
    return (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def decimal_to_cents(amount: Decimal | None) -> int | None:
    """Inverse of cents_to_decimal — for symmetry and post-event reconciliation.

    Examples:
        >>> decimal_to_cents(Decimal('8.00'))
        800
        >>> decimal_to_cents(Decimal('12.345'))   # rounded HALF_UP
        1235
    """
    if amount is None:
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ─────────────────────────────────────────────────────────────────────
# Timestamp conversions
# ─────────────────────────────────────────────────────────────────────
def unix_ms_to_datetime(ms: int | None, *, tz: ZoneInfo | None = None) -> datetime | None:
    """Convert Slesh's Unix milliseconds (13-digit int) to a timezone-aware datetime.

    Slesh's `_createdAt`, `_payedAt`, and `fromTs/toTs` query parameters all
    use Unix ms (e.g. 1716569758657). Note: the docs prose claims ISO 8601
    but every observed schema example uses ms — we trust the schema.

    Default behaviour returns a UTC datetime. Pass `tz=EUROPE_ROME` to get
    a wall-clock time matching how Omar perceives the event.

    Examples:
        >>> unix_ms_to_datetime(1716569758657)
        datetime.datetime(2024, 5, 24, 16, 55, 58, 657000, tzinfo=datetime.timezone.utc)
        >>> unix_ms_to_datetime(1716569758657, tz=EUROPE_ROME)
        datetime.datetime(2024, 5, 24, 18, 55, 58, ..., tzinfo=zoneinfo.ZoneInfo('Europe/Rome'))
        >>> unix_ms_to_datetime(None)
        None

    Args:
        ms: Unix milliseconds since epoch, or None.
        tz: Target timezone. None => UTC. EUROPE_ROME for Sundance display.

    Returns:
        Timezone-aware datetime, or None if input was None.
    """
    if ms is None:
        return None
    dt_utc = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    if tz is None:
        return dt_utc
    return dt_utc.astimezone(tz)


def datetime_to_unix_ms(dt: datetime | None) -> int | None:
    """Inverse of unix_ms_to_datetime — for query-param construction.

    The polling worker (B6) calls Slesh with `?fromTs=<ms>&toTs=<ms>`,
    so we need this direction too. Naive datetimes are assumed UTC; the
    caller is responsible for being explicit about timezone.

    Examples:
        >>> dt = datetime(2024, 5, 24, 16, 55, 58, 657000, tzinfo=timezone.utc)
        >>> datetime_to_unix_ms(dt)
        1716569758657
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Treat naive datetimes as UTC. Caller should be explicit but we're
        # defensive here to avoid silently wrong cross-timezone math.
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def to_europe_rome(dt: datetime | None) -> datetime | None:
    """Shorthand: convert any tz-aware datetime to Europe/Rome.

    Used when generating user-facing timestamps for Omar's dashboard,
    where he expects to see local Italian wall-clock time.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(EUROPE_ROME)


# ─────────────────────────────────────────────────────────────────────
# Localized name resolution
# ─────────────────────────────────────────────────────────────────────
def localized_name(
    name: dict[str, str] | str | None,
    locale: str = DEFAULT_LOCALE,
    *,
    context: str = "",
) -> str:
    """Resolve a Slesh localized-name dict to a single string.

    Slesh returns product/category names as a dict like
    {"it": "Mojito", "en": "Mojito", "es": "Mojito"}. This function picks
    the requested locale, falling back through LOCALE_FALLBACKS, then to
    the first available value, and finally to an empty string. Each
    fallback fires a one-time warning so we know which products lack
    proper Italian translations without flooding logs at scale.

    Accepts a plain string for forward-compatibility: some Slesh endpoints
    or future versions might return strings directly. Returns it unchanged.

    Examples:
        >>> localized_name({"it": "Mojito", "en": "Mojito"})
        'Mojito'
        >>> localized_name({"en": "Beer"}, locale="it", context="product 123")
        # logs a warning that 'it' was missing for product 123
        'Beer'
        >>> localized_name(None)
        ''
        >>> localized_name("Already a string")
        'Already a string'

    Args:
        name:    Slesh's name field. Dict, string, or None.
        locale:  Preferred locale (default 'it' — Omar's language).
        context: Optional caller-provided context for logging
                 (e.g. "product 65f0e8c5"). Used to make warnings actionable.

    Returns:
        The best-available name as a string. "" if nothing was resolvable.
    """
    if name is None:
        return ""
    if isinstance(name, str):
        return name
    if not isinstance(name, dict):
        # Defensive: Slesh sent something we don't understand. Don't crash;
        # return empty and warn.
        logger.warning("localized_name received unexpected type %s (context=%s)",
                       type(name).__name__, context)
        return ""

    # Direct hit on the requested locale
    if locale in name and name[locale]:
        return name[locale]

    # Cascade through fallback locales (skip the one we already tried)
    for fb in LOCALE_FALLBACKS:
        if fb != locale and fb in name and name[fb]:
            _warn_locale_fallback(locale, fb, context)
            return name[fb]

    # Last resort: any non-empty value
    for v in name.values():
        if v:
            _warn_locale_fallback(locale, "any", context)
            return v

    # Truly empty dict
    _warn_locale_fallback(locale, "none", context)
    return ""


def _warn_locale_fallback(requested: str, used: str, context: str) -> None:
    """Log a one-time warning per (context, locale) pair when fallback fires."""
    key = (context or "<no-context>", requested)
    if key in _WARNED_LOCALE_FALLBACKS:
        return
    _WARNED_LOCALE_FALLBACKS.add(key)
    if used == "none":
        logger.warning("localized_name: empty name dict (context=%s, requested=%s)",
                       context, requested)
    else:
        logger.warning("localized_name: locale '%s' missing, fell back to '%s' (context=%s)",
                       requested, used, context)


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────
__all__ = [
    "EUROPE_ROME",
    "DEFAULT_LOCALE",
    "LOCALE_FALLBACKS",
    "cents_to_decimal",
    "decimal_to_cents",
    "unix_ms_to_datetime",
    "datetime_to_unix_ms",
    "to_europe_rome",
    "localized_name",
]
