"""Typed dataclasses for the parsed Event Plan Excel.

These are the wire-shape the wizard endpoint returns to the frontend.
Kept as @dataclass (not Pydantic) so callers can treat them as plain
data; serialization happens at the FastAPI boundary in the endpoint.

Every list defaults to [], every optional scalar to None. The parser
guarantees this so consumers never need defensive None-checks beyond
the field types themselves.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ContactSpec:
    """A contact person from Sheet 1's 'Referenti' section."""
    role: str                       # e.g. "Referente generale"
    name: str | None = None
    email: str | None = None
    phone: str | None = None


@dataclass
class BarSpec:
    """A bar/point from Sheet 3 'Device Count'.

    Excel uses ITALIAN display names (MAIN BAR, MALANDRINO, etc).
    The wizard later asks Omar to link each one to a Slesh shop_id
    via the API picker — we do NOT attempt fuzzy matching here.
    """
    name: str                       # display name from Excel (preserve case)
    device_count: int               # number of POS devices at this bar
    bar_type: str                   # "drinks" | "food" | "service" | "recharge"
    notes: str | None = None        # notes column from Excel, if present


@dataclass
class ProductSpec:
    """A product row from Sheet 4 or 4.1.

    Sheet 4 has a richer per-vendor section (rows 32+) with Cauzione
    (deposit) data. We prefer that section over the simpler top section
    (rows 6-27) when the same product appears in both.
    """
    name: str                       # e.g. "Hamburger"
    bar_name: str                   # e.g. "Malandrino" (matches BarSpec.name)
    category: str                   # e.g. "Panineria" | "Bar" | "Merchandising"
    price_cents: int                # 1200 for €12
    iva_pct: int                    # 0-100 percent (normalized: 0.1 → 10, 10.0 → 10)
    cauzione_cents: int = 0         # deposit; 0 if no deposit charged


@dataclass
class ParseWarning:
    """Non-fatal warning surfaced to the wizard UI.

    `sheet` is the Excel sheet name (e.g. "3. Device Count").
    `where` is a free-form location hint (cell ref like "B14", row #, etc).
    `message` is human-readable English (translated to Italian in the UI
    if needed — we keep parser output language-agnostic).
    """
    sheet: str
    where: str
    message: str


@dataclass
class ParsedEventPlan:
    """The full result of parsing a Slesh Event Plan Excel.

    All sub-lists default to []. Scalars that couldn't be parsed are None.
    """
    # Sheet 1 — Overview
    event_name: str | None = None
    event_dates: list[str] = field(default_factory=list)    # ["14/06", "05/07", ...]
    event_start_time: str | None = None                     # "12:30"
    event_end_time: str | None = None                       # "22:30"
    staff_arrival_time: str | None = None                   # "11:00"
    venue_name: str | None = None
    venue_address: str | None = None
    capacity: int | None = None
    expected_guests: int | None = None
    contacts: list[ContactSpec] = field(default_factory=list)

    # Sheet 2 — Parametri Evento
    topup_denominations_user: list[int] = field(default_factory=list)
    topup_denominations_staff: list[int] = field(default_factory=list)
    refund_min_credit_cents: int | None = None
    refund_fee_cents: int | None = None

    # Sheet 3 — Device Count
    drink_bars: list[BarSpec] = field(default_factory=list)
    food_bars: list[BarSpec] = field(default_factory=list)
    other_bars: list[BarSpec] = field(default_factory=list)   # service, merch, etc.
    recharge_device_count: int = 0

    # Sheets 4 + 4.1 — Listini
    products: list[ProductSpec] = field(default_factory=list)

    # Always-present
    warnings: list[ParseWarning] = field(default_factory=list)
