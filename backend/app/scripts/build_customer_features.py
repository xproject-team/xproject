"""CLI: build customer_sessions + customer_purchases from Slesh-sourced data.

Usage:
    python -m app.scripts.build_customer_features \\
        --tenant-id 25ef916c-a288-44ae-b17c-8dfd09390834 \\
        --event-id 9ae0dc52-8a01-4998-b430-3814bd8cdabe \\
        --expected-customers 980

    # or all three events in one run, in order:
    python -m app.scripts.build_customer_features \\
        --tenant-id 25ef916c-a288-44ae-b17c-8dfd09390834 \\
        --events 6bd035a9-3ab4-4c7f-8f68-c811aef9fa47:1256 \\
                 0888f4b7-7030-426b-815c-938e6ca447a6:1206 \\
                 9ae0dc52-8a01-4998-b430-3814bd8cdabe:980

SCOPE RULE (hard): reads ONLY event_orders, stock_transactions, products,
bars. Never joins recipes, bar_stock, inventory, alerts, or warehouse —
if a metric would need one of those, it doesn't belong in this script.

BUILD RULES
-----------
1. customer_key = event_orders.raw_extras->'user'->>'_id'. Orders where
   this is NULL are skipped entirely — never invented.
2. Drink/food lines join to their order via
   stock_transactions.source_idempotency_key, format
   "slesh:{order_id}:{line_id}" — split on ':', middle segment ->
   event_orders.slesh_order_id (same join proven in the identity audit,
   100% match rate on all three events).
3. Only source_idempotency_key IS NOT NULL rows are read — excludes
   recipe-cascade child rows (currently 0 in production, but the filter
   stays regardless of whether the cascade ever fires).
4. ordered_at is ALWAYS event_orders.created_at_slesh. NEVER
   stock_transactions.created_at — that's the poller's ingestion
   timestamp (median lag 25-48s, tail up to 6.6h) and would corrupt any
   hourly analysis built on top of this table.
5. session_minutes = last_order_at - first_order_at. Time BETWEEN
   purchases, NOT attendance duration — documented on the column itself
   (see the ac1 migration).
6. category is derived from the products catalog via bucket_category()
   below — spritz is checked by product NAME first (it has no dedicated
   catalog category; every spritz SKU is filed under basic_cocktail),
   everything else falls through to the catalog category. Products with
   a NULL catalog category are grouped into 'other' but reported
   separately as "unmapped" so the gap in the source catalog stays
   visible, not silently absorbed.

SANITY GATE (hard failure, not a warning)
------------------------------------------
Distinct customers per event must match the value the caller supplies
via --expected-customers (or the events:N pairs). This is checked
BEFORE any write — a mismatch aborts with diagnostics and commits
nothing, for that event only. This is the same "hard failure gate"
pattern used in backfill_customer_identity.py's prediction check.

Idempotent: re-running for an event first deletes any existing
customer_sessions/customer_purchases rows for that (tenant, event),
then rebuilds from scratch. Never touches event_orders,
stock_transactions, products, or bars.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import AsyncSessionLocal
from app.modules.auth.models import Tenant  # noqa: F401 - registers mapper deps
from app.modules.customer_analytics.models import CustomerPurchase, CustomerSession

# One SQL query does the entire scope-legal join: stock_transactions ->
# event_orders (by parsed idempotency key) -> products. tenant_id is
# taken from event_orders (bars/products are tenant-scoped too, but the
# FK chain through event_id already pins the tenant).
_PURCHASE_ROWS_SQL = text("""
    select
        eo.raw_extras->'user'->>'_id'   as customer_key,
        eo.slesh_order_id               as slesh_order_id,
        eo.created_at_slesh             as ordered_at,
        eo.customer_email               as customer_email,
        coalesce(eo.raw_extras->>'user_source', 'live') as user_source,
        st.id                            as stock_transaction_id,
        st.product_id                   as product_id,
        st.bar_id                       as bar_id,
        st.qty                          as qty,
        st.price_cents                  as price_cents,
        p.name                          as product_name,
        p.product_type                  as product_type,
        p.category                      as product_category
    from stock_transactions st
    join event_orders eo
      on eo.slesh_order_id = split_part(st.source_idempotency_key, ':', 2)
     and eo.event_id = st.event_id
    join products p on p.id = st.product_id
    where st.event_id = :event_id
      and st.tenant_id = :tenant_id
      and st.source_idempotency_key like 'slesh:%'
      and eo.raw_extras->'user'->>'_id' is not null
""")

_NULL_KEY_ORDER_COUNT_SQL = text("""
    select count(*) from event_orders
    where event_id = :event_id and tenant_id = :tenant_id
      and raw_extras->'user'->>'_id' is null
""")


# ─────────────────────────────────────────────────────────────────────
# Pure logic — no I/O, unit tested directly
# ─────────────────────────────────────────────────────────────────────
def normalize_product_name(name: str) -> str:
    """Trim + collapse whitespace + lowercase, for GROUPING duplicate
    catalog entries in the unmapped-product report only. The actual
    category join is always by product_id (exact), never by name — this
    exists purely so 'Bottiglia Vino' and 'Bottiglia Vino ' (a real
    catalog duplicate, trailing-space typo) don't appear as two
    different products in a report meant for a human to read.
    """
    return " ".join((name or "").split()).lower()


def bucket_category(product_type: str, product_category: str | None, product_name: str) -> str:
    """Map a purchased product to one of the 7 buckets this feature
    layer reports on: beer | cocktail | spritz | wine | premium | other
    | food. Spritz is name-based (no dedicated catalog category — every
    spritz SKU, including the misspelled "Sprtiz Arancio", is filed
    under basic_cocktail) and is checked before catalog category so it
    doesn't fall into 'cocktail'.
    """
    if product_type == "food":
        return "food"
    name_lower = (product_name or "").lower()
    if "spritz" in name_lower or "sprtiz" in name_lower:
        return "spritz"
    if product_category in ("beer_draft", "beer_bottle"):
        return "beer"
    if product_category == "premium_cocktail":
        return "premium"
    if product_category in ("wine_red", "wine_white", "wine_sparkling"):
        return "wine"
    if product_category == "basic_cocktail":
        return "cocktail"
    # soft_drink, NULL category, or anything else not explicitly bucketed
    return "other"


_CATEGORY_COUNT_COLUMNS = ("beer", "cocktail", "spritz", "wine", "premium", "other")


@dataclass
class SessionBuildResult:
    session: dict
    unmapped_products: set[tuple[str, str]] = field(default_factory=set)  # (normalized_name, product_id)


def build_session_row(
    *, tenant_id: UUID, event_id: UUID, customer_key: str, lines: list[dict],
) -> SessionBuildResult:
    """Pure aggregation: given every purchase line dict already attributed
    to one customer at one event (each dict must have the same keys the
    SQL query above returns, plus a 'bucket' key already computed),
    produce the CustomerSession row. No I/O.
    """
    ordered_ats = [ln["ordered_at"] for ln in lines]
    first_order_at = min(ordered_ats)
    last_order_at = max(ordered_ats)
    session_minutes = round((last_order_at - first_order_at).total_seconds() / 60.0, 2)

    order_ids = {ln["slesh_order_id"] for ln in lines}
    order_count = len(order_ids)

    total_spend_cents = sum(int(round(float(ln["qty"]) * (ln["price_cents"] or 0))) for ln in lines)
    avg_order_cents = int(round(total_spend_cents / order_count)) if order_count else 0

    bar_ids = [ln["bar_id"] for ln in lines if ln["bar_id"] is not None]
    distinct_bars = len(set(bar_ids))
    first_bar_id = min(lines, key=lambda ln: ln["ordered_at"])["bar_id"]

    emails = [ln["customer_email"] for ln in lines if ln["customer_email"]]
    email_domain = emails[0].split("@", 1)[1] if emails and "@" in emails[0] else None
    is_registered = (email_domain != "slesh.it") if email_domain is not None else None

    user_source = "backfill" if any(ln["user_source"] == "backfill" for ln in lines) else "live"

    drink_lines = [ln for ln in lines if ln["bucket"] != "food"]
    food_lines = [ln for ln in lines if ln["bucket"] == "food"]
    bucket_counts = Counter(ln["bucket"] for ln in drink_lines)

    unmapped = {
        (normalize_product_name(ln["product_name"]), str(ln["product_id"]))
        for ln in lines
        if ln["product_type"] != "food" and ln["product_category"] is None
    }

    session = dict(
        id=uuid4(),
        tenant_id=tenant_id,
        event_id=event_id,
        customer_key=customer_key,
        first_order_at=first_order_at,
        last_order_at=last_order_at,
        session_minutes=session_minutes,
        order_count=order_count,
        total_spend_cents=total_spend_cents,
        avg_order_cents=avg_order_cents,
        distinct_bars=distinct_bars,
        first_bar_id=first_bar_id,
        is_registered=is_registered,
        email_domain=email_domain,
        user_source=user_source,
        drink_count=len(drink_lines),
        food_count=len(food_lines),
        beer_count=bucket_counts.get("beer", 0),
        cocktail_count=bucket_counts.get("cocktail", 0),
        spritz_count=bucket_counts.get("spritz", 0),
        wine_count=bucket_counts.get("wine", 0),
        premium_count=bucket_counts.get("premium", 0),
        other_count=bucket_counts.get("other", 0),
    )
    return SessionBuildResult(session=session, unmapped_products=unmapped)


def percentile_stats(values: list[float]) -> tuple[float, float]:
    """(median, p90). Returns (0.0, 0.0) for an empty list."""
    if not values:
        return 0.0, 0.0
    arr = np.array(values, dtype=float)
    return float(np.percentile(arr, 50)), float(np.percentile(arr, 90))


# ─────────────────────────────────────────────────────────────────────
# I/O — fetch, orchestrate, write
# ─────────────────────────────────────────────────────────────────────
async def fetch_purchase_lines(db, tenant_id: UUID, event_id: UUID) -> list[dict]:
    res = await db.execute(_PURCHASE_ROWS_SQL, {"tenant_id": tenant_id, "event_id": event_id})
    rows = res.mappings().all()
    lines = []
    for r in rows:
        d = dict(r)
        d["bucket"] = bucket_category(d["product_type"], d["product_category"], d["product_name"])
        lines.append(d)
    return lines


async def fetch_null_key_order_count(db, tenant_id: UUID, event_id: UUID) -> int:
    res = await db.execute(_NULL_KEY_ORDER_COUNT_SQL, {"tenant_id": tenant_id, "event_id": event_id})
    return res.scalar_one()


@dataclass
class EventReport:
    event_id: UUID
    sessions_created: int = 0
    purchases_created: int = 0
    distinct_customers: int = 0
    expected_customers: int = 0
    sanity_passed: bool = False
    registered: int = 0
    guest: int = 0
    unknown_registration: int = 0
    orders_skipped_null_key: int = 0
    revenue_covered_cents: int = 0
    known_revenue_cents: int = 0
    unmapped_products: set = field(default_factory=set)
    median_orders: float = 0.0
    p90_orders: float = 0.0
    median_spend_cents: float = 0.0
    p90_spend_cents: float = 0.0
    median_session_minutes: float = 0.0
    p90_session_minutes: float = 0.0

    @property
    def revenue_coverage_pct(self) -> float:
        if not self.known_revenue_cents:
            return 0.0
        return 100.0 * self.revenue_covered_cents / self.known_revenue_cents


async def build_event(
    *, tenant_id: UUID, event_id: UUID, expected_customers: int, known_revenue_cents: int,
) -> EventReport:
    report = EventReport(event_id=event_id, expected_customers=expected_customers,
                          known_revenue_cents=known_revenue_cents)

    async with AsyncSessionLocal() as db:
        lines = await fetch_purchase_lines(db, tenant_id, event_id)
        report.orders_skipped_null_key = await fetch_null_key_order_count(db, tenant_id, event_id)

    by_customer: dict[str, list[dict]] = defaultdict(list)
    for ln in lines:
        by_customer[ln["customer_key"]].append(ln)

    session_rows = []
    purchase_rows = []
    unmapped: set[tuple[str, str]] = set()

    for customer_key, cust_lines in by_customer.items():
        result = build_session_row(
            tenant_id=tenant_id, event_id=event_id, customer_key=customer_key, lines=cust_lines,
        )
        session_rows.append(result.session)
        unmapped |= result.unmapped_products

        for ln in cust_lines:
            purchase_rows.append(dict(
                id=uuid4(),
                tenant_id=tenant_id,
                event_id=event_id,
                customer_key=customer_key,
                slesh_order_id=ln["slesh_order_id"],
                product_id=ln["product_id"],
                product_name=ln["product_name"],
                category=ln["bucket"],
                bar_id=ln["bar_id"],
                qty=ln["qty"],
                price_cents=ln["price_cents"],
                ordered_at=ln["ordered_at"],
            ))

    report.distinct_customers = len(session_rows)
    report.sessions_created = len(session_rows)
    report.purchases_created = len(purchase_rows)
    report.unmapped_products = unmapped
    report.revenue_covered_cents = sum(s["total_spend_cents"] for s in session_rows)

    report.registered = sum(1 for s in session_rows if s["is_registered"] is True)
    report.guest = sum(1 for s in session_rows if s["is_registered"] is False)
    report.unknown_registration = sum(1 for s in session_rows if s["is_registered"] is None)

    report.median_orders, report.p90_orders = percentile_stats([s["order_count"] for s in session_rows])
    report.median_spend_cents, report.p90_spend_cents = percentile_stats([s["total_spend_cents"] for s in session_rows])
    report.median_session_minutes, report.p90_session_minutes = percentile_stats([s["session_minutes"] for s in session_rows])

    # ── Hard sanity gate — checked BEFORE any write ─────────────────
    report.sanity_passed = (report.distinct_customers == expected_customers)
    if not report.sanity_passed:
        return report

    async with AsyncSessionLocal() as db:
        await db.execute(delete(CustomerPurchase).where(
            CustomerPurchase.tenant_id == tenant_id, CustomerPurchase.event_id == event_id,
        ))
        await db.execute(delete(CustomerSession).where(
            CustomerSession.tenant_id == tenant_id, CustomerSession.event_id == event_id,
        ))
        if session_rows:
            await db.execute(pg_insert(CustomerSession).values(session_rows))
        if purchase_rows:
            await db.execute(pg_insert(CustomerPurchase).values(purchase_rows))
        await db.commit()

    return report


def _print_report(label: str, r: EventReport, tenant_id: UUID) -> None:
    print()
    print("=" * 70)
    print(f"EVENT: {label}  ({r.event_id})")
    print("=" * 70)
    print(f"  sanity gate: distinct_customers={r.distinct_customers}  expected={r.expected_customers}  "
          + ("PASS" if r.sanity_passed else "!!! FAIL — NOTHING WRITTEN FOR THIS EVENT !!!"))
    if not r.sanity_passed:
        return
    print(f"  sessions created:   {r.sessions_created}")
    print(f"  purchases created:  {r.purchases_created}")
    print(f"  distinct customers: {r.distinct_customers}")
    print(f"  registered / guest / unknown: {r.registered} / {r.guest} / {r.unknown_registration}")
    print(f"  orders skipped for NULL customer_key: {r.orders_skipped_null_key}")
    print(f"  revenue covered: EUR{r.revenue_covered_cents/100:,.2f} / EUR{r.known_revenue_cents/100:,.2f}"
          f"  ({r.revenue_coverage_pct:.1f}%)")
    print(f"  orders per customer   — median {r.median_orders:.1f}  p90 {r.p90_orders:.1f}")
    print(f"  spend per customer    — median EUR{r.median_spend_cents/100:,.2f}  p90 EUR{r.p90_spend_cents/100:,.2f}")
    print(f"  session_minutes       — median {r.median_session_minutes:.1f}  p90 {r.p90_session_minutes:.1f}")
    print(f"  unmapped products (category IS NULL in catalog, normalized): {len(r.unmapped_products)}")
    for name, pid in sorted(r.unmapped_products):
        print(f"    {name!r}  (product_id={pid})")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="build_customer_features")
    p.add_argument("--tenant-id", required=True)
    p.add_argument("--event", action="append", required=True,
                   help="event_id:expected_customers:known_revenue_cents:label — repeatable, "
                        "processed in the order given.")
    return p


async def _run(args) -> int:
    tenant_id = UUID(args.tenant_id)
    overall_ok = True
    for spec in args.event:
        parts = spec.split(":")
        if len(parts) != 4:
            raise SystemExit(f"❌ --event must be event_id:expected_customers:known_revenue_cents:label, got {spec!r}")
        event_id_str, expected_str, revenue_str, label = parts
        report = await build_event(
            tenant_id=tenant_id,
            event_id=UUID(event_id_str),
            expected_customers=int(expected_str),
            known_revenue_cents=int(revenue_str),
        )
        _print_report(label, report, tenant_id)
        if not report.sanity_passed:
            overall_ok = False
            print()
            print(f"STOPPING after {label} — sanity gate failed, not proceeding to remaining events.")
            break
    return 0 if overall_ok else 1


def main() -> None:
    p = _build_parser()
    sys.exit(asyncio.run(_run(p.parse_args())))


if __name__ == "__main__":
    main()
