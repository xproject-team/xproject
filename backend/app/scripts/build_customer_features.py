"""CLI: build customer_sessions + customer_purchases from Slesh-sourced data.

Usage:
    python -m app.scripts.build_customer_features \\
        --tenant-id 25ef916c-a288-44ae-b17c-8dfd09390834 \\
        --event 9ae0dc52-8a01-4998-b430-3814bd8cdabe:980:3795100:jul19 \\
        --event 0888f4b7-7030-426b-815c-938e6ca447a6:1206:5015300:jul5 \\
        --event 6bd035a9-3ab4-4c7f-8f68-c811aef9fa47:1256:5401700:sundance14

--event is event_id:expected_customers:known_revenue_cents:label,
repeatable, processed in the order given.

SCOPE RULE (hard): reads ONLY event_orders, stock_transactions, products,
bars. Never joins recipes, bar_stock, inventory, alerts, or warehouse —
if a metric would need one of those, it doesn't belong in this script.

BUILD RULES
-----------
1. customer_key = event_orders.raw_extras->'user'->>'_id'. Orders where
   this is NULL are skipped entirely — never invented.
2. customer_sessions is built from event_orders DIRECTLY, not from the
   line join (2026-07-29 correction). Every identified order
   produces/updates a session — order_count, total_spend_cents
   (= sum of event_orders.fiscal_gross_cents), first/last_order_at,
   session_minutes, distinct_bars, first_bar_id, is_registered,
   email_domain, user_source all come from event_orders alone, so a
   customer whose order(s) have zero matching stock_transactions rows
   still gets a complete, correctly-counted session. Only drink_count,
   food_count, and the six category counts are line-derived and are 0
   when no lines exist for that customer — see orders_with_lines /
   has_full_line_coverage, which make that gap visible instead of
   silently averaging it away.
3. Drink/food lines (for customer_purchases and the line-derived session
   fields) join to their order via stock_transactions.source_idempotency_key,
   format "slesh:{order_id}:{line_id}" — split on ':', middle segment ->
   event_orders.slesh_order_id (100% match rate on all three events when
   a matching line exists at all).
4. Only source_idempotency_key IS NOT NULL rows are read — excludes
   recipe-cascade child rows (currently 0 in production, but the filter
   stays regardless of whether the cascade ever fires).
5. ordered_at is ALWAYS event_orders.created_at_slesh. NEVER
   stock_transactions.created_at — that's the poller's ingestion
   timestamp (median lag 25-48s, tail up to 6.6h) and would corrupt any
   hourly analysis built on top of this table.
6. session_minutes = last_order_at - first_order_at. Time BETWEEN
   purchases, NOT attendance duration — documented on the column itself
   (see the ac1 migration).
7. category is derived from the products catalog via bucket_category()
   below — spritz is checked by product NAME first (it has no dedicated
   catalog category; every spritz SKU is filed under basic_cocktail),
   everything else falls through to the catalog category. Products with
   a NULL catalog category (excluding deposits and food) are reported
   as "unmapped" so the gap in the source catalog stays visible.
8. Deposit/cup-charge lines (Bicchiere, Cauzione Bottiglia, Free
   Bicchiere — see is_deposit_product()) are KEPT in customer_purchases
   and flagged is_deposit=True, but EXCLUDED from drink_count and the
   category counts. event_orders.fiscal_gross_cents is net of deposits
   (subtotal_cents = fiscal_gross_cents + deposit_cents, verified exact
   on Sundance 14), so a revenue sum that includes deposit lines
   overshoots — that's why total_spend_cents comes from event_orders
   (rule 2), never from summing customer_purchases.price_cents.

ZERO-LINE ORDERS ARE EXPECTED, NOT A BUG
-------------------------------------------
An order with a real customer_key can have zero matching
stock_transactions rows when every one of its cart lines' products
failed to match our product catalog (external_pos_id mismatch) — the
ingester skips such lines silently. Confirmed on Jul-5: 880 of 4,133
orders (21.3%), €8,923.00 in fiscal_gross_cents, entirely without line
detail. Those orders' money is still counted in customer_sessions
(rule 2); their drink/food detail simply doesn't exist. This is a
product-catalog mapping gap upstream, not something this script's join
logic can recover — see app/scripts/find_unmapped_products.py for the
actual product names behind it.

SANITY GATE (hard failure, not a warning)
------------------------------------------
Distinct customers per event must match the value the caller supplies.
Checked BEFORE any write — a mismatch aborts with diagnostics and
commits nothing, for that event only. Because customer_sessions is now
built from event_orders directly (rule 2), this holds by construction:
every order with a customer_key contributes to exactly one session, so
distinct sessions == distinct customer_key values in event_orders.

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
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import AsyncSessionLocal
from app.modules.auth.models import Tenant  # noqa: F401 - registers mapper deps
from app.modules.customer_analytics.models import CustomerPurchase, CustomerSession

# Every identified order at this event — the PRIMARY source for
# customer_sessions (see rule 2 in the module docstring).
_IDENTIFIED_ORDERS_SQL = text("""
    select
        raw_extras->'user'->>'_id'                    as customer_key,
        slesh_order_id                                 as slesh_order_id,
        created_at_slesh                               as created_at_slesh,
        customer_email                                 as customer_email,
        coalesce(raw_extras->>'user_source', 'live')   as user_source,
        bar_id                                         as bar_id,
        coalesce(fiscal_gross_cents, 0)                as fiscal_gross_cents
    from event_orders
    where event_id = :event_id
      and tenant_id = :tenant_id
      and raw_extras->'user'->>'_id' is not null
""")

# Drink/food lines, for customer_purchases + the line-derived session
# fields. Only orders with an identified customer are read, but a
# customer can appear here with FEWER lines than their true order_count
# implies (see ZERO-LINE ORDERS note above) — that's expected.
_PURCHASE_ROWS_SQL = text("""
    select
        eo.raw_extras->'user'->>'_id'   as customer_key,
        eo.slesh_order_id               as slesh_order_id,
        eo.created_at_slesh             as ordered_at,
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

# Orders with an identified customer but ZERO matching stock_transactions
# rows — every cart line's product failed to catalog-match. Money is
# still real (see fiscal_gross_cents); drink/food detail is not.
_ZERO_LINE_ORDERS_SQL = text("""
    with joined_orders as (
      select distinct eo.slesh_order_id
      from stock_transactions st
      join event_orders eo
        on eo.slesh_order_id = split_part(st.source_idempotency_key, ':', 2)
       and eo.event_id = st.event_id
      where st.event_id = :event_id and st.tenant_id = :tenant_id
        and st.source_idempotency_key like 'slesh:%'
    )
    select count(*), coalesce(sum(eo.fiscal_gross_cents), 0)
    from event_orders eo
    left join joined_orders jo on jo.slesh_order_id = eo.slesh_order_id
    where eo.event_id = :event_id and eo.tenant_id = :tenant_id
      and eo.raw_extras->'user'->>'_id' is not null
      and jo.slesh_order_id is null
""")

_EVENT_TOTALS_SQL = text("""
    select coalesce(sum(deposit_cents), 0) from event_orders
    where event_id = :event_id and tenant_id = :tenant_id
""")


# ─────────────────────────────────────────────────────────────────────
# Pure logic — no I/O, unit tested directly
# ─────────────────────────────────────────────────────────────────────
def normalize_product_name(name: str) -> str:
    """Trim + collapse whitespace + lowercase, for GROUPING duplicate
    catalog entries in reports only. The actual category/deposit
    classification always operates on this normalized form too, since
    the catalog has real duplicate entries differing only in whitespace
    (e.g. "Bottiglia Vino" vs "Bottiglia Vino ").
    """
    return " ".join((name or "").split()).lower()


_DEPOSIT_PRODUCT_NAMES = {"bicchiere", "cauzione bottiglia", "free bicchiere"}


def is_deposit_product(name: str) -> bool:
    """True for a refundable cup/bottle deposit charge — a real line the
    customer paid/held, but not consumption, and not part of
    event_orders.fiscal_gross_cents (see module docstring rule 8).
    """
    return normalize_product_name(name) in _DEPOSIT_PRODUCT_NAMES


def bucket_category(product_type: str, product_category: str | None, product_name: str) -> str:
    """Map a purchased product to one of the 7 buckets this feature
    layer reports on: beer | cocktail | spritz | wine | premium | other
    | food. Spritz is name-based (no dedicated catalog category — every
    spritz SKU, including the misspelled "Sprtiz Arancio", is filed
    under basic_cocktail) and is checked before catalog category so it
    doesn't fall into 'cocktail'. Deposit lines are handled by the
    caller (excluded from counts, not bucketed here).
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


@dataclass
class SessionBuildResult:
    session: dict
    unmapped_products: set[tuple[str, str]] = field(default_factory=set)  # (normalized_name, product_id)


def build_session_row(
    *, tenant_id: UUID, event_id: UUID, customer_key: str, orders: list[dict], lines: list[dict],
) -> SessionBuildResult:
    """Pure aggregation for one customer at one event. `orders` is this
    customer's rows from _IDENTIFIED_ORDERS_SQL (never empty — that's
    how a customer_key exists at all); `lines` is their rows from
    _PURCHASE_ROWS_SQL, already bucketed + is_deposit-flagged, and MAY
    be empty (zero-line-order case). No I/O.
    """
    order_ids = {o["slesh_order_id"] for o in orders}
    order_count = len(order_ids)

    created_ats = [o["created_at_slesh"] for o in orders]
    first_order_at = min(created_ats)
    last_order_at = max(created_ats)
    session_minutes = round((last_order_at - first_order_at).total_seconds() / 60.0, 2)

    total_spend_cents = sum(o["fiscal_gross_cents"] for o in orders)
    avg_order_cents = int(round(total_spend_cents / order_count)) if order_count else 0

    bar_ids = [o["bar_id"] for o in orders if o["bar_id"] is not None]
    distinct_bars = len(set(bar_ids))
    first_bar_id = min(orders, key=lambda o: o["created_at_slesh"])["bar_id"]

    emails = [o["customer_email"] for o in orders if o["customer_email"]]
    email_domain = emails[0].split("@", 1)[1] if emails and "@" in emails[0] else None
    is_registered = (email_domain != "slesh.it") if email_domain is not None else None

    user_source = "backfill" if any(o["user_source"] == "backfill" for o in orders) else "live"

    lines_order_ids = {ln["slesh_order_id"] for ln in lines}
    orders_with_lines = len(order_ids & lines_order_ids)
    has_full_line_coverage = (orders_with_lines == order_count)

    non_deposit_lines = [ln for ln in lines if not ln["is_deposit"]]
    drink_lines = [ln for ln in non_deposit_lines if ln["bucket"] != "food"]
    food_lines = [ln for ln in non_deposit_lines if ln["bucket"] == "food"]
    bucket_counts = Counter(ln["bucket"] for ln in drink_lines)

    unmapped = {
        (normalize_product_name(ln["product_name"]), str(ln["product_id"]))
        for ln in lines
        if ln["product_type"] != "food" and ln["product_category"] is None and not ln["is_deposit"]
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
        orders_with_lines=orders_with_lines,
        has_full_line_coverage=has_full_line_coverage,
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


# asyncpg hard-caps a single prepared statement at 32,767 bind
# parameters. CustomerSession has ~26 columns, CustomerPurchase ~13 —
# 1,000 rows/batch stays comfortably under that for either table even
# though only one is ever needed at a time.
_INSERT_BATCH_SIZE = 1000


def _chunked(rows: list[dict], size: int):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


# ─────────────────────────────────────────────────────────────────────
# I/O — fetch, orchestrate, write
# ─────────────────────────────────────────────────────────────────────
async def fetch_identified_orders(db, tenant_id: UUID, event_id: UUID) -> list[dict]:
    res = await db.execute(_IDENTIFIED_ORDERS_SQL, {"tenant_id": tenant_id, "event_id": event_id})
    return [dict(r) for r in res.mappings().all()]


async def fetch_purchase_lines(db, tenant_id: UUID, event_id: UUID) -> list[dict]:
    res = await db.execute(_PURCHASE_ROWS_SQL, {"tenant_id": tenant_id, "event_id": event_id})
    lines = []
    for r in res.mappings().all():
        d = dict(r)
        d["is_deposit"] = is_deposit_product(d["product_name"])
        d["bucket"] = bucket_category(d["product_type"], d["product_category"], d["product_name"])
        lines.append(d)
    return lines


async def fetch_zero_line_order_stats(db, tenant_id: UUID, event_id: UUID) -> tuple[int, int]:
    res = await db.execute(_ZERO_LINE_ORDERS_SQL, {"tenant_id": tenant_id, "event_id": event_id})
    count, revenue_cents = res.one()
    return int(count), int(revenue_cents)


async def fetch_total_deposit_cents(db, tenant_id: UUID, event_id: UUID) -> int:
    res = await db.execute(_EVENT_TOTALS_SQL, {"tenant_id": tenant_id, "event_id": event_id})
    # asyncpg returns sum() as Decimal; coerce now so downstream float
    # arithmetic (the coverage % properties) doesn't blow up on
    # float * Decimal.
    return int(res.scalar_one())


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
    sessions_without_full_line_coverage: int = 0
    zero_line_orders: int = 0
    zero_line_orders_revenue_cents: int = 0
    known_revenue_cents: int = 0
    known_deposit_cents: int = 0
    consumption_covered_cents: int = 0     # sum(price*qty) excl. deposits
    full_payment_covered_cents: int = 0    # sum(price*qty) incl. deposits
    unmapped_products: set = field(default_factory=set)
    median_orders: float = 0.0
    p90_orders: float = 0.0
    median_spend_cents: float = 0.0
    p90_spend_cents: float = 0.0
    median_session_minutes: float = 0.0
    p90_session_minutes: float = 0.0

    @property
    def consumption_coverage_pct(self) -> float:
        return 100.0 * self.consumption_covered_cents / self.known_revenue_cents if self.known_revenue_cents else 0.0

    @property
    def full_payment_coverage_pct(self) -> float:
        denom = self.known_revenue_cents + self.known_deposit_cents
        return 100.0 * self.full_payment_covered_cents / denom if denom else 0.0


async def build_event(
    *, tenant_id: UUID, event_id: UUID, expected_customers: int, known_revenue_cents: int,
) -> EventReport:
    report = EventReport(event_id=event_id, expected_customers=expected_customers,
                          known_revenue_cents=known_revenue_cents)

    async with AsyncSessionLocal() as db:
        orders = await fetch_identified_orders(db, tenant_id, event_id)
        lines = await fetch_purchase_lines(db, tenant_id, event_id)
        report.zero_line_orders, report.zero_line_orders_revenue_cents = \
            await fetch_zero_line_order_stats(db, tenant_id, event_id)
        report.known_deposit_cents = await fetch_total_deposit_cents(db, tenant_id, event_id)

    orders_by_customer: dict[str, list[dict]] = defaultdict(list)
    for o in orders:
        orders_by_customer[o["customer_key"]].append(o)
    lines_by_customer: dict[str, list[dict]] = defaultdict(list)
    for ln in lines:
        lines_by_customer[ln["customer_key"]].append(ln)

    session_rows = []
    purchase_rows = []
    unmapped: set[tuple[str, str]] = set()

    for customer_key, cust_orders in orders_by_customer.items():
        cust_lines = lines_by_customer.get(customer_key, [])
        result = build_session_row(
            tenant_id=tenant_id, event_id=event_id, customer_key=customer_key,
            orders=cust_orders, lines=cust_lines,
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
                is_deposit=ln["is_deposit"],
                ordered_at=ln["ordered_at"],
            ))

    report.distinct_customers = len(session_rows)
    report.sessions_created = len(session_rows)
    report.purchases_created = len(purchase_rows)
    report.unmapped_products = unmapped

    report.consumption_covered_cents = sum(
        int(round(float(ln["qty"]) * (ln["price_cents"] or 0))) for ln in lines if not ln["is_deposit"]
    )
    report.full_payment_covered_cents = sum(
        int(round(float(ln["qty"]) * (ln["price_cents"] or 0))) for ln in lines
    )

    report.registered = sum(1 for s in session_rows if s["is_registered"] is True)
    report.guest = sum(1 for s in session_rows if s["is_registered"] is False)
    report.unknown_registration = sum(1 for s in session_rows if s["is_registered"] is None)
    report.sessions_without_full_line_coverage = sum(1 for s in session_rows if not s["has_full_line_coverage"])

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
        # asyncpg caps a single prepared statement at 32,767 bind
        # parameters — a plain one-shot bulk insert blows past that once
        # an event has a few thousand rows. Batch instead.
        for batch in _chunked(session_rows, _INSERT_BATCH_SIZE):
            await db.execute(pg_insert(CustomerSession).values(batch))
        for batch in _chunked(purchase_rows, _INSERT_BATCH_SIZE):
            await db.execute(pg_insert(CustomerPurchase).values(batch))
        await db.commit()

    return report


def _print_report(label: str, r: EventReport) -> None:
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
    print(f"  sessions WITHOUT full line coverage: {r.sessions_without_full_line_coverage}")
    print(f"  zero-line orders (money counted, no drink detail): {r.zero_line_orders}  "
          f"(EUR{r.zero_line_orders_revenue_cents/100:,.2f})")
    print(f"  consumption coverage (excl. deposits) vs fiscal_gross: "
          f"EUR{r.consumption_covered_cents/100:,.2f} / EUR{r.known_revenue_cents/100:,.2f}"
          f"  ({r.consumption_coverage_pct:.1f}%)")
    print(f"  full-payment check (incl. deposits) vs fiscal_gross+deposits: "
          f"EUR{r.full_payment_covered_cents/100:,.2f} / EUR{(r.known_revenue_cents+r.known_deposit_cents)/100:,.2f}"
          f"  ({r.full_payment_coverage_pct:.1f}%)")
    print(f"  orders per customer   — median {r.median_orders:.1f}  p90 {r.p90_orders:.1f}")
    print(f"  spend per customer    — median EUR{r.median_spend_cents/100:,.2f}  p90 EUR{r.p90_spend_cents/100:,.2f}")
    print(f"  session_minutes       — median {r.median_session_minutes:.1f}  p90 {r.p90_session_minutes:.1f}")
    print(f"  unmapped products (category IS NULL in catalog, excl. food/deposits): {len(r.unmapped_products)}")
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
    zero_line_summary = []
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
        _print_report(label, report)
        zero_line_summary.append((label, report.zero_line_orders, report.zero_line_orders_revenue_cents))
        if not report.sanity_passed:
            overall_ok = False
            print()
            print(f"STOPPING after {label} — sanity gate failed, not proceeding to remaining events.")
            break

    print()
    print("=" * 70)
    print("ZERO-LINE ORDERS — all events")
    print("=" * 70)
    for label, count, revenue_cents in zero_line_summary:
        print(f"  {label:12s}  {count:5d} orders  EUR{revenue_cents/100:,.2f}")

    return 0 if overall_ok else 1


def main() -> None:
    p = _build_parser()
    sys.exit(asyncio.run(_run(p.parse_args())))


if __name__ == "__main__":
    main()
