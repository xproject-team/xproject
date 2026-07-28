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
    Slesh still has the user — write {"user": ...} plus a provenance
    marker so a fresh recovery is distinguishable from a live capture."""
    row = _FakeEventOrder(raw_extras=None)
    report = BackfillReport()
    fetched = [_fo("ord-1", raw_extras_user={"_id": "mongo123"})]

    updates = _compute_updates(fetched, existing={"ord-1": row}, report=report)

    assert updates[0][1] == {
        "raw_extras": {"user": {"_id": "mongo123"}, "user_source": "backfill"},
    }


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
        "user_source": "backfill",
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


# ─── Drift protection (2026-07-28 finding) ─────────────────────────────
# raw_extras.user._id was found to change under re-fetch for ~4-5% of
# already-ingested orders. When the existing row already has a trusted
# user_id, this run must refuse to write ANYTHING for that order unless
# the fresh fetch's user_id matches it exactly.

def test_matching_user_id_allows_normal_writes():
    row = _FakeEventOrder(
        customer_email=None, payment_token=None,
        raw_extras={"user": {"_id": "trusted123"}},
    )
    report = BackfillReport()
    fetched = [_fo(
        "ord-1",
        customer_email="jane@example.com",
        payment_token="tok-1",
        raw_extras_user={"_id": "trusted123"},  # matches
    )]

    updates = _compute_updates(fetched, existing={"ord-1": row}, report=report)

    assert report.skipped_for_drift == 0
    assert len(updates) == 1
    values = updates[0][1]
    assert values["customer_email"] == "jane@example.com"
    assert values["payment_token"] == "tok-1"
    # raw_extras already non-null on the existing row -> never rewritten,
    # drift or no drift.
    assert "raw_extras" not in values


def test_mismatched_user_id_skips_everything_for_that_order():
    """The hard rule: a fresh fetch disagreeing with the trusted stored
    user_id means NOTHING from that fetch is trusted for this order —
    not even email/token, even though they look independent."""
    row = _FakeEventOrder(
        customer_email=None, payment_token=None,
        raw_extras={"user": {"_id": "trusted123"}},
    )
    report = BackfillReport()
    fetched = [_fo(
        "ord-1",
        customer_email="jane@example.com",
        payment_token="tok-1",
        raw_extras_user={"_id": "different456"},  # does NOT match
    )]

    updates = _compute_updates(fetched, existing={"ord-1": row}, report=report)

    assert report.skipped_for_drift == 1
    assert report.matched_existing_order == 1
    assert report.would_update == 0
    assert updates == []


def test_fresh_fetch_returning_no_user_at_all_counts_as_drift():
    """Existing row has a trusted user_id; this fetch's order has NO user
    field at all (e.g. a cash/guest re-read). Treated as a mismatch, not
    a harmless absence — we don't know why it's gone, so nothing writes."""
    row = _FakeEventOrder(raw_extras={"user": {"_id": "trusted123"}})
    report = BackfillReport()
    fetched = [_fo("ord-1", customer_email="jane@example.com", raw_extras_user=None)]

    updates = _compute_updates(fetched, existing={"ord-1": row}, report=report)

    assert report.skipped_for_drift == 1
    assert updates == []


def test_no_existing_user_id_skips_drift_check_entirely():
    """Sundance-14 case: no stored user_id to compare against at all —
    this is a straight recovery, not a verified-match write. Confirms the
    drift gate only engages when there's something to check against."""
    row = _FakeEventOrder(raw_extras=None)
    report = BackfillReport()
    fetched = [_fo("ord-1", customer_email="jane@example.com", raw_extras_user={"_id": "new123"})]

    updates = _compute_updates(fetched, existing={"ord-1": row}, report=report)

    assert report.skipped_for_drift == 0
    assert len(updates) == 1
    assert updates[0][1]["customer_email"] == "jane@example.com"
    assert updates[0][1]["raw_extras"]["user_source"] == "backfill"


def test_existing_raw_extras_without_user_key_skips_drift_check():
    """Existing row's raw_extras is non-null but has no 'user' key at all
    (e.g. operator-only) — there is still nothing to drift-check against,
    so email/token proceed normally; raw_extras itself stays untouched
    (already-populated-column rule, unrelated to drift)."""
    row = _FakeEventOrder(
        customer_email=None,
        raw_extras={"operator": {"_id": "op1"}},
    )
    report = BackfillReport()
    fetched = [_fo("ord-1", customer_email="jane@example.com", raw_extras_user={"_id": "new123"})]

    updates = _compute_updates(fetched, existing={"ord-1": row}, report=report)

    assert report.skipped_for_drift == 0
    assert updates[0][1] == {"customer_email": "jane@example.com"}


def test_duplicate_fetched_order_id_deduped_before_diffing():
    """Chunk-boundary overlap can hand back the same order twice. Must not
    double-count matched/would_update or queue the same UPDATE twice."""
    row = _FakeEventOrder(customer_email=None)
    report = BackfillReport()
    fetched = [
        _fo("ord-1", customer_email="jane@example.com"),
        _fo("ord-1", customer_email="jane@example.com"),  # same order, re-fetched
    ]

    updates = _compute_updates(fetched, existing={"ord-1": row}, report=report)

    assert report.matched_existing_order == 1
    assert report.would_update == 1
    assert len(updates) == 1


def test_drift_examples_capped_at_five_and_show_truncated_ids():
    report = BackfillReport()
    rows = {
        f"ord-{i}": _FakeEventOrder(raw_extras={"user": {"_id": f"trusted{i}"}})
        for i in range(8)
    }
    fetched = [_fo(f"ord-{i}", raw_extras_user={"_id": f"drifted{i}"}) for i in range(8)]

    _compute_updates(fetched, existing=rows, report=report)

    assert report.skipped_for_drift == 8
    assert len(report.drift_examples) == 5
    for ex in report.drift_examples:
        assert ex["existing_user_id"].endswith("...")
        assert ex["fresh_user_id"].endswith("...")
