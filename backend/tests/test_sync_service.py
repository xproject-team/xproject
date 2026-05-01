"""Sync service unit tests — pure logic, no DB, no network.

Locks in:
  - SyncResult arithmetic (created/updated/skipped → total)
  - Slesh-category-name → ProductType classification
  - Unknown-category warning behavior

The full DB integration (sync_shops, sync_products against fixtures) is
covered in test_adapter_unit.py + the live CLI verification in B5.
"""
from __future__ import annotations

import logging

import pytest

from app.modules.pos.sync_service import (
    SyncResult,
    _classify_product_type,
)
from app.modules.products.models import ProductType


# ─── SyncResult arithmetic ────────────────────────────────────────────────

def test_sync_result_total_sums_three_counters():
    r = SyncResult(created=2, updated=1, skipped=3)
    assert r.total == 6


def test_sync_result_str_is_human_readable():
    r = SyncResult(created=66, updated=0, skipped=18)
    s = str(r)
    assert "created=66" in s
    assert "updated=0" in s
    assert "skipped=18" in s
    assert "total=84" in s


def test_sync_result_default_factory_isolates_errors_list():
    """errors list is per-instance, not shared between SyncResults."""
    r1 = SyncResult()
    r2 = SyncResult()
    r1.errors.append("boom")
    assert r2.errors == []  # isolation, not shared


# ─── Category classification ──────────────────────────────────────────────

@pytest.mark.parametrize("slesh_name,expected_type", [
    ("beverage",            ProductType.DRINK),
    ("Food",                ProductType.FOOD),
    ("food",                ProductType.FOOD),       # case-insensitive
    ("FOOD",                ProductType.FOOD),
    ("Merch",               ProductType.SUPPLY),
    ("Guardaroba",          ProductType.SUPPLY),
    ("guardaroba",          ProductType.SUPPLY),     # case-insensitive
    ("prodotti non attivi", None),                    # explicit skip
])
def test_classify_known_categories(slesh_name, expected_type):
    assert _classify_product_type(slesh_name) == expected_type


def test_classify_returns_none_for_empty_or_missing():
    assert _classify_product_type(None) is None
    assert _classify_product_type("") is None


def test_classify_unknown_category_logs_warning(caplog):
    """Unknown Slesh category logs a warning and returns None (skip)."""
    caplog.set_level(logging.WARNING)
    result = _classify_product_type("brand-new-category-from-the-future")
    assert result is None
    assert any(
        "unknown Slesh category" in r.getMessage()
        for r in caplog.records
    )


def test_classify_strips_whitespace():
    """Slesh category names with stray whitespace still classify correctly."""
    assert _classify_product_type("  beverage  ") == ProductType.DRINK
    assert _classify_product_type("Food\n") == ProductType.FOOD
