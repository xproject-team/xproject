"""Tests for Phase F: year-weighted fallback mean + auto-retrain.

NOTE on scope: Phase F also set out to add year-segmented shape
curves, hour-of-day weighting, a first-hour signal booster, and
per-year confidence recalibration. All four were back-tested
leave-one-out and made MAPE WORSE at every hour checkpoint (see
app/modules/predictions/nowcast/predictor.py's "Phase F — what shipped
and what didn't" docstring, and backend/scripts/test_nowcast_predictor.py's
comparison table). All four were reverted — there is deliberately no
"first-hour booster fires" test here, because that feature isn't
shipped. Only the year-weighted fallback mean and the auto-retrain
pipeline survived back-testing.

retrain tests write to a TEMPORARY copy of the real parquet files
(never the live app/modules/predictions/nowcast/data/ directory) via
retrain_from_completed_events's data_dir parameter — the running
predictor singleton (and other tests) must never see test data.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Tenant
from app.modules.bars.models import Bar
from app.modules.events.models import Event, EventStatus
from app.modules.predictions.nowcast.predictor import DATA_DIR, year_weighted_fallback_mean
from app.modules.predictions.nowcast.retrain import retrain_from_completed_events
from app.modules.products.models import Product, ProductType, ProductUnit
from app.modules.stock_transactions.models import StockTransaction, TransactionSource
from app.modules.venues.models import Venue


# ─── Pure-function tests: year_weighted_fallback_mean ─────────────────

def test_year_weighted_mean_weights_newest_year_2x():
    events_df = pd.DataFrame({
        "event_id":      ["a", "b", "c"],
        "event_date":    [pd.Timestamp("2024-06-01"), pd.Timestamp("2025-06-01"), pd.Timestamp("2025-07-01")],
        "total_revenue": [50_000.0, 40_000.0, 42_000.0],
    })
    # 2024 mean = 50000 (n=1). 2025 mean = 41000 (n=2). target=2026 ->
    # most recent 2 years present at/before 2026 = [2025, 2024], weighted 2x/1x.
    result = year_weighted_fallback_mean(events_df, target_year=2026)
    expected = (2 * 41_000.0 + 1 * 50_000.0) / 3
    assert result == pytest.approx(expected)


def test_year_weighted_mean_falls_back_to_single_year_when_only_one_available():
    events_df = pd.DataFrame({
        "event_id":      ["a", "b"],
        "event_date":    [pd.Timestamp("2024-06-01"), pd.Timestamp("2024-07-01")],
        "total_revenue": [50_000.0, 52_000.0],
    })
    # No year before-or-equal to 2024 other than 2024 itself.
    result = year_weighted_fallback_mean(events_df, target_year=2024)
    assert result == pytest.approx(51_000.0)


def test_year_weighted_mean_ignores_future_years():
    events_df = pd.DataFrame({
        "event_id":      ["a", "b"],
        "event_date":    [pd.Timestamp("2024-06-01"), pd.Timestamp("2026-06-01")],
        "total_revenue": [50_000.0, 10_000.0],
    })
    # target_year=2024: the 2026 row is in the future relative to the
    # target and must not be included.
    result = year_weighted_fallback_mean(events_df, target_year=2024)
    assert result == pytest.approx(50_000.0)


# ─── Auto-retrain tests ─────────────────────────────────────────────

async def _make_isolated_tenant(db: AsyncSession) -> Tenant:
    """A throwaway tenant, NOT noma-group. The dev DB's noma-group
    tenant already has 16 pre-existing COMPLETED events (mostly
    "Sundance 14 — SIMULATION" seed/test data with real transaction
    volumes, plus a "Sundance 2026" event) — retrain_from_completed_events
    would pick up ALL of them, not just what a test creates, making
    exact-count assertions against noma-group nondeterministic. See
    this module's docstring / the Phase F report for why that's also a
    real design gap worth flagging (no filter distinguishes real
    events from simulation/test data in the retrain query)."""
    t = Tenant(name=f"retrain-test-tenant-{uuid4().hex[:8]}", slug=uuid4().hex[:12])
    db.add(t)
    await db.flush()
    return t


async def _create_venue(db: AsyncSession, tenant_id: UUID) -> Venue:
    v = Venue(tenant_id=tenant_id, name=f"Test Venue {uuid4().hex[:8]}", address="Test address")
    db.add(v)
    await db.flush()
    return v


async def _create_completed_event(
    db: AsyncSession, tenant_id: UUID, venue_id: UUID, *, is_training_eligible: bool = True,
) -> Event:
    ev = Event(
        tenant_id=tenant_id,
        venue_id=venue_id,
        name=f"Retrain Test Event {uuid4().hex[:8]}",
        scheduled_at=datetime(2026, 5, 1, 18, 0, tzinfo=timezone.utc),
        scheduled_end_at=datetime(2026, 5, 2, 4, 0, tzinfo=timezone.utc),
        status=EventStatus.COMPLETED,
        ended_at=datetime(2026, 5, 2, 3, 0, tzinfo=timezone.utc),
        expected_guest_count=500,
        version=1,
        is_training_eligible=is_training_eligible,
    )
    db.add(ev)
    await db.flush()
    return ev


async def _create_bar(db: AsyncSession, tenant_id: UUID, event_id: UUID) -> Bar:
    bar = Bar(tenant_id=tenant_id, event_id=event_id, name=f"Bar-{uuid4().hex[:6]}",
              bar_type="drinks", is_active=True)
    db.add(bar)
    await db.flush()
    return bar


async def _create_product(db: AsyncSession, tenant_id: UUID) -> Product:
    p = Product(tenant_id=tenant_id, name=f"Test Drink {uuid4().hex[:8]}",
                product_type=ProductType.DRINK, unit=ProductUnit.GLASS)
    db.add(p)
    await db.flush()
    return p


async def _add_sale(db, tenant_id, event_id, bar_id, product_id, *, created_at, price_cents):
    tx = StockTransaction(
        tenant_id=tenant_id, event_id=event_id, bar_id=bar_id, product_id=product_id,
        qty=Decimal("1"), price_cents=price_cents, source=TransactionSource.SLESH_POS,
        source_idempotency_key=uuid4().hex, created_at=created_at,
    )
    db.add(tx)
    await db.flush()
    return tx


@pytest.fixture
def tmp_nowcast_data_dir(tmp_path: Path) -> Path:
    """A throwaway copy of the real training parquet files. retrain
    tests write here — never to the live nowcast/data/ directory that
    the running predictor singleton and other tests read from."""
    dest = tmp_path / "nowcast_data"
    dest.mkdir()
    shutil.copy(DATA_DIR / "training_events.parquet", dest / "training_events.parquet")
    shutil.copy(DATA_DIR / "training_transactions.parquet", dest / "training_transactions.parquet")
    return dest


@pytest.mark.asyncio
async def test_retrain_adds_completed_event_to_parquet(
    db_session: AsyncSession, tmp_nowcast_data_dir: Path,
):
    before = pd.read_parquet(tmp_nowcast_data_dir / "training_events.parquet")
    before_count = len(before)

    tenant = await _make_isolated_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_completed_event(db_session, tenant.id, venue.id)
    bar = await _create_bar(db_session, tenant.id, event.id)
    product = await _create_product(db_session, tenant.id)

    first_tx = datetime(2026, 5, 1, 18, 0, tzinfo=timezone.utc)
    await _add_sale(db_session, tenant.id, event.id, bar.id, product.id,
                     created_at=first_tx, price_cents=1_000_000)
    await _add_sale(db_session, tenant.id, event.id, bar.id, product.id,
                     created_at=first_tx + timedelta(hours=3), price_cents=500_000)
    await db_session.flush()

    result = await retrain_from_completed_events(db_session, tenant.id, data_dir=tmp_nowcast_data_dir)

    assert result["status"] == "ok"
    assert result["retrained"] is True
    assert str(event.id) in result["events_added_or_updated"]
    assert result["training_events_count"] == before_count + 1

    after = pd.read_parquet(tmp_nowcast_data_dir / "training_events.parquet")
    assert len(after) == before_count + 1
    new_row = after[after["event_id"] == str(event.id)].iloc[0]
    assert new_row["total_revenue"] == pytest.approx(15_000.0)  # 10000 + 5000

    tx_after = pd.read_parquet(tmp_nowcast_data_dir / "training_transactions.parquet")
    assert (tx_after["event_id"] == str(event.id)).sum() == 2


@pytest.mark.asyncio
async def test_retrain_is_idempotent_on_rerun(
    db_session: AsyncSession, tmp_nowcast_data_dir: Path,
):
    """Re-running retrain (e.g. two events completing in quick
    succession both enqueue the same dedup job_id) must upsert, not
    duplicate, an already-merged event."""
    tenant = await _make_isolated_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_completed_event(db_session, tenant.id, venue.id)
    bar = await _create_bar(db_session, tenant.id, event.id)
    product = await _create_product(db_session, tenant.id)
    await _add_sale(db_session, tenant.id, event.id, bar.id, product.id,
                     created_at=datetime(2026, 5, 1, 18, 0, tzinfo=timezone.utc), price_cents=200_000)
    await db_session.flush()

    result1 = await retrain_from_completed_events(db_session, tenant.id, data_dir=tmp_nowcast_data_dir)
    count_after_first = result1["training_events_count"]

    result2 = await retrain_from_completed_events(db_session, tenant.id, data_dir=tmp_nowcast_data_dir)
    assert result2["training_events_count"] == count_after_first  # no duplicate row

    after = pd.read_parquet(tmp_nowcast_data_dir / "training_events.parquet")
    assert (after["event_id"] == str(event.id)).sum() == 1


@pytest.mark.asyncio
async def test_retrain_skips_completed_event_with_no_revenue(
    db_session: AsyncSession, tmp_nowcast_data_dir: Path,
):
    before = pd.read_parquet(tmp_nowcast_data_dir / "training_events.parquet")
    before_count = len(before)

    tenant = await _make_isolated_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_completed_event(db_session, tenant.id, venue.id)  # no transactions
    await db_session.flush()

    result = await retrain_from_completed_events(db_session, tenant.id, data_dir=tmp_nowcast_data_dir)

    assert result["status"] == "no_completed_events_with_revenue"
    assert result["retrained"] is False
    assert str(event.id) in result["skipped_no_revenue"]

    after = pd.read_parquet(tmp_nowcast_data_dir / "training_events.parquet")
    assert len(after) == before_count  # untouched


@pytest.mark.asyncio
async def test_retrain_excludes_training_ineligible_completed_event(
    db_session: AsyncSession, tmp_nowcast_data_dir: Path,
):
    """A COMPLETED event with real revenue but is_training_eligible=False
    (e.g. a simulation/test fixture) must not be pulled into retraining
    — the contamination guard flagged in the Phase F report, shipped as
    migration aa3."""
    before = pd.read_parquet(tmp_nowcast_data_dir / "training_events.parquet")
    before_count = len(before)

    tenant = await _make_isolated_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    ineligible_event = await _create_completed_event(
        db_session, tenant.id, venue.id, is_training_eligible=False,
    )
    bar = await _create_bar(db_session, tenant.id, ineligible_event.id)
    product = await _create_product(db_session, tenant.id)
    await _add_sale(db_session, tenant.id, ineligible_event.id, bar.id, product.id,
                     created_at=datetime(2026, 5, 1, 18, 0, tzinfo=timezone.utc), price_cents=999_999)
    await db_session.flush()

    result = await retrain_from_completed_events(db_session, tenant.id, data_dir=tmp_nowcast_data_dir)

    # No ELIGIBLE completed events with revenue exist for this tenant —
    # the ineligible one must be filtered out at the query level, not
    # merely skipped-for-no-revenue (it has plenty of revenue).
    assert result["status"] == "no_completed_events_with_revenue"
    assert result["retrained"] is False
    assert str(ineligible_event.id) not in result.get("skipped_no_revenue", [])

    after = pd.read_parquet(tmp_nowcast_data_dir / "training_events.parquet")
    assert len(after) == before_count
    assert str(ineligible_event.id) not in set(after["event_id"])


@pytest.mark.asyncio
async def test_retrain_includes_eligible_but_excludes_ineligible_sibling(
    db_session: AsyncSession, tmp_nowcast_data_dir: Path,
):
    """Mixed tenant: one eligible + one ineligible COMPLETED event, both
    with revenue. Only the eligible one should land in the retrained
    parquet."""
    tenant = await _make_isolated_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)

    eligible_event = await _create_completed_event(db_session, tenant.id, venue.id, is_training_eligible=True)
    ineligible_event = await _create_completed_event(db_session, tenant.id, venue.id, is_training_eligible=False)

    eligible_bar = await _create_bar(db_session, tenant.id, eligible_event.id)
    ineligible_bar = await _create_bar(db_session, tenant.id, ineligible_event.id)
    product = await _create_product(db_session, tenant.id)

    await _add_sale(db_session, tenant.id, eligible_event.id, eligible_bar.id, product.id,
                     created_at=datetime(2026, 5, 1, 18, 0, tzinfo=timezone.utc), price_cents=300_000)
    await _add_sale(db_session, tenant.id, ineligible_event.id, ineligible_bar.id, product.id,
                     created_at=datetime(2026, 5, 1, 18, 0, tzinfo=timezone.utc), price_cents=999_999)
    await db_session.flush()

    result = await retrain_from_completed_events(db_session, tenant.id, data_dir=tmp_nowcast_data_dir)

    assert result["status"] == "ok"
    assert str(eligible_event.id) in result["events_added_or_updated"]
    assert str(ineligible_event.id) not in result["events_added_or_updated"]

    after = pd.read_parquet(tmp_nowcast_data_dir / "training_events.parquet")
    ids = set(after["event_id"])
    assert str(eligible_event.id) in ids
    assert str(ineligible_event.id) not in ids
