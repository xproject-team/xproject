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

WHY THE FETCH WINDOW IS DERIVED FROM event_orders, NOT event.scheduled_at
----------------------------------------------------------------------------
A 2026-07-28 run against Jul-19 using [scheduled_at - 1h, scheduled_end_at
+ 1h] fetched 3,155 orders against an expected ~3,176 — a real gap, not
truncation (0 truncation warnings). Root cause: event.scheduled_at
(12:30 UTC) was LATER than the actual first order (10:37 UTC), so the
window start cut off ~53 minutes of real orders. event.scheduled_at is
not a reliable proxy for "when orders actually happened." The default
window is instead [min(event_orders.created_at_slesh) - 3h,
max(...) + 3h] for this event, queried fresh each run — this reproduced
the full 3,176/3,176 exactly on re-test.

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
                    {"user": ..., "operator": ..., "user_source": "backfill"}
                    — same shape order_ingester writes today, plus a
                    provenance marker. If raw_extras is already populated
                    we never touch it, even to add a missing key; that's
                    out of scope for this pass.
Never touches fiscal_gross_cents, bar_id, or any other existing field.
Matching is on (tenant_id, event_id, slesh_order_id) against the
already-ingested event_orders row — this script never creates orders.

DRIFT PROTECTION (2026-07-28 finding, load-bearing)
-----------------------------------------------------
A completeness audit found raw_extras.user._id is NOT stable under
re-fetch: re-querying Slesh for an already-ingested order can return a
DIFFERENT Mongo user id than what was captured live at ingestion time
(~4-5% of matched orders on Jul-5/Jul-19). Financial fields do not do
this — only `user` drifts.

Consequence: when the existing row ALREADY has a trusted
raw_extras.user._id (true for 100% of Jul-5/Jul-19, 2 rows on
Sundance 14), this script will NOT write customer_email or
payment_token unless the freshly-fetched user._id matches the stored
one EXACTLY. A mismatch means this fetch's view of that order is
unreliable, and nothing from it — including email/token — is trusted
for that row. Mismatches are counted as `skipped_for_drift` and
reported per event; they are not an error, they're expected at ~4-5%.
When the existing row has NO stored user._id at all (Sundance 14's
4,264 pre-Phase-3 rows), there is nothing to drift-check against, so
this is a straight recovery: raw_extras, customer_email, and
payment_token are all written directly.

Spec: identity audit follow-up (customer_email / payment_token task).
"""
from __future__ import annotations

import app.models_registry  # noqa: F401 — complete the FK graph for standalone runs

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
    skipped_for_drift:         int = 0   # existing user_id present, fresh fetch disagrees
    updated:                   int = 0   # only non-zero in --execute
    truncation_warnings:       int = 0
    chunks_walked:             int = 0
    examples: list[dict] = field(default_factory=list)
    drift_examples: list[dict] = field(default_factory=list)


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
                        "orders by ~17%%. 5 minutes produced 0 truncations. Re-check "
                        "this default against observed peak order rate for any new "
                        "event before trusting a larger value.")
    p.add_argument("--from-ts", default=None,
                   help="Override window start (ISO 8601). Defaults to this event's "
                        "OWN min(created_at_slesh) minus a 3h safety buffer — see "
                        "note below on why NOT event.scheduled_at.")
    p.add_argument("--to-ts", default=None,
                   help="Override window end (ISO 8601). Defaults to this event's "
                        "OWN max(created_at_slesh) plus a 3h safety buffer.")
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


def _existing_user_id(row: EventOrder) -> str | None:
    if row.raw_extras and isinstance(row.raw_extras, dict):
        u = row.raw_extras.get("user")
        if u and u.get("_id"):
            return u["_id"]
    return None


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
    --execute run would write. NULL-only, per-column, PLUS the drift gate
    (see module docstring "DRIFT PROTECTION"). Mutates `report`'s
    counters/examples; returns the write plan. No I/O — this is the piece
    unit tests exercise directly, independent of Slesh network access or
    a live database.
    """
    # Chunk-boundary overlap can hand back the same order twice (an order
    # whose created_at lands exactly on a chunk edge). Dedupe by
    # slesh_order_id before diffing — a duplicate would otherwise double
    # up in matched/would_update/skipped_for_drift and queue the same
    # UPDATE twice (harmless but sloppy; fix it, don't rely on it being
    # a no-op).
    deduped: dict[str, _FetchedOrder] = {}
    for fo in fetched:
        deduped.setdefault(fo.slesh_order_id, fo)
    fetched = list(deduped.values())

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

        existing_uid = _existing_user_id(row)
        fresh_uid = fo.raw_extras_user.get("_id") if fo.raw_extras_user else None

        if existing_uid is not None and fresh_uid != existing_uid:
            # This fetch's view of this order is unreliable (the ONE field
            # we've proven drifts under re-fetch doesn't match what we
            # already trust) — skip email/token/raw_extras for it entirely,
            # don't cherry-pick "safe-looking" fields from an untrusted read.
            report.skipped_for_drift += 1
            if len(report.drift_examples) < 5:
                report.drift_examples.append({
                    "slesh_order_id": fo.slesh_order_id,
                    "existing_user_id": existing_uid[:6] + "...",
                    "fresh_user_id": (fresh_uid[:6] + "...") if fresh_uid else None,
                })
            continue

        values: dict = {}
        if row.customer_email is None and fo.customer_email:
            values["customer_email"] = fo.customer_email
        if row.payment_token is None and fo.payment_token:
            values["payment_token"] = fo.payment_token
        if row.raw_extras is None and (fo.raw_extras_user or fo.raw_extras_operator):
            # existing_uid was None to reach here (no stored user._id to
            # drift-check against) — this is a straight recovery, not a
            # verified-match write. Mark provenance so it's distinguishable
            # from live-captured raw_extras downstream.
            blob = {}
            if fo.raw_extras_operator is not None:
                blob["operator"] = fo.raw_extras_operator
            if fo.raw_extras_user is not None:
                blob["user"] = fo.raw_extras_user
            blob["user_source"] = "backfill"
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

    db_min_ts = min((r.created_at_slesh for r in existing.values()), default=None)
    db_max_ts = max((r.created_at_slesh for r in existing.values()), default=None)
    if db_min_ts is None:
        raise SystemExit("❌ no existing event_orders rows for this event — nothing to backfill against")

    # Window derived from THIS event's own observed order range, not
    # event.scheduled_at — see module docstring, that field proved
    # unreliable (later than real first orders) on Jul-19.
    from_ts = _parse_iso(args.from_ts, "from-ts") if args.from_ts else db_min_ts - timedelta(hours=3)
    to_ts   = _parse_iso(args.to_ts,   "to-ts")   if args.to_ts   else db_max_ts + timedelta(hours=3)
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

    # Registered vs placeholder split, over the emails this run would
    # actually write (not all fetched — only ones surviving the drift gate
    # and NULL-only rule). 'slesh.it' is the confirmed guest-placeholder
    # domain from the 2026-07-28 email forensics pass.
    written_emails = [v["customer_email"] for _, v in updates if "customer_email" in v]
    placeholder_count = sum(1 for e in written_emails if e.endswith("@slesh.it"))
    registered_count = len(written_emails) - placeholder_count

    # Distinct users: what's already durably in the DB (the trustworthy,
    # live-captured figure — see the drift-protection note above; a fresh
    # re-fetch is NOT more authoritative for this field) plus, for events
    # with no prior user._id at all, what this run's recovery would add.
    db_distinct_users = {_existing_user_id(r) for r in existing.values() if _existing_user_id(r) is not None}
    recovered_user_ids = {
        v["raw_extras"]["user"]["_id"] for _, v in updates
        if "raw_extras" in v and "user" in v["raw_extras"] and "_id" in v["raw_extras"]["user"]
    }
    post_write_distinct_users = db_distinct_users | recovered_user_ids

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
    print(f"  rows SKIPPED for user_id drift:          {report.skipped_for_drift}")
    print()
    print(f"  distinct users already in DB (trusted, live-captured): {len(db_distinct_users)}")
    print(f"  distinct users this run would newly recover:            {len(recovered_user_ids)}")
    print(f"  distinct users after this run (union):                  {len(post_write_distinct_users)}")
    print()
    print(f"  registered (real-domain) emails this run would write: {registered_count}")
    print(f"  placeholder (@slesh.it) emails this run would write:  {placeholder_count}")
    print()
    print("  5 example rows (masked):")
    for ex in report.examples:
        print(f"    {ex}")
    if report.drift_examples:
        print()
        print("  5 example DRIFT SKIPS (existing vs fresh user_id disagree):")
        for ex in report.drift_examples:
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
    print(f"EXECUTED — {report.updated} rows updated, {report.skipped_for_drift} skipped for drift.")
    return 0


def main() -> None:
    p = _build_parser()
    sys.exit(asyncio.run(_run(p.parse_args())))


if __name__ == "__main__":
    main()
