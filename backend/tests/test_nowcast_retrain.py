"""Tests for Phase F: year-weighted fallback mean + auto-retrain, and the
2026-08 fix moving nowcast persistence off shared/ephemeral parquet
files onto model_artifacts (tenant_id-scoped, versioned, durable — see
nowcast/predictor.py's module docstring for the full rationale: the old
design let every tenant's Dashboard forecast be computed from the SAME
historical basis, and every retrain's output was silently discarded on
the next Railway deploy).

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

retrain tests write their (non-durable, debug-only) local file copy to
a tmp_path fixture — never the real app/modules/predictions/nowcast/
artifacts/nowcast/ directory — and their durable output to
model_artifacts via the SAVEPOINT db_session fixture, so xproject_dev
is never mutated.
"""
from __future__ import annotations

import pickle
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
from app.modules.predictions.models import ModelArtifact
from app.modules.predictions.nowcast.loader import (
    NOT_TRAINED_REASON,
    get_active_nowcast_predictor,
)
from app.modules.predictions.nowcast.predictor import DATA_DIR, year_weighted_fallback_mean
from app.modules.predictions.nowcast.retrain import (
    MODEL_NAME,
    bootstrap_from_static_dataset,
    retrain_from_completed_events,
)
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
    result = year_weighted_fallback_mean(events_df, target_year=2024)
    assert result == pytest.approx(51_000.0)


def test_year_weighted_mean_ignores_future_years():
    events_df = pd.DataFrame({
        "event_id":      ["a", "b"],
        "event_date":    [pd.Timestamp("2024-06-01"), pd.Timestamp("2026-06-01")],
        "total_revenue": [50_000.0, 10_000.0],
    })
    result = year_weighted_fallback_mean(events_df, target_year=2024)
    assert result == pytest.approx(50_000.0)


# ─── Fixtures + helpers ─────────────────────────────────────────────

async def _make_isolated_tenant(db: AsyncSession, *, name: str | None = None) -> Tenant:
    """A throwaway tenant, NOT noma-group. Post-fix, a fresh tenant's
    retrain starts from ZERO prior events — no inherited historical
    baseline from anyone else — so exact-count assertions are safe and
    deterministic here, unlike against noma-group's own real data."""
    t = Tenant(name=name or f"retrain-test-tenant-{uuid4().hex[:8]}", slug=uuid4().hex[:12])
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


async def _active_artifact_bundle(db: AsyncSession, tenant_id: UUID) -> dict | None:
    row = (await db.execute(
        select(ModelArtifact.file_bytes).where(
            ModelArtifact.tenant_id == tenant_id,
            ModelArtifact.model_name == MODEL_NAME,
            ModelArtifact.is_active.is_(True),
        )
    )).first()
    return pickle.loads(row[0]) if row is not None else None


@pytest.fixture
def tmp_artifacts_dir(tmp_path: Path) -> Path:
    """Where retrain's best-effort, non-durable local debug copy goes in
    tests — never the real app/modules/predictions/artifacts/nowcast/
    directory. Nothing in these tests depends on this file; the durable
    artifact is model_artifacts.file_bytes, asserted via the DB."""
    return tmp_path / "nowcast_artifacts"


# ─── Auto-retrain tests ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrain_creates_artifact_with_only_this_tenants_event(
    db_session: AsyncSession, tmp_artifacts_dir: Path,
):
    """Post-isolation-fix: a fresh tenant's first retrain contains
    ONLY their own event — not noma-group's 9 bootstrapped historical
    events, not anyone else's. This is the isolation fix's core
    behavior change from the old shared-parquet design."""
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

    result = await retrain_from_completed_events(
        db_session, tenant.id, triggered_by="test", artifacts_dir=tmp_artifacts_dir,
    )

    assert result["status"] == "ok"
    assert result["retrained"] is True
    assert str(event.id) in result["events_added_or_updated"]
    assert result["training_events_count"] == 1  # NOT 9+1 — no inherited historical baseline

    bundle = await _active_artifact_bundle(db_session, tenant.id)
    assert bundle is not None
    assert set(bundle["events_df"]["event_id"]) == {str(event.id)}
    new_row = bundle["events_df"][bundle["events_df"]["event_id"] == str(event.id)].iloc[0]
    assert new_row["total_revenue"] == pytest.approx(15_000.0)  # 10000 + 5000
    assert (bundle["transactions_df"]["event_id"] == str(event.id)).sum() == 2


@pytest.mark.asyncio
async def test_retrain_is_idempotent_on_rerun(
    db_session: AsyncSession, tmp_artifacts_dir: Path,
):
    """Re-running retrain (e.g. two events completing in quick
    succession both enqueue the same dedup job_id) must upsert, not
    duplicate, an already-merged event within the resulting artifact."""
    tenant = await _make_isolated_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_completed_event(db_session, tenant.id, venue.id)
    bar = await _create_bar(db_session, tenant.id, event.id)
    product = await _create_product(db_session, tenant.id)
    await _add_sale(db_session, tenant.id, event.id, bar.id, product.id,
                     created_at=datetime(2026, 5, 1, 18, 0, tzinfo=timezone.utc), price_cents=200_000)
    await db_session.flush()

    result1 = await retrain_from_completed_events(
        db_session, tenant.id, triggered_by="test", artifacts_dir=tmp_artifacts_dir,
    )
    result2 = await retrain_from_completed_events(
        db_session, tenant.id, triggered_by="test", artifacts_dir=tmp_artifacts_dir,
    )
    assert result2["training_events_count"] == result1["training_events_count"]  # no duplicate row
    assert result2["version"] == result1["version"] + 1  # each retrain still versions forward

    bundle = await _active_artifact_bundle(db_session, tenant.id)
    assert (bundle["events_df"]["event_id"] == str(event.id)).sum() == 1


@pytest.mark.asyncio
async def test_retrain_skips_completed_event_with_no_revenue(
    db_session: AsyncSession, tmp_artifacts_dir: Path,
):
    tenant = await _make_isolated_tenant(db_session)
    venue = await _create_venue(db_session, tenant.id)
    event = await _create_completed_event(db_session, tenant.id, venue.id)  # no transactions
    await db_session.flush()

    result = await retrain_from_completed_events(
        db_session, tenant.id, triggered_by="test", artifacts_dir=tmp_artifacts_dir,
    )

    assert result["status"] == "no_completed_events_with_revenue"
    assert result["retrained"] is False
    assert str(event.id) in result["skipped_no_revenue"]
    assert await _active_artifact_bundle(db_session, tenant.id) is None  # nothing written


@pytest.mark.asyncio
async def test_retrain_excludes_training_ineligible_completed_event(
    db_session: AsyncSession, tmp_artifacts_dir: Path,
):
    """A COMPLETED event with real revenue but is_training_eligible=False
    (e.g. a simulation/test fixture) must not be pulled into retraining
    — the contamination guard flagged in the Phase F report, shipped as
    migration aa3."""
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

    result = await retrain_from_completed_events(
        db_session, tenant.id, triggered_by="test", artifacts_dir=tmp_artifacts_dir,
    )

    # No ELIGIBLE completed events with revenue exist for this tenant —
    # the ineligible one must be filtered out at the query level, not
    # merely skipped-for-no-revenue (it has plenty of revenue).
    assert result["status"] == "no_completed_events_with_revenue"
    assert result["retrained"] is False
    assert str(ineligible_event.id) not in result.get("skipped_no_revenue", [])
    assert await _active_artifact_bundle(db_session, tenant.id) is None


@pytest.mark.asyncio
async def test_retrain_includes_eligible_but_excludes_ineligible_sibling(
    db_session: AsyncSession, tmp_artifacts_dir: Path,
):
    """Mixed tenant: one eligible + one ineligible COMPLETED event, both
    with revenue. Only the eligible one should land in the artifact."""
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

    result = await retrain_from_completed_events(
        db_session, tenant.id, triggered_by="test", artifacts_dir=tmp_artifacts_dir,
    )

    assert result["status"] == "ok"
    assert str(eligible_event.id) in result["events_added_or_updated"]
    assert str(ineligible_event.id) not in result["events_added_or_updated"]

    bundle = await _active_artifact_bundle(db_session, tenant.id)
    ids = set(bundle["events_df"]["event_id"])
    assert str(eligible_event.id) in ids
    assert str(ineligible_event.id) not in ids


# ─── Cross-tenant isolation ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrain_writes_only_to_own_tenants_artifact_and_predictor_never_crosses(
    db_session: AsyncSession, tmp_artifacts_dir: Path,
):
    """The two isolation requirements together: (1) tenant A's retrain
    writes only to A's model_artifacts row, never touching or creating
    one for B; (2) loading each tenant's active predictor never
    reflects the other tenant's event or revenue figures."""
    tenant_a = await _make_isolated_tenant(db_session, name="Isolation Tenant A")
    tenant_b = await _make_isolated_tenant(db_session, name="Isolation Tenant B")

    venue_a = await _create_venue(db_session, tenant_a.id)
    venue_b = await _create_venue(db_session, tenant_b.id)
    event_a = await _create_completed_event(db_session, tenant_a.id, venue_a.id)
    event_b = await _create_completed_event(db_session, tenant_b.id, venue_b.id)
    bar_a = await _create_bar(db_session, tenant_a.id, event_a.id)
    bar_b = await _create_bar(db_session, tenant_b.id, event_b.id)
    product_a = await _create_product(db_session, tenant_a.id)
    product_b = await _create_product(db_session, tenant_b.id)

    # Deliberately very different revenue so any cross-contamination is
    # immediately visible in historical_mean, not just row counts.
    await _add_sale(db_session, tenant_a.id, event_a.id, bar_a.id, product_a.id,
                     created_at=datetime(2026, 5, 1, 18, 0, tzinfo=timezone.utc), price_cents=10_000_00)
    await _add_sale(db_session, tenant_b.id, event_b.id, bar_b.id, product_b.id,
                     created_at=datetime(2026, 5, 1, 18, 0, tzinfo=timezone.utc), price_cents=90_000_00)
    await db_session.flush()

    result_a = await retrain_from_completed_events(
        db_session, tenant_a.id, triggered_by="test", artifacts_dir=tmp_artifacts_dir,
    )
    result_b = await retrain_from_completed_events(
        db_session, tenant_b.id, triggered_by="test", artifacts_dir=tmp_artifacts_dir,
    )

    # (1) Each retrain wrote only its own tenant's artifact.
    bundle_a = await _active_artifact_bundle(db_session, tenant_a.id)
    bundle_b = await _active_artifact_bundle(db_session, tenant_b.id)
    assert set(bundle_a["events_df"]["event_id"]) == {str(event_a.id)}
    assert set(bundle_b["events_df"]["event_id"]) == {str(event_b.id)}
    assert str(event_b.id) not in set(bundle_a["events_df"]["event_id"])
    assert str(event_a.id) not in set(bundle_b["events_df"]["event_id"])
    assert result_a["training_events_count"] == 1
    assert result_b["training_events_count"] == 1

    # (2) Loading each tenant's predictor never reflects the other's data.
    predictor_a, reason_a = await get_active_nowcast_predictor(db_session, tenant_a.id)
    predictor_b, reason_b = await get_active_nowcast_predictor(db_session, tenant_b.id)
    assert predictor_a is not None, reason_a
    assert predictor_b is not None, reason_b
    assert predictor_a.historical_n == 1
    assert predictor_b.historical_n == 1
    assert predictor_a.historical_mean == pytest.approx(10_000.0)
    assert predictor_b.historical_mean == pytest.approx(90_000.0)
    assert set(predictor_a._events_df["event_id"]) == {str(event_a.id)}
    assert set(predictor_b._events_df["event_id"]) == {str(event_b.id)}


@pytest.mark.asyncio
async def test_predictor_for_tenant_with_no_artifact_is_none_not_an_error_or_fabricated(
    db_session: AsyncSession,
):
    """A tenant that has never retrained (the common case) gets an
    explicit, honest (None, reason) — never raises, and never silently
    substitutes another tenant's fitted predictor."""
    tenant = await _make_isolated_tenant(db_session)

    predictor, reason = await get_active_nowcast_predictor(db_session, tenant.id)

    assert predictor is None
    assert reason == NOT_TRAINED_REASON


# ─── Bootstrap ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bootstrap_lands_in_the_requested_tenant_only(
    db_session: AsyncSession, tmp_artifacts_dir: Path,
):
    """bootstrap_from_static_dataset seeds the historical 9-event
    dataset into whichever tenant_id it's called with — proving the
    mechanism is tenant-targeted, not hardcoded to always land on
    Noma Group (the production script just happens to always call it
    with Noma Group's id — see scripts/bootstrap_nowcast_artifact.py).
    A different, untouched tenant must not be affected."""
    target_tenant = await _make_isolated_tenant(db_session, name="Bootstrap Target")
    bystander_tenant = await _make_isolated_tenant(db_session, name="Bootstrap Bystander")

    result = await bootstrap_from_static_dataset(
        db_session, target_tenant.id, data_dir=DATA_DIR, artifacts_dir=tmp_artifacts_dir,
    )

    assert result["status"] == "ok"
    assert result["retrained"] is True
    assert result["n_training_events"] == 9

    bundle = await _active_artifact_bundle(db_session, target_tenant.id)
    assert bundle is not None
    assert bundle["historical_n"] == 9

    # The bystander tenant must remain completely untouched.
    assert await _active_artifact_bundle(db_session, bystander_tenant.id) is None


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent_and_refuses_to_overwrite(
    db_session: AsyncSession, tmp_artifacts_dir: Path,
):
    tenant = await _make_isolated_tenant(db_session)

    first = await bootstrap_from_static_dataset(
        db_session, tenant.id, data_dir=DATA_DIR, artifacts_dir=tmp_artifacts_dir,
    )
    assert first["status"] == "ok"

    second = await bootstrap_from_static_dataset(
        db_session, tenant.id, data_dir=DATA_DIR, artifacts_dir=tmp_artifacts_dir,
    )
    assert second["status"] == "already_bootstrapped"
    assert second["retrained"] is False

    # Still exactly one active artifact — the second call created nothing new.
    row_count = (await db_session.execute(
        select(ModelArtifact.id).where(
            ModelArtifact.tenant_id == tenant.id,
            ModelArtifact.model_name == MODEL_NAME,
            ModelArtifact.is_active.is_(True),
        )
    )).all()
    assert len(row_count) == 1
