"""CLI: historical backfill of a past Slesh event.

Usage:
    python -m app.scripts.backfill_slesh_event \\
        --tenant-slug noma-group \\
        --event-id <UUID> \\
        --experience-id <slesh_experience_id> \\
        --from-ts 2025-08-03T18:00:00+00:00 \\
        --to-ts   2025-08-04T03:00:00+00:00 \\
        [--chunk-minutes 30]

Walks the [from_ts, to_ts] window in chunks (default 30 min each), reusing
the production polling worker (`poll_slesh_orders`) for each chunk. The
DB unique constraint on (tenant, source, idempotency_key) makes this
naturally idempotent — re-running the same backfill produces zero new
rows.

Why chunks:
- A single 9-hour window paginated through Slesh would be one very long
  request series — easier to watch progress chunk-by-chunk.
- If a chunk fails, only that chunk needs retry, not the whole window.
- The polling worker's circuit breaker resets between chunks (each call
  opens a fresh adapter), so a single transient Slesh hiccup doesn't
  poison the whole backfill.

Spec: docs/slesh-integration-roadmap.md §B7
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from app.core.config             import settings
from app.core.database           import AsyncSessionLocal
from app.modules.auth.models     import Tenant
from app.modules.events.models   import Event
from app.modules.pos.slesh_poller import poll_slesh_orders


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="backfill_slesh_event")
    p.add_argument("--tenant-slug",   required=True)
    p.add_argument("--event-id",      required=True)
    p.add_argument("--experience-id", required=True,
                   help="Slesh experience id of the past event to replay.")
    p.add_argument("--from-ts", required=True,
                   help="Lower bound of the backfill window (ISO 8601).")
    p.add_argument("--to-ts",   required=True,
                   help="Upper bound of the backfill window (ISO 8601).")
    p.add_argument("--chunk-minutes", type=int, default=30,
                   help="Width of each poll window in minutes (default 30).")
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


async def _resolve_tenant_id(db, slug: str) -> UUID:
    res = await db.execute(select(Tenant).where(Tenant.slug == slug))
    t = res.scalar_one_or_none()
    if t is None:
        raise SystemExit(f"❌ Tenant {slug!r} not found.")
    print(f"  tenant: {t.name} ({t.id})")
    return t.id


async def _resolve_event_id(db, tenant_id: UUID, eid_str: str) -> UUID:
    try:
        eid = UUID(eid_str)
    except ValueError:
        raise SystemExit(f"❌ --event-id not a UUID: {eid_str!r}")
    res = await db.execute(
        select(Event).where(Event.tenant_id == tenant_id).where(Event.id == eid)
    )
    e = res.scalar_one_or_none()
    if e is None:
        raise SystemExit(f"❌ Event {eid} not found.")
    print(f"  event:  {e.name} ({e.id})")
    return e.id


async def _run(args) -> int:
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    # Quiet down sqlalchemy + httpx; keep our modules visible
    for noisy in ("sqlalchemy.engine", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if not settings.slesh_api_token:
        print("❌ SLESH_API_TOKEN not configured")
        return 1

    from_ts = _parse_iso(args.from_ts, "from-ts")
    to_ts   = _parse_iso(args.to_ts,   "to-ts")
    if from_ts >= to_ts:
        raise SystemExit("❌ --from-ts must be earlier than --to-ts")

    chunk = timedelta(minutes=args.chunk_minutes)
    total_window = to_ts - from_ts
    n_chunks = int((total_window.total_seconds() + chunk.total_seconds() - 1)
                   // chunk.total_seconds())

    print()
    print("=" * 70)
    print("Slesh historical backfill")
    print("=" * 70)
    async with AsyncSessionLocal() as db:
        tenant_id = await _resolve_tenant_id(db, args.tenant_slug)
        event_id  = await _resolve_event_id(db, tenant_id, args.event_id)

    print(f"  exp:      {args.experience_id}")
    print(f"  window:   {from_ts.isoformat()} -> {to_ts.isoformat()}")
    print(f"  chunks:   {n_chunks} x {args.chunk_minutes} min")
    print()

    # Reset cursor for this scope so the first chunk starts cleanly at from_ts
    from app.modules.pos.poll_state_models import SleshPollState
    async with AsyncSessionLocal() as db:
        await db.execute(
            select(SleshPollState).where(SleshPollState.tenant_id == tenant_id)
        )
        # Delete existing cursor for this scope (safe — only this experience)
        from sqlalchemy import delete
        await db.execute(
            delete(SleshPollState)
            .where(SleshPollState.tenant_id == tenant_id)
            .where(SleshPollState.experience_id == args.experience_id)
        )
        await db.commit()

    # Aggregate counters across all chunks
    total_orders   = 0
    total_lines    = 0
    total_replays  = 0
    total_skipped  = 0
    total_errors   = 0
    failed_chunks  = 0

    chunk_idx = 0
    cursor = from_ts
    while cursor < to_ts:
        chunk_idx += 1
        chunk_until = min(cursor + chunk, to_ts)

        print(f"[{chunk_idx}/{n_chunks}] {cursor.isoformat()} -> {chunk_until.isoformat()}")
        result = await poll_slesh_orders(
            tenant_id     = tenant_id,
            event_id      = event_id,
            experience_id = args.experience_id,
            since_ts      = cursor,        # explicit chunk start
            until_ts      = chunk_until,   # explicit chunk end
        )
        if result.status != "ok":
            failed_chunks += 1
            print(f"        ❌ {result.status}: {result.error_msg[:80]}")
        else:
            total_orders  += result.orders_seen
            total_lines   += result.lines_ingested
            total_replays += result.lines_replayed
            total_skipped += result.lines_skipped
            total_errors  += result.lines_errors
            print(f"        ✅ orders={result.orders_seen} "
                  f"lines={result.lines_ingested} replayed={result.lines_replayed} "
                  f"skipped={result.lines_skipped} errors={result.lines_errors}")

        cursor = chunk_until

    print()
    print("=" * 70)
    print(f"Backfill complete: {chunk_idx} chunks ({failed_chunks} failed)")
    print(f"  Orders seen:    {total_orders}")
    print(f"  Lines ingested: {total_lines}")
    print(f"  Lines replayed: {total_replays}  (idempotency hits — fine)")
    print(f"  Lines skipped:  {total_skipped}")
    print(f"  Lines errors:   {total_errors}")
    print("=" * 70)
    return 0 if failed_chunks == 0 else 1


def main() -> None:
    p = _build_parser()
    sys.exit(asyncio.run(_run(p.parse_args())))


if __name__ == "__main__":
    main()
