#!/usr/bin/env python3
"""clone_event.py — idempotent event clone (Jul-19 -> Aug-2, and reusable
for future clones), built for the Aug-2 rehearsal task.

Two modes:

  --fetch-source   Read-only. ALWAYS run this against production (via
                    railway ssh) — it dumps the source event's row,
                    venue, bars, and event_category_ingredients
                    ("recipes") to a local JSON file. Never writes.

  (default)         Reads that JSON dump and creates/updates the TARGET
                    event via the SAME service layer the wizard uses:
                    EventService.create_full / update_full (POST/PUT
                    /events/full) and EventRecipeService.bulk_create
                    (POST /event-recipes/bulk). Runs against whatever
                    DATABASE_URL is active — the local dev DB when run
                    via `venv/bin/python`, production when run via
                    `railway ssh`. This is what makes "local first, then
                    production on explicit go" possible with one script.

IDEMPOTENCY: matched on (tenant_id, name, scheduled_at) — the natural
key for "is the target event already there". If found and DRAFT,
restructures it via update_full (same semantics the wizard's edit mode
uses: bars are deleted and recreated, which CASCADEs any existing
event_category_ingredients rows tied to those bars, so recipes never
duplicate on a re-run — see the module's bar_id ondelete=CASCADE FK).
If found and NOT DRAFT, aborts loudly rather than touching a live/
completed event. Recipes are only bulk-created when the event currently
has zero recipe rows (bulk_create's own duplicate-key check would
otherwise reject a second identical run outright).

RE-RESOLUTION, NOT BLIND ID COPYING: venue is resolved by exact name
match in the TARGET tenant (not by source venue_id — local/prod venue
ids differ). supplier_product_id is resolved by (tenant_id,
supplier_sku) — Partesa's stable SKU, not the raw UUID, which can also
differ across environments. drink_name -> product_id resolution happens
inside EventRecipeService.bulk_create itself, against whatever catalog
the TARGET database currently has — this is the "re-resolve every
product_id against the current catalog" requirement, enforced by the
existing service code, not bolted on here.

COPIES: event scalar fields, bars (name/type/slesh_negozio_id/
device_count/slesh_category/is_active), event_category_ingredients
("recipes"). Always created as DRAFT.
NEVER COPIES: bar_stock, event_orders, stock_transactions, alerts,
chat channels, bar_devices, pending_shop_mappings — none of these are
read from the source or written to the target anywhere in this script.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text

DEFAULT_SOURCE_EVENT_ID = "9ae0dc52-8a01-4998-b430-3814bd8cdabe"  # sundance 19Jul
DEFAULT_DUMP_PATH = Path(__file__).parent / "event_clone_data" / "jul19_source.json"


# ─── Mode 1: fetch-source (read-only) ──────────────────────────────────

async def fetch_source(source_event_id: str, out_path: Path) -> None:
    from app.core.database import engine

    async with engine.connect() as conn:
        event = dict((await conn.execute(text(
            "select * from events where id = :eid"
        ), {"eid": source_event_id})).mappings().one())

        venue = dict((await conn.execute(text(
            "select * from venues where id = :vid"
        ), {"vid": event["venue_id"]})).mappings().one())

        bars = [dict(r) for r in (await conn.execute(text("""
            select id, name, bar_type, is_active, slesh_negozio_id, slesh_category, device_count
            from bars where event_id = :eid order by name
        """), {"eid": source_event_id})).mappings().all()]

        # drink_name is resolved from the source row's OWN product_id (the
        # authoritative catalog link), not the raw slesh_category label --
        # those two are known to drift (e.g. "SPRITZ ARANCIO" vs the
        # catalog's "Sprtiz Arancio", the exact free-text/catalog mismatch
        # that caused the Jul-5 depletion outage in the first place, see
        # migration aa5). Cloning off the resolved name avoids reproducing
        # that failure mode; raw_slesh_category is kept for reference only.
        recipes = [dict(r) for r in (await conn.execute(text("""
            select p.name as drink_name, eci.slesh_category as raw_slesh_category,
                   b.name as bar_name,
                   sp.supplier_sku, sp.item_name as supplier_product_name,
                   eci.ml_per_sale, eci.is_optional
            from event_category_ingredients eci
            join bars b on b.id = eci.bar_id
            join supplier_products sp on sp.id = eci.supplier_product_id
            join products p on p.id = eci.product_id
            where eci.event_id = :eid
            order by eci.created_at
        """), {"eid": source_event_id})).mappings().all()]

        menu = [dict(r) for r in (await conn.execute(text("""
            select b.name as bar_name, p.name as product_name,
                   p.product_type, p.category, p.tier_rank as product_tier_rank,
                   p.unit, p.default_price_cents, p.iva_pct, p.cauzione_cents, p.food_type,
                   ep.price_cents, ep.tier_rank_override, ep.is_available
            from event_products ep
            join bars b on b.id = ep.bar_id
            join products p on p.id = ep.product_id
            where ep.event_id = :eid
            order by b.name, p.name
        """), {"eid": source_event_id})).mappings().all()]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "source_event_id": source_event_id, "event": event, "venue": venue,
        "bars": bars, "recipes": recipes, "menu": menu,
    }, default=str))
    print(f"wrote {out_path} — {len(bars)} bars, {len(recipes)} recipe rows, {len(menu)} menu rows")


# ─── Mode 2: create/update the clone (default) ─────────────────────────

async def clone_from_dump(
    dump_path: Path, *, target_name: str, target_scheduled_at: datetime,
    target_scheduled_end_at: datetime,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.modules.auth.models import Tenant, User  # noqa: F401 — register mappers
    from app.modules.bars.models import Bar
    from app.modules.event_recipes.schemas import EventRecipeBulkCreate, EventRecipeCreate
    from app.modules.event_recipes.service import EventRecipeService
    from app.modules.events.models import Event, EventStatus
    from app.modules.events.schemas import (
        EventCreate, FullEventBar, FullEventCreate, FullEventMenuItem, FullEventProductInput,
    )
    from app.modules.events.service import EventService
    from app.modules.venues.models import Venue

    src = json.loads(dump_path.read_text())
    src_event = src["event"]
    src_venue = src["venue"]
    src_bars = src["bars"]
    src_recipes = src["recipes"]
    src_menu = src.get("menu", [])

    async with AsyncSessionLocal() as db:
        tenant_id = UUID(src_event["tenant_id"])

        # ── resolve venue by NAME in the target DB, not by source id ──
        venue_rows = (await db.execute(
            select(Venue.id, Venue.name).where(
                Venue.tenant_id == tenant_id, Venue.name == src_venue["name"],
            )
        )).all()
        if len(venue_rows) != 1:
            print(f"FATAL: expected exactly 1 venue named {src_venue['name']!r} in target "
                  f"tenant, found {len(venue_rows)}. Not proceeding.", file=sys.stderr)
            sys.exit(1)
        venue_id = venue_rows[0].id

        event_service = EventService(db)

        event_payload = EventCreate(
            name=target_name,
            venue_id=venue_id,
            scheduled_at=target_scheduled_at,
            scheduled_end_at=target_scheduled_end_at,
            expected_guest_count=src_event["expected_guest_count"],
            stripe_ragione_sociale=src_event["stripe_ragione_sociale"],
            staff_arrival_time=(
                time.fromisoformat(src_event["staff_arrival_time"])
                if src_event["staff_arrival_time"] else None
            ),
            wristband_qty_per_type=src_event["wristband_qty_per_type"] and json.loads(
                src_event["wristband_qty_per_type"]
            ) if isinstance(src_event["wristband_qty_per_type"], str) else src_event["wristband_qty_per_type"],
            topup_denominations_user=json.loads(src_event["topup_denominations_user"])
                if isinstance(src_event["topup_denominations_user"], str) else src_event["topup_denominations_user"],
            topup_denominations_staff=json.loads(src_event["topup_denominations_staff"])
                if isinstance(src_event["topup_denominations_staff"], str) else src_event["topup_denominations_staff"],
            refund_min_credit_cents=src_event["refund_min_credit_cents"],
            refund_fee_cents=src_event["refund_fee_cents"],
            refund_window_open_at=src_event["refund_window_open_at"],
            refund_window_close_at=src_event["refund_window_close_at"],
            food_revenue_share_pct=src_event["food_revenue_share_pct"],
        )
        bars_payload = [
            FullEventBar(
                name=b["name"], slesh_negozio_id=b["slesh_negozio_id"],
                bar_type=b["bar_type"], device_count=b["device_count"],
                slesh_category=b["slesh_category"], is_active=b["is_active"],
            )
            for b in src_bars
        ]
        bar_index_by_name = {b["name"]: i for i, b in enumerate(src_bars)}

        # ── menu (event_products): products are tenant-global and
        # reused-by-name (create_full's own dedup, see FullEventProductInput's
        # docstring) -- build one deduped products[] list, then index-reference
        # it + bars_payload from menu[]. Prices/availability/tier overrides
        # copied verbatim from the source menu row.
        products_payload: list = []
        product_index_by_name: dict[str, int] = {}
        menu_payload: list = []
        for m in src_menu:
            pname = m["product_name"]
            if pname not in product_index_by_name:
                product_index_by_name[pname] = len(products_payload)
                products_payload.append(FullEventProductInput(
                    name=pname, product_type=m["product_type"], category=m["category"],
                    tier_rank=m["product_tier_rank"], unit=m["unit"],
                    default_price_cents=m["default_price_cents"], iva_pct=m["iva_pct"],
                    cauzione_cents=m["cauzione_cents"], food_type=m["food_type"],
                ))
            menu_payload.append(FullEventMenuItem(
                bar_index=bar_index_by_name[m["bar_name"]],
                product_index=product_index_by_name[pname],
                price_cents=m["price_cents"], tier_rank_override=m["tier_rank_override"],
                is_available=m["is_available"],
            ))

        full_payload = FullEventCreate(
            event=event_payload, bars=bars_payload, products=products_payload, menu=menu_payload,
        )

        # ── idempotency: match on (tenant_id, name, scheduled_at) ─────
        existing = (await db.execute(
            select(Event).where(
                Event.tenant_id == tenant_id, Event.name == target_name,
                Event.scheduled_at == target_scheduled_at,
            )
        )).scalar_one_or_none()

        if existing is None:
            print(f"no existing event matching name={target_name!r} scheduled_at={target_scheduled_at} "
                  f"-- creating")
            result = await event_service.create_full(tenant_id, full_payload)
            target_event = result["event"]
        else:
            if existing.status != EventStatus.DRAFT:
                print(f"FATAL: existing event {existing.id} matches the natural key but is "
                      f"{existing.status}, not DRAFT. Refusing to restructure a non-draft event.",
                      file=sys.stderr)
                sys.exit(1)
            print(f"existing DRAFT event {existing.id} found -- restructuring via update_full "
                  f"(idempotent re-run)")
            result = await event_service.update_full(tenant_id, existing.id, full_payload)
            target_event = result["event"]

        target_event_id = target_event.id

        # ── re-resolve bars by name in the target (post create/update) ─
        bar_rows = (await db.execute(
            select(Bar.id, Bar.name).where(Bar.event_id == target_event_id)
        )).all()
        bar_id_by_name = {r.name: r.id for r in bar_rows}

        # ── recipes: only if the (now-current) event has none yet ─────
        existing_recipe_count = (await db.execute(text(
            "select count(*) from event_category_ingredients where event_id = :eid"
        ), {"eid": target_event_id})).scalar()

        if existing_recipe_count > 0:
            print(f"target event already has {existing_recipe_count} recipe rows -- skipping "
                  f"bulk_create (idempotent re-run; bulk_create's own duplicate check would "
                  f"reject an identical second insert anyway)")
        else:
            sku_rows = (await db.execute(text(
                "select supplier_sku, id from supplier_products where tenant_id = :t"
            ), {"t": tenant_id})).all()
            supplier_id_by_sku = {r.supplier_sku: r.id for r in sku_rows}

            missing_bars, missing_skus = [], []
            recipe_rows = []
            for r in src_recipes:
                bar_id = bar_id_by_name.get(r["bar_name"])
                if bar_id is None:
                    missing_bars.append(r["bar_name"])
                    continue
                sp_id = supplier_id_by_sku.get(r["supplier_sku"])
                if sp_id is None:
                    missing_skus.append((r["supplier_sku"], r["supplier_product_name"]))
                    continue
                recipe_rows.append(EventRecipeCreate(
                    event_id=target_event_id, drink_name=r["drink_name"], bar_id=bar_id,
                    supplier_product_id=sp_id, ml_per_sale=r["ml_per_sale"],
                    is_optional=r["is_optional"],
                ))

            if missing_bars or missing_skus:
                print(f"FATAL: cannot clone recipes -- missing bars: {set(missing_bars)}, "
                      f"missing supplier SKUs: {missing_skus}", file=sys.stderr)
                sys.exit(1)

            recipe_service = EventRecipeService(db)
            try:
                created = await recipe_service.bulk_create(
                    tenant_id, EventRecipeBulkCreate(event_id=target_event_id, rows=recipe_rows),
                )
                print(f"created {len(created)} recipe rows")
            except Exception as exc:  # noqa: BLE001
                items = getattr(exc, "items", None)
                if items:
                    print(f"FATAL: {len(items)} recipe row(s) failed validation:", file=sys.stderr)
                    for it in items:
                        print(f"  [{it.index}] {it.error}", file=sys.stderr)
                    sys.exit(1)
                raise

        # ── summary report ─────────────────────────────────────────────
        await _print_summary(db, target_event_id)


async def _print_summary(db, event_id: UUID) -> None:
    from app.modules.bars.models import Bar
    from app.modules.events.models import Event

    event = (await db.execute(select(Event).where(Event.id == event_id))).scalar_one()
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"event: id={event.id} name={event.name!r} status={event.status} "
          f"scheduled_at={event.scheduled_at} scheduled_end_at={event.scheduled_end_at} "
          f"venue_id={event.venue_id} food_revenue_share_pct={event.food_revenue_share_pct} "
          f"topup_user={event.topup_denominations_user} topup_staff={event.topup_denominations_staff}")

    bars = (await db.execute(
        select(Bar).where(Bar.event_id == event_id).order_by(Bar.name)
    )).scalars().all()
    print(f"\nbars ({len(bars)}):")
    for b in bars:
        print(f"  {b.name:24s} type={b.bar_type:8s} slesh_negozio_id={b.slesh_negozio_id} "
              f"active={b.is_active} device_count={b.device_count}")

    rows = (await db.execute(text("""
        select b.name as bar_name, count(*) as n
        from event_category_ingredients eci join bars b on b.id = eci.bar_id
        where eci.event_id = :eid group by b.name order by n desc
    """), {"eid": event_id})).all()
    total = sum(r.n for r in rows)
    print(f"\nrecipes: {total} rows")
    for r in rows:
        print(f"  {r.bar_name:24s} {r.n}")

    orphans = (await db.execute(text("""
        select count(*) from event_category_ingredients eci
        left join products p on p.id = eci.product_id
        where eci.event_id = :eid and (eci.product_id is null or p.id is null)
    """), {"eid": event_id})).scalar()
    print(f"\nrecipe product_id resolution: {orphans} unresolved/null (expect 0)")

    menu_rows = (await db.execute(text("""
        select b.name as bar_name, count(*) as n
        from event_products ep join bars b on b.id = ep.bar_id
        where ep.event_id = :eid group by b.name order by n desc
    """), {"eid": event_id})).all()
    menu_total = sum(r.n for r in menu_rows)
    print(f"\nmenu (event_products): {menu_total} rows")
    for r in menu_rows:
        print(f"  {r.bar_name:24s} {r.n}")

    print("\nverifying nothing else was copied:")
    for label, sql in [
        ("bar_stock", "select count(*) from bar_stock where event_id = :eid"),
        ("event_orders", "select count(*) from event_orders where event_id = :eid"),
        ("stock_transactions", "select count(*) from stock_transactions where event_id = :eid"),
        ("alerts", "select count(*) from alerts where event_id = :eid"),
        ("bar_devices", "select count(*) from bar_devices where event_id = :eid"),
        ("pending_shop_mappings", "select count(*) from pending_shop_mappings where event_id = :eid"),
    ]:
        n = (await db.execute(text(sql), {"eid": event_id})).scalar()
        print(f"  {label:24s} {n} (expect 0)")


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--fetch-source", action="store_true")
    p.add_argument("--source-event-id", default=DEFAULT_SOURCE_EVENT_ID)
    p.add_argument("--dump-path", default=str(DEFAULT_DUMP_PATH))
    p.add_argument("--target-name", default="Sundance 2Aug")
    p.add_argument("--target-scheduled-at", default="2026-08-02T12:30:00+00:00")
    p.add_argument("--target-scheduled-end-at", default="2026-08-02T22:30:00+00:00")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    dump_path = Path(args.dump_path)
    if args.fetch_source:
        asyncio.run(fetch_source(args.source_event_id, dump_path))
    else:
        asyncio.run(clone_from_dump(
            dump_path,
            target_name=args.target_name,
            target_scheduled_at=datetime.fromisoformat(args.target_scheduled_at),
            target_scheduled_end_at=datetime.fromisoformat(args.target_scheduled_end_at),
        ))


if __name__ == "__main__":
    main()
