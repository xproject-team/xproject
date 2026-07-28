"""CLI: backfill customer_email / payment_token (+ recover raw_extras.user)
for a past event by re-pulling its orders from the Slesh API.

Usage:
    python -m app.scripts.backfill_customer_identity \\
        --tenant-id 25ef916c-a288-44ae-b17c-8dfd09390834 \\
        --event-id 9ae0dc52-8a01-4998-b430-3814bd8cdabe \\
        --dry-run

    # after reviewing the dry-run report:
    python -m app.scripts.backfill_customer_identity \\
        --tenant-id 25ef916c-a288-44ae-b17c-8dfd09390834 \\
        --event-id 9ae0dc52-8a01-4998-b430-3814bd8cdabe \\
        --execute

--tenant-slug also accepted as an alternative to --tenant-id.

KNOWN FINDING — payment_token is NOT a per-wristband credential
------------------------------------------------------------------
A 2026-07-28 dry-run against the Jul-19 event found payment._paymentToken
holds exactly ONE distinct value across all 3,155 orders that carried it.
It is some kind of static payment-gateway/session token, not the physical
band. Whatever question this column was meant to help answer ("does one
band = one person or a shared wallet") cannot be answered from it. It is
still backfilled here because it's harmless and matches the deployed
schema, but do not build anything downstream that assumes it varies
per-band. raw_extras.user._id remains the only per-customer handle.

WHY THIS SCRIPT SHARES CODE WITH THE LIVE POLLER
-------------------------------------------------
Every field this script extracts from a raw Slesh order goes through
`app.modules.pos.order_ingester.extract_identity_fields` — the SAME
function `ingest_order()` calls on the live path. There is no second,
parallel copy of the mapping here. If that function is wrong, both the
live poller and this backfill are wrong together, and testing one tests
both. A backfill with its own copy of the mapping logic would prove
nothing about whether Sunday's live ingestion actually works.

WHY CHUNKED WINDOWS, NOT ONE BIG PULL
--------------------------------------
Slesh's `/order/brand-my` endpoint pages at 100 documents, and its `from`
offset is unreliable past the first page for a given call — see the
detailed note in `adapters/slesh.py::_iter_paginated` ("chunk truncated").
A single query spanning an entire event risks silently returning only
the first ~100 orders. We walk the event's active window in fixed-size
time chunks (default 5 min) instead, so no single call is likely to
exceed the page cap. `_iter_paginated` still logs a WARNING if any one
chunk truncates anyway; this script counts those warnings and surfaces
the count front and center in the report — a chunk-truncation count of
0 is required before trusting the numbers below it, not just "materially
fewer than expected."

WRITE SEMANTICS (--execute only; irrelevant in --dry-run)
-----------------------------------------------------------
UPDATE-only, and only on columns that are CURRENTLY NULL:
  - customer_email: set iff existing value IS NULL and Slesh has one.
  - payment_token:  set iff existing value IS NULL and Slesh has one.
  - raw_extras:     set iff existing value IS NULL (whole column), to
                    {"user": ..., "operator": ...} — same shape
                    order_ingester writes today. If raw_extras is
                    already populated we never touch it, even to add a
                    missing key; that's out of scope for this pass.
Never touches fiscal_gross_cents, bar_id, or any other existing field.
Matching is on (tenant_id, event_id, slesh_order_id) against the
already-ingested event_orders row — this script never creates orders.

Spec: identity audit follow-up (customer_email / payment_token task).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.modules.auth.models import Tenant
from app.modules.events.models import Event, EventOrder
from app.modules.pos.adapters.slesh import SleshAdapter
from app.modules.pos.order_ingester import extract_identity_fields

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Truncation watchdog — reuses _iter_paginated's own detection, doesn't
# reimplement it. See adapters/slesh.py for where this warning fires.
# ─────────────────────────────────────────────────────────────────────
class _TruncationWatchdog(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if "chunk truncated" in msg or "pagination loop detected" in msg:
            self.messages.append(msg)


def _mask(value: str | None) -> str:
    if value is None:
        return "None"
    return value[:4] + "***"


@dataclass
class _FetchedOrder:
    slesh_order_id: str
    customer_email: str | None
    payment_token:  str | None
    raw_extras_user:     dict | None
    raw_extras_operator: dict | None


@dataclass
class BackfillReport:
    orders_fetched:            int = 0
    with_customer_email:       int = 0
    with_payment_token:        int = 0
    matched_existing_order:    int = 0
    would_update:              int = 0   # matched AND >=1 target column newly fillable
    updated:                   int = 0   # only non-zero in --execute
    truncation_warnings:       int = 0
    chunks_walked:             int = 0
    examples: list[dict] = field(default_factory=list)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="backfill_customer_identity")
    tenant = p.add_mutually_exclusive_group(required=True)
    tenant.add_argument("--tenant-slug")
    tenant.add_argument("--tenant-id")
    p.add_argument("--event-id",    required=True)
    p.add_argument("--chunk-minutes", type=int, default=5,
                   help="Width of each Slesh query window in minutes (default 5). "
                        "A 2026-07-28 dry-run against Jul-19 with 15-minute chunks "
                        "silently truncated 15 of ~144 windows during peak hours "
                        "(observed up to 159 orders in a single 15-min window, "
                        "against the 100-doc page cap) and undercounted total "
                        "orders by ~17%. 5 minutes produced 0 truncations. Re-check "
                        "this default against observed peak order rate for any new "
                        "event before trusting a larger value.")
    p.add_argument("--from-ts", default=None,
                   help="Override window start (ISO 8601). Defaults to the event's "
                        "scheduled_at minus a 1h safety buffer.")
    p.add_argument("--to-ts", default=None,
                   help="Override window end (ISO 8601). Defaults to the event's "
                        "scheduled_end_at plus a 1h safety buffer.")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                       help="Report only. No writes to Postgres.")
    mode.add_argument("--execute", action="store_true",
                       help="Perform the UPDATE-only, NULL-only writes described "
                            "in the module docstring.")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


def _parse_iso(s: str, label: str) -> datetime:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit(f"❌ --{label} must be ISO 8601, got {s!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def _resolve_tenant_id(db, *, slug: str | None, tenant_id: str | None) -> UUID:
    if tenant_id:
        try:
            tid = UUID(tenant_id)
        except ValueError:
            raise SystemExit(f"❌ --tenant-id not a UUID: {tenant_id!r}")
        res = await db.execute(select(Tenant).where(Tenant.id == tid))
    else:
        res = await db.execute(select(Tenant).where(Tenant.slug == slug))
    t = res.scalar_one_or_none()
    if t is None:
        raise SystemExit(f"❌ Tenant {tenant_id or slug!r} not found.")
    print(f"  tenant: {t.name} ({t.id})")
    return t.id


async def _resolve_event(db, tenant_id: UUID, eid_str: str) -> Event:
    try:
        eid = UUID(eid_str)
    except ValueError:
        raise SystemExit(f"❌ --event-id not a UUID: {eid_str!r}")
    res = await db.execute(
        select(Event).where(Event.tenant_id == tenant_id).where(Event.id == eid)
    )
    e = res.scalar_one_or_none()
    if e is None:
        raise SystemExit(f"❌ Event {eid} not found for tenant.")
    print(f"  event:  {e.name} ({e.id})  scheduled [{e.scheduled_at} -> {e.scheduled_end_at}]")
    return e


async def _fetch_existing_orders(db, tenant_id: UUID, event_id: UUID) -> dict[str, EventOrder]:
    """Read-only snapshot of what's already in event_orders for this event,
    keyed by slesh_order_id — used to decide match + NULL-only eligibility.
    """
    res = await db.execute(
        select(EventOrder)
        .where(EventOrder.tenant_id == tenant_id)
        .where(EventOrder.event_id == event_id)
    )
    rows = res.scalars().all()
    return {r.slesh_order_id: r for r in rows}


async def _fetch_from_slesh(
    *, brand_id: str, token: str, from_ts: datetime, to_ts: datetime,
    chunk: timedelta, report: BackfillReport,
) -> list[_FetchedOrder]:
    fetched: list[_FetchedOrder] = []

    watchdog = _TruncationWatchdog()
    adapter_logger = logging.getLogger("app.modules.pos.adapters.slesh")
    adapter_logger.addHandler(watchdog)
    try:
        async with SleshAdapter(token=token, brand_id=brand_id) as adapter:
            cursor = from_ts
            while cursor < to_ts:
                chunk_until = min(cursor + chunk, to_ts)
                report.chunks_walked += 1
                print(f"  [{report.chunks_walked}] {cursor.isoformat()} -> {chunk_until.isoformat()}", end="")

                n_before = len(fetched)
                async for order in adapter.list_orders(
                    since_ts=cursor, until_ts=chunk_until, experience_id=None,
                ):
                    identity = extract_identity_fields(order)
                    fetched.append(_FetchedOrder(
                        slesh_order_id=order.id,
                        customer_email=identity.customer_email,
                        payment_token=identity.payment_token,
                        raw_extras_user=identity.raw_extras_user,
                        raw_extras_operator=identity.raw_extras_operator,
                    ))
                print(f"  ({len(fetched) - n_before} orders)")
                cursor = chunk_until
    finally:
        adapter_logger.removeHandler(watchdog)

    report.truncation_warnings = len(watchdog.messages)
    for msg in watchdog.messages:
        logger.warning("TRUNCATION SIGNAL: %s", msg)

    return fetched


def _compute_updates(
    fetched: list[_FetchedOrder],
    existing: dict[str, EventOrder],
    report: BackfillReport,
) -> list[tuple[EventOrder, dict]]:
    """Pure diff: for each fetched order, decide what (if anything) an
    --execute run would write. NULL-only, per-column — see module
    docstring. Mutates `report`'s counters/examples; returns the write
    plan. No I/O — this is the piece unit tests exercise directly,
    independent of Slesh network access or a live database.
    """
    updates: list[tuple[EventOrder, dict]] = []
    for fo in fetched:
        if fo.customer_email:
            report.with_customer_email += 1
        if fo.payment_token:
            report.with_payment_token += 1

        row = existing.get(fo.slesh_order_id)
        if row is None:
            continue
        report.matched_existing_order += 1

        values: dict = {}
        if row.customer_email is None and fo.customer_email:
            values["customer_email"] = fo.customer_email
        if row.payment_token is None and fo.payment_token:
            values["payment_token"] = fo.payment_token
        if row.raw_extras is None and (fo.raw_extras_user or fo.raw_extras_operator):
            blob = {}
            if fo.raw_extras_operator is not None:
                blob["operator"] = fo.raw_extras_operator
            if fo.raw_extras_user is not None:
                blob["user"] = fo.raw_extras_user
            values["raw_extras"] = blob

        if values:
            report.would_update += 1
            updates.append((row, values))
            if len(report.examples) < 5:
                report.examples.append({
                    "slesh_order_id": fo.slesh_order_id,
                    "customer_email": _mask(fo.customer_email),
                    "payment_token":  _mask(fo.payment_token),
                    "columns_to_write": sorted(values.keys()),
                })
    return updates


async def _run(args) -> int:
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    for noisy in ("sqlalchemy.engine", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if not settings.slesh_api_token or not settings.slesh_brand_id:
        print("❌ SLESH_API_TOKEN / SLESH_BRAND_ID not configured")
        return 1

    print()
    print("=" * 70)
    print("Customer identity backfill" + ("  [DRY RUN]" if args.dry_run else "  [EXECUTE]"))
    print("=" * 70)

    async with AsyncSessionLocal() as db:
        tenant_id = await _resolve_tenant_id(db, slug=args.tenant_slug, tenant_id=args.tenant_id)
        event = await _resolve_event(db, tenant_id, args.event_id)
        existing = await _fetch_existing_orders(db, tenant_id, event.id)
    print(f"  existing event_orders rows for this event: {len(existing)}")

    from_ts = _parse_iso(args.from_ts, "from-ts") if args.from_ts else event.scheduled_at - timedelta(hours=1)
    to_ts   = _parse_iso(args.to_ts,   "to-ts")   if args.to_ts   else event.scheduled_end_at + timedelta(hours=1)
    if from_ts >= to_ts:
        raise SystemExit("❌ window start must be before window end")

    chunk = timedelta(minutes=args.chunk_minutes)
    print(f"  window: {from_ts.isoformat()} -> {to_ts.isoformat()}  (chunk={args.chunk_minutes}min)")
    print()

    report = BackfillReport()
    fetched = await _fetch_from_slesh(
        brand_id=settings.slesh_brand_id, token=settings.slesh_api_token,
        from_ts=from_ts, to_ts=to_ts, chunk=chunk, report=report,
    )
    report.orders_fetched = len(fetched)
    updates = _compute_updates(fetched, existing, report)

    print()
    print("=" * 70)
    print("REPORT")
    print("=" * 70)
    print(f"  orders fetched from Slesh:              {report.orders_fetched}")
    print(f"  chunk-truncation warnings:               {report.truncation_warnings}"
          + ("  <-- INVESTIGATE, numbers below are unreliable" if report.truncation_warnings else "  (clean)"))
    print(f"  carrying _customerEmail:                {report.with_customer_email}")
    print(f"  carrying payment._paymentToken:         {report.with_payment_token}")
    print(f"  matched an existing event_orders row:   {report.matched_existing_order}")
    print(f"  rows that WOULD be updated:              {report.would_update}")
    print()
    print("  5 example rows (masked):")
    for ex in report.examples:
        print(f"    {ex}")
    print("=" * 70)

    if args.dry_run:
        print("DRY RUN — no writes performed.")
        return 0

    # ── --execute path ──────────────────────────────────────────────
    async with AsyncSessionLocal() as db:
        for row, values in updates:
            await db.execute(
                update(EventOrder)
                .where(EventOrder.id == row.id)
                .values(**values)
            )
            report.updated += 1
        await db.commit()
    print(f"EXECUTED — {report.updated} rows updated.")
    return 0


def main() -> None:
    p = _build_parser()
    sys.exit(asyncio.run(_run(p.parse_args())))


if __name__ == "__main__":
    main()
