"""Slesh Event Plan Excel parser — pre-event configuration import.

The Slesh team sends Omar a single .xlsx file for each recurring event series
(e.g. Sundance Sunday) covering all four dates that summer. Sheets:

    1. Overview           Event basics: name, hours, dates, venue, capacity
    2. Parametri Evento   Top-up denominations, refund policy
    3. Device Count       Bars + devices per bar (drinks, food, recharge)
    4. Listini Bar        Drinks/cocktail bar product list + prices + IVA
    4.1. Listini Food     Per-vendor food menus
    5. Lineup             Music acts (currently unused — placeholder dates)

Public surface:

    >>> from app.modules.events.event_plan_excel import parse_event_plan
    >>> with open("plan.xlsx", "rb") as f:
    ...     parsed = parse_event_plan(f.read())
    >>> parsed.event_name
    'Sundance Sunday'

This module is the parsing layer ONLY. It writes nothing to the database.
The wizard endpoint (`POST /events/{id}/import-event-plan`) will render
the parsed JSON for Omar to confirm, and the finalize endpoint will commit
the confirmed data atomically.

Defensive parsing: every sheet is handled independently in try/except.
A malformed or missing sheet produces a ParseWarning rather than a 500;
the parser always returns a ParsedEventPlan (possibly with empty sections).
"""
from app.modules.events.event_plan_excel.parser import parse_event_plan
from app.modules.events.event_plan_excel.schemas import (
    ParsedEventPlan,
    BarSpec,
    ProductSpec,
    ContactSpec,
    ParseWarning,
)

__all__ = [
    "parse_event_plan",
    "ParsedEventPlan",
    "BarSpec",
    "ProductSpec",
    "ContactSpec",
    "ParseWarning",
]
