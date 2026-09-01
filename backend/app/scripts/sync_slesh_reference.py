"""CLI: sync Slesh reference data (shops + products) into our DB.

Usage:
    python -m app.scripts.sync_slesh_reference --tenant-slug noma-group --event-id <UUID> [--experience-id <id>]

Idempotent — safe to re-run. Reports created/updated/skipped counts.

Spec: docs/slesh-integration-roadmap.md §B5
"""
from __future__ import annotations

import app.models_registry  # noqa: F401 — complete the FK graph for standalone runs

import argparse
import asyncio
import logging
import sys
from uuid import UUID

from sqlalchemy import select

from app.core.config           import settings
from app.core.database         import AsyncSessionLocal
from app.modules.auth.models   import Tenant
from app.modules.events.models import Event
from app.modules.pos.adapters.slesh import SleshAdapter
from app.modules.pos.sync_service   import sync_shops, sync_products


# ─────────────────────────────────────────────────────────────────────
# Argument parsing
# ─────────────────────────────────────────────────────────────────────
def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sync_slesh_reference",
        description="Sync Slesh shops + products into the local DB.",
    )
    p.add_argument(
        "--tenant-slug",
        required=True,
        help="Tenant slug (e.g. 'noma-group').",
    )
    p.add_argument(
        "--event-id",
        required=True,
        help="UUID of the event the bars belong to. Required because bars are event-scoped.",
    )
    p.add_argument(
        "--experience-id",
        default=None,
        help="Optional Slesh experience id to filter shops/products by.",
    )
    p.add_argument(
        "--skip-shops",
        action="store_true",
        help="Skip the shop sync step.",
    )
    p.add_argument(
        "--skip-products",
        action="store_true",
        help="Skip the product sync step.",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p


# ─────────────────────────────────────────────────────────────────────
# Resolution helpers
# ─────────────────────────────────────────────────────────────────────
async def _resolve_tenant_id(db, tenant_slug: str) -> UUID:
    res = await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
    tenant = res.scalar_one_or_none()
    if tenant is None:
        raise SystemExit(f"❌ Tenant with slug {tenant_slug!r} not found.")
    print(f"  Resolved tenant: {tenant.name} (id={tenant.id})")
    return tenant.id


async def _resolve_event_id(db, tenant_id: UUID, event_id_str: str) -> UUID:
    try:
        event_uuid = UUID(event_id_str)
    except ValueError:
        raise SystemExit(f"❌ --event-id must be a valid UUID, got {event_id_str!r}")
    res = await db.execute(
        select(Event).where(Event.tenant_id == tenant_id).where(Event.id == event_uuid)
    )
    event = res.scalar_one_or_none()
    if event is None:
        raise SystemExit(
            f"❌ Event {event_uuid} not found for tenant. "
            "Create the event first via the API or seed script."
        )
    print(f"  Resolved event: {event.name} (id={event.id})")
    return event.id


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────
async def _run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )

    if not settings.slesh_api_token:
        print("❌ SLESH_API_TOKEN is not configured. Check .env.")
        return 1
    if not settings.slesh_brand_id:
        print("❌ SLESH_BRAND_ID is not configured. Check .env.")
        return 1

    print()
    print("=" * 70)
    print(f"Slesh reference sync — brand_id={settings.slesh_brand_id}")
    print(f"experience_id={args.experience_id or '(none — global)'}")
    print("=" * 70)

    async with AsyncSessionLocal() as db:
        tenant_id = await _resolve_tenant_id(db, args.tenant_slug)
        event_id  = await _resolve_event_id(db, tenant_id, args.event_id)

        async with SleshAdapter(
            token              = settings.slesh_api_token,
            brand_id           = settings.slesh_brand_id,
            base_url           = settings.slesh_base_url,
            request_timeout    = settings.slesh_request_timeout,
            rate_limit_rps     = settings.slesh_rate_limit_rps,
            max_retries        = settings.slesh_max_retries,
        ) as adapter:

            # Sanity-check the token first — fail fast if it's wrong.
            print()
            print("[0/2] Verifying token against Slesh /brand/my…")
            brand = await adapter.verify_token()
            print(f"      ✅ Token works. Brand: {brand.name} (id={brand.id})")

            if not args.skip_shops:
                print()
                print("[1/2] Syncing shops → bars…")
                result = await sync_shops(
                    db            = db,
                    adapter       = adapter,
                    tenant_id     = tenant_id,
                    event_id      = event_id,
                    experience_id = args.experience_id,
                )
                print(f"      ✅ {result}")
            else:
                print()
                print("[1/2] Shop sync skipped (--skip-shops)")

            if not args.skip_products:
                print()
                print("[2/2] Syncing products → products table…")
                result = await sync_products(
                    db            = db,
                    adapter       = adapter,
                    tenant_id     = tenant_id,
                    experience_id = args.experience_id,
                )
                print(f"      ✅ {result}")
            else:
                print()
                print("[2/2] Product sync skipped (--skip-products)")

        # Commit the whole sync atomically
        await db.commit()

    print()
    print("=" * 70)
    print("✅ Sync complete.")
    print("=" * 70)
    return 0


def main() -> None:
    parser = _build_arg_parser()
    args   = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
