"""Small typed helpers for the event plan parser.

Each function is pure (no I/O) and either returns the normalized value
or None. Callers append a ParseWarning when None comes back for a field
the user is expected to fill in.
"""
from __future__ import annotations
import re
from typing import Any


def normalize_iva(raw: Any) -> int | None:
    """Slesh IVA arrives as either a percent (e.g. 10.0) or a decimal
    ratio (e.g. 0.1). Both mean 10%.

    Rule: values > 1 are treated as percent (10 → 10), values <= 1 are
    treated as ratio (0.1 → 10). Returns int 0-100 or None.
    """
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v < 0:
        return None
    if v > 1:
        return int(round(v))
    return int(round(v * 100))


def normalize_price(raw: Any) -> int | None:
    """Excel price is a float euro amount; we store cents."""
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v < 0:
        return None
    return int(round(v * 100))


def parse_event_dates(raw: Any) -> list[str]:
    """The Sheet 1 'Date Evento' field looks like '14/06-05/07-19/07-02/08'.

    Returns the list of DD/MM strings. Empty list if the input doesn't
    match the pattern. We deliberately don't infer year (multi-year
    series get explicit dates from the wizard step 1).
    """
    if not isinstance(raw, str):
        return []
    parts = [p.strip() for p in raw.split("-") if p.strip()]
    # Each part must look like DD/MM
    valid = [p for p in parts if re.fullmatch(r"\d{1,2}/\d{1,2}", p)]
    return valid


def parse_time_range(raw: Any) -> tuple[str | None, str | None]:
    """The Sheet 1 'Orari evento' field looks like '12:30 / 22:30'.

    Returns (start, end). Either may be None if missing.
    """
    if not isinstance(raw, str):
        return None, None
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    if len(parts) == 0:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]


def parse_topup_list(raw: Any) -> list[int]:
    """The Sheet 2 fields come in two shapes:

      - "App operatore/cassa" has a SINGLE numeric value (5.0)
      - "App utente" has a slash-separated string like '5/10/20/50/100 €'

    Returns the integer denominations, sorted ascending. Empty list if
    no integers can be extracted.

    Bugfix note: an earlier version used re.findall on str(raw)
    which on raw=5.0 became str='5.0' and matched ['5', '0'] — the
    fractional zero polluted results. We now handle numeric inputs
    explicitly and only regex on actual strings.
    """
    if raw is None:
        return []
    # Numeric scalar — single denomination
    if isinstance(raw, (int, float)):
        v = int(round(float(raw)))
        return [v] if v > 0 else []
    # Anything else — coerce to str and split on non-digit boundaries.
    # Drop fractional zeros by splitting on '/' first (the actual separator),
    # then extracting the leading integer from each chunk.
    s = str(raw)
    out: set[int] = set()
    for chunk in re.split(r"[/,;]", s):
        m = re.match(r"\s*(\d+)", chunk)
        if m:
            v = int(m.group(1))
            if v > 0:
                out.add(v)
    return sorted(out)


def clean_str(raw: Any) -> str | None:
    """Strip whitespace, return None if empty."""
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None
