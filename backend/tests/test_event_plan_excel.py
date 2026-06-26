"""Tests for app.modules.events.event_plan_excel.

The fixture file at tests/fixtures/excel/sundance_2026_plan.xlsx is the
real Slesh template for the Sundance Sunday 2026 series (4 dates).

These tests cover:
  - happy path: every sheet parses, assertions on known values
  - per-sheet defensive paths: missing sheet, malformed cells, etc.
  - normalization helpers in isolation (IVA, prices, dates, time ranges)
  - per-product cauzione handling
  - multi-event date extraction
"""
from __future__ import annotations
import io
from pathlib import Path

import openpyxl
import pytest

from app.modules.events.event_plan_excel import parse_event_plan
from app.modules.events.event_plan_excel.normalize import (
    normalize_iva,
    normalize_price,
    parse_event_dates,
    parse_time_range,
    parse_topup_list,
)
from app.modules.events.event_plan_excel.schemas import (
    BarSpec, ContactSpec, ParsedEventPlan, ParseWarning, ProductSpec,
)


FIXTURE = Path(__file__).parent / "fixtures" / "excel" / "sundance_2026_plan.xlsx"


@pytest.fixture(scope="module")
def parsed() -> ParsedEventPlan:
    """Parse the real fixture once per module — every happy-path test reuses."""
    return parse_event_plan(FIXTURE.read_bytes())


# ─────────────────────────────────────────────────────────────────────
# Sheet 1 — Overview
# ─────────────────────────────────────────────────────────────────────
def test_overview_event_basics(parsed):
    assert parsed.event_name == "Sundance Sunday"
    assert parsed.event_start_time == "12:30"
    assert parsed.event_end_time == "22:30"
    assert parsed.staff_arrival_time == "11:00"
    assert parsed.venue_name == "Villa Alberico"
    assert "Fioranello" in (parsed.venue_address or "")
    assert parsed.capacity == 1600
    assert parsed.expected_guests == 1600


def test_overview_multi_event_dates(parsed):
    # The file covers 4 Sundance dates: 14/06, 05/07, 19/07, 02/08
    assert parsed.event_dates == ["14/06", "05/07", "19/07", "02/08"]


def test_overview_contacts_extracted(parsed):
    # Two referenti in this file
    assert len(parsed.contacts) >= 2
    # At least one with the name "Alessandro Proietti"
    names = [c.name for c in parsed.contacts if c.name]
    assert any("Alessandro Proietti" in n for n in names)


# ─────────────────────────────────────────────────────────────────────
# Sheet 2 — Parametri Evento
# ─────────────────────────────────────────────────────────────────────
def test_parametri_topup_denominations(parsed):
    assert parsed.topup_denominations_user == [5, 10, 20, 50, 100]
    assert parsed.topup_denominations_staff == [5]


def test_parametri_refund_policy(parsed):
    # 1 EUR -> 100 cents, 0.5 EUR -> 50 cents
    assert parsed.refund_min_credit_cents == 100
    assert parsed.refund_fee_cents == 50


# ─────────────────────────────────────────────────────────────────────
# Sheet 3 — Device Count
# ─────────────────────────────────────────────────────────────────────
def test_devices_drink_bars(parsed):
    # Excel has MAIN BAR (9), NO.3 BAR (1), STAGE BAR (4)
    names = sorted(b.name for b in parsed.drink_bars)
    assert names == ["MAIN BAR", "NO.3 BAR", "STAGE BAR"]
    by_name = {b.name: b.device_count for b in parsed.drink_bars}
    assert by_name == {"MAIN BAR": 9, "NO.3 BAR": 1, "STAGE BAR": 4}


def test_devices_food_bars(parsed):
    names = sorted(b.name for b in parsed.food_bars)
    assert names == ["MALANDRINO", "PULLED PORK", "SCROCCHIA"]
    by_name = {b.name: b.device_count for b in parsed.food_bars}
    # Sundance 15 has 2 devices per food truck per the file
    assert by_name == {"MALANDRINO": 2, "SCROCCHIA": 2, "PULLED PORK": 2}


def test_devices_recharge_count(parsed):
    assert parsed.recharge_device_count == 4


# ─────────────────────────────────────────────────────────────────────
# Sheet 4 — Listini Bar
# ─────────────────────────────────────────────────────────────────────
def test_listini_products_present(parsed):
    # Cocktail Bar has at least the basic drink line-up
    cb = [p for p in parsed.products if p.bar_name.lower() == "cocktail bar"]
    names = {p.name.upper() for p in cb}
    assert {"SPRITZ", "DRINK", "PREMIUM"}.issubset(names)


def test_listini_hamburger_price_and_iva(parsed):
    hamburgers = [p for p in parsed.products
                  if p.name.lower() == "hamburger"]
    assert len(hamburgers) >= 1
    h = hamburgers[0]
    assert h.price_cents == 1200    # €12
    assert h.iva_pct == 10


def test_listini_cauzione_glass_deposit(parsed):
    # Cocktail Bar has 'Cauzione Bicchiere' at €1
    rows = [p for p in parsed.products
            if "cauzione" in p.name.lower()]
    assert any(p.price_cents == 100 for p in rows)


# ─────────────────────────────────────────────────────────────────────
# Normalization helpers
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    (10.0,   10),    # percent
    (10,     10),
    (0.1,    10),    # ratio
    (0.22,   22),
    (22.0,   22),
    (0,      0),
    (None,   None),
    ("oops", None),
    (-5,     None),
])
def test_normalize_iva(raw, expected):
    assert normalize_iva(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    (12.0,   1200),
    (7.5,    750),
    (0,      0),
    (None,   None),
    ("nope", None),
])
def test_normalize_price(raw, expected):
    assert normalize_price(raw) == expected


def test_parse_event_dates_multi():
    assert parse_event_dates("14/06-05/07-19/07-02/08") == ["14/06", "05/07", "19/07", "02/08"]


def test_parse_event_dates_garbage():
    assert parse_event_dates("hello world") == []
    assert parse_event_dates(None) == []


def test_parse_time_range():
    assert parse_time_range("12:30 / 22:30") == ("12:30", "22:30")
    assert parse_time_range("22:30") == ("22:30", None)
    assert parse_time_range(None) == (None, None)


def test_parse_topup_list():
    assert parse_topup_list("5/10/20/50/100 €") == [5, 10, 20, 50, 100]
    assert parse_topup_list("5 €") == [5]
    assert parse_topup_list(None) == []


# ─────────────────────────────────────────────────────────────────────
# Defensive paths
# ─────────────────────────────────────────────────────────────────────
def test_parse_corrupted_bytes_returns_warning_not_500():
    parsed = parse_event_plan(b"this is not an excel file")
    assert isinstance(parsed, ParsedEventPlan)
    assert len(parsed.warnings) >= 1
    assert any("could not open" in w.message for w in parsed.warnings)


def test_parse_workbook_missing_sheet_warns():
    # Build an empty workbook with no expected sheets
    wb = openpyxl.Workbook()
    # The default sheet is named "Sheet" — not one of ours
    buf = io.BytesIO()
    wb.save(buf)
    parsed = parse_event_plan(buf.getvalue())
    # Should produce a warning for EACH expected sheet that's missing
    sheet_warnings = {w.sheet for w in parsed.warnings if "missing" in w.where}
    assert "1. Overview"           in sheet_warnings
    assert "2. Parametri Evento"   in sheet_warnings
    assert "3. Device Count"       in sheet_warnings
    assert "4. Listini Bar"        in sheet_warnings
    assert "4.1. Listini Food"     in sheet_warnings
    # And parsed should still be a valid ParsedEventPlan, not crashed
    assert parsed.drink_bars == []
    assert parsed.products == []
