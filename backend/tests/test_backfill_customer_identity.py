"""Unit tests for the backfill's diff logic (_compute_updates) — the piece
that decides what an --execute run would write. Pure function, no Slesh
network access and no live database: fed fabricated _FetchedOrder /
EventOrder objects directly.

Deliberately does NOT re-test extract_identity_fields' mapping rules —
those live in test_order_ingester.py, exercised through the same shared
function the backfill calls. This file only tests the NULL-only,
match/no-match diffing that is unique to the backfill script.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.scripts.backfill_customer_identity import (
    BackfillReport,
    _FetchedOrder,
    _compute_updates,
    _mask,
)


class _FakeEventOrder:
    """Mimics just the attributes _compute_updates reads/matches on."""
    def __init__(self, *, id=None, customer_email=None, payment_token=None, raw_extras=None):
        self.id = id or uuid4()
        self.customer_email = customer_email
        self.payment_token = payment_token
        self.raw_extras = raw_extras


def _fo(order_id: str, **overrides) -> _FetchedOrder:
    base = dict(
        slesh_order_id=order_id,
        customer_email=None,
        payment_token=None,
        raw_extras_user=None,
        raw_extras_operator=None,
    )
    base.update(overrides)
    return _FetchedOrder(**base)


def test_no_match_counts_as_fetched_but_not_matched():
    report = BackfillReport()
    fetched = [_fo("ord-unknown", customer_email="a@b.com")]
    updates = _compute_updates(fetched, existing={}, report=report)

    assert report.matched_existing_order == 0
    assert report.would_update == 0
    assert updates == []
    # still counted toward the "carries a field" tallies
    assert report.with_customer_email == 1


def test_matched_row_with_null_email_gets_filled():
    row = _FakeEventOrder(customer_email=None)
    report = BackfillReport()
    fetched = [_fo("ord-1", customer_email="jane@example.com")]

    updates = _compute_updates(fetched, existing={"ord-1": row}, report=report)

    assert report.matched_existing_order == 1
    assert report.would_update == 1
    assert len(updates) == 1
    updated_row, values = updates[0]
    assert updated_row is row
    assert values == {"customer_email": "jane@example.com"}


def test_matched_row_with_existing_email_is_never_overwritten():
    """The hard requirement: UPDATE-only, NULL-only. An already-populated
    column must not appear in the write plan even if Slesh now returns a
    DIFFERENT value."""
    row = _FakeEventOrder(customer_email="already-set@example.com")
    report = BackfillReport()
    fetched = [_fo("ord-1", customer_email="different@example.com")]

    updates = _compute_updates(fetched, existing={"ord-1": row}, report=report)

    assert report.matched_existing_order == 1
    assert report.would_update == 0
    assert updates == []


def test_payment_token_same_null_only_rule():
    row = _FakeEventOrder(payment_token="tok-existing")
    report = BackfillReport()
    fetched = [_fo("ord-1", payment_token="tok-from-slesh")]

    updates = _compute_updates(fetched, existing={"ord-1": row}, report=report)
    assert updates == []

    row2 = _FakeEventOrder(payment_token=None)
    report2 = BackfillReport()
    updates2 = _compute_updates(fetched, existing={"ord-1": row2}, report=report2)
    assert updates2[0][1] == {"payment_token": "tok-from-slesh"}


def test_raw_extras_only_written_when_column_is_wholly_null():
    """Sundance-14-style recovery: raw_extras IS NULL on the existing row,
    Slesh still has the user — write {"user": ...}."""
    row = _FakeEventOrder(raw_extras=None)
    report = BackfillReport()
    fetched = [_fo("ord-1", raw_extras_user={"_id": "mongo123"})]

    updates = _compute_updates(fetched, existing={"ord-1": row}, report=report)

    assert updates[0][1] == {"raw_extras": {"user": {"_id": "mongo123"}}}


def test_raw_extras_never_touched_if_already_populated():
    """Even a partial existing raw_extras (e.g. {"operator": ...} with no
    "user" key) must not be merged into — out of scope for this pass,
    per the module docstring."""
    row = _FakeEventOrder(raw_extras={"operator": {"_id": "op1"}})
    report = BackfillReport()
    fetched = [_fo("ord-1", raw_extras_user={"_id": "mongo123"})]

    updates = _compute_updates(fetched, existing={"ord-1": row}, report=report)
    assert updates == []


def test_raw_extras_includes_operator_when_both_present():
    row = _FakeEventOrder(raw_extras=None)
    report = BackfillReport()
    fetched = [_fo(
        "ord-1",
        raw_extras_user={"_id": "mongo123"},
        raw_extras_operator={"id": "op1", "type": "operator"},
    )]

    updates = _compute_updates(fetched, existing={"ord-1": row}, report=report)
    assert updates[0][1]["raw_extras"] == {
        "operator": {"id": "op1", "type": "operator"},
        "user": {"_id": "mongo123"},
    }


def test_multiple_columns_fillable_at_once():
    row = _FakeEventOrder(customer_email=None, payment_token=None, raw_extras=None)
    report = BackfillReport()
    fetched = [_fo(
        "ord-1",
        customer_email="jane@example.com",
        payment_token="tok-1",
        raw_extras_user={"_id": "mongo123"},
    )]

    updates = _compute_updates(fetched, existing={"ord-1": row}, report=report)
    assert report.would_update == 1
    values = updates[0][1]
    assert set(values.keys()) == {"customer_email", "payment_token", "raw_extras"}


def test_matched_but_nothing_fillable_does_not_count_as_would_update():
    """Matched, but every fetched field is None (e.g. cash guest) and every
    existing column is already non-null — a real no-op, not a write."""
    row = _FakeEventOrder(customer_email="x@example.com", payment_token="tok", raw_extras={"user": {}})
    report = BackfillReport()
    fetched = [_fo("ord-1")]

    updates = _compute_updates(fetched, existing={"ord-1": row}, report=report)
    assert report.matched_existing_order == 1
    assert report.would_update == 0
    assert updates == []


def test_examples_capped_at_five_and_masked():
    report = BackfillReport()
    rows = {f"ord-{i}": _FakeEventOrder(customer_email=None) for i in range(8)}
    fetched = [_fo(f"ord-{i}", customer_email=f"person{i}@example.com") for i in range(8)]

    _compute_updates(fetched, existing=rows, report=report)

    assert report.would_update == 8
    assert len(report.examples) == 5
    for ex in report.examples:
        assert ex["customer_email"].endswith("***")
        assert "@example.com" not in ex["customer_email"]


def test_mask_helper():
    assert _mask(None) == "None"
    assert _mask("jane@example.com") == "jane***"
    assert _mask("ab") == "ab***"
