"""CLI: manually trigger one Slesh polling cycle.

Usage:
    python -m app.scripts.poll_slesh_orders \\
        --tenant-slug noma-group \\
        --event-id <UUID> \\
        [--experience-id <slesh_experience_id>] \\
        [--until-ts <ISO>] \\
        [--log-level INFO]

This is the manual entry point per B6.6 — auto-cron scheduling lands later.
Useful for:
  - Verifying the polling stack end-to-end against real Slesh
  - Backfilling a specific window during ops
  - Debugging cursor / ingestion behavior

Spec: docs/slesh-integration-roadmap.md §B6.6
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.core.config             import settings
from app.core.database           import AsyncSessionLocal
from app.modules.auth.models     import Tenant
from app.modules.events.models   import Event
from app.modules.pos.slesh_poller import poll_slesh_orders


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="poll_slesh_orders",
        description="Manually trigger one Slesh polling cycle.",
    )
    p.add_argument("--tenant-slug", required=True)
    p.add_argument("--event-id",    required=True,
                   help="UUID of the XProject event the orders attach to.")
    p.add_argument("--experience-id", default=None,
                   help="Optional Slesh experience filter.")
    p.add_argument("--until-ts", default=None,
                   help="Upper bound (ISO 8601). Defaults to now (UTC).")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


async def _resolve_tenant_id(db, slug: str) -> UUID:
    res = await db.execute(select(Tenant).where(Tenant.slug == slug))
    tenant = res.scalar_one_or_none()
    if tenant is None:
        raise SystemExit(f"❌ Tenant {slug!r} not found.")
    print(f"  tenant: {tenant.name} (id={tenant.id})")
    return tenant.id


async def _resolve_event_id(db, tenant_id: UUID, event_id_str: str) -> UUID:
    try:
        eid = UUID(event_id_str)
    except ValueError:
        raise SystemExit(f"❌ --event-id must be a valid UUID, got {event_id_str!r}")
    res = await db.execute(
        select(Event).where(Event.tenant_id == tenant_id).where(Event.id == eid)
    )
    event = res.scalar_one_or_none()
    if event is None:
        raise SystemExit(f"❌ Event {eid} not found for tenant.")
    print(f"  event:  {event.name} (id={event.id})")
    return event.id


def _parse_until_ts(arg: str | None) -> datetime | None:
    if arg is None:
        return None
    try:
        dt = datetime.fromisoformat(arg.replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit(f"❌ --until-ts must be ISO 8601, got {arg!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def _run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )

    if not settings.slesh_api_token:
        print("❌ SLESH_API_TOKEN not configured. Check .env.")
        return 1

    print()
    print("=" * 70)
    print("Slesh order poll — manual trigger")
    print("=" * 70)

    until_ts = _parse_until_ts(args.until_ts)

    async with AsyncSessionLocal() as db:
        tenant_id = await _resolve_tenant_id(db, args.tenant_slug)
        event_id  = await _resolve_event_id(db, tenant_id, args.event_id)

    print(f"  brand:  {settings.slesh_brand_id}")
    print(f"  exp:    {args.experience_id or '(brand-wide)'}")
    print(f"  until:  {until_ts.isoformat() if until_ts else '(now)'}")
    print()

    print("[…] polling …")
    result = await poll_slesh_orders(
        tenant_id     = tenant_id,
        event_id      = event_id,
        experience_id = args.experience_id,
        until_ts      = until_ts,
    )

    print()
    if result.status != "ok":
        print(f"❌ poll failed: {result.status}")
        print(f"   {result.error_msg}")
        return 1

    print(f"✅ {result}")
    if result.window:
        print(f"   window: {result.window.since_ts.isoformat()}")
        print(f"      to:  {result.window.until_ts.isoformat()}")
        print(f"   width:  {result.window.width_seconds:.0f}s")
    if result.new_high_water_ts:
        hw = datetime.fromtimestamp(result.new_high_water_ts / 1000, tz=timezone.utc)
        print(f"   new high-water mark: {hw.isoformat()} ({result.new_high_water_ts})")
    print()
    print("=" * 70)
    return 0


def main() -> None:
    parser = _build_arg_parser()
    args   = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
