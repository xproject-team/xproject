"""Regenerate one event's post-event reports under the event_orders
revenue definition (Day 14 migration), safely and idempotently.

Usage (from backend/, inside the app venv / container):

    # ALWAYS dry-run first — read-only, prints the full plan + pre-flight:
    python -m app.scripts.regenerate_reports_event_orders \
        --tenant-id <uuid> --event <event_uuid>

    # Then, deliberately:
    python -m app.scripts.regenerate_reports_event_orders \
        --tenant-id <uuid> --event <event_uuid> --execute

ONE EVENT PER INVOCATION, by design — regenerate the season in
chronological order (oldest first) so each new report's previous-event
comparison reads the already-corrected predecessor.

What --execute does, in order:
  1. Pre-flight (also what dry-run prints):
       - event is COMPLETED; latest READY primary-language report found
       - event_orders total vs the stored report total (the delta v+1
         will show)
       - unresolved pending_shop_mappings (money in NEITHER table):
         BLOCKS unless --allow-parked
       - customer_sessions spend vs event_orders total (guest sections
         are rebuilt at regeneration time from customer_sessions; if
         features predate an order recovery, WARNS — rebuild features
         first or accept stale guest figures in the new version)
  2. ReportService.regenerate(latest ready IT report)  → IT v+1
     (C5 semantics: the old version is superseded only after success)
  3. ReportService.get_report_in_language(IT v+1, 'en') → EN v+1 derived
     from IT v+1's FROZEN snapshot (C6) — numbers cent-identical across
     the language pair. If a previous run left a failed sibling row, it
     is re-populated from the snapshot instead of being returned as-is.
  4. Chain supersede pointers, BOTH languages: every ready, unsuperseded
     row older than the new pair is pointed at the new row of its own
     language. regenerate() only chains the row it was invoked on; the
     sibling language's predecessor — and any same-language row left
     dangling by historical version divergence — needs this explicit
     hop or its audit pointer stays NULL.
  5. Inline verification: new stored headline vs SUM(fiscal_gross_cents)
     over confirmed orders — must match TO THE CENT or the script exits
     non-zero.

Idempotent: if the latest ready primary report already carries
revenue_source='event_orders', steps 2 is skipped and the script only
completes whatever a partial earlier run left undone (missing sibling,
missing supersede pointer). Old versions are NEVER modified beyond their
superseded_by pointer; data_json/pdf_bytes are untouched by design
(reports/service.py has no code path that rewrites a ready snapshot).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

PRIMARY_LANGUAGE = "it"   # matches the cron's generation order
SIBLING_LANGUAGE = "en"


def _eur(cents: int | None) -> str:
    return f"€{(Decimal(cents or 0) / 100):.2f}"


async def _preflight(db, tenant_id: UUID, event_id: UUID) -> dict:
    """Read-only checks. Returns the facts; caller decides what blocks."""
    row = (await db.execute(text("""
        SELECT e.name, e.ended_at, upper(e.status::text) AS status,
          (SELECT COALESCE(SUM(fiscal_gross_cents), 0) FROM event_orders
            WHERE tenant_id = :tid AND event_id = :eid AND confirmed_line_count > 0
          ) AS eo_cents,
          (SELECT COALESCE(SUM(total_gross_cents), 0) FROM pending_shop_mappings
            WHERE tenant_id = :tid AND event_id = :eid AND resolved_at IS NULL
          ) AS parked_cents,
          (SELECT COUNT(*) FROM pending_shop_mappings
            WHERE tenant_id = :tid AND event_id = :eid AND resolved_at IS NULL
          ) AS parked_rows,
          (SELECT COALESCE(SUM(total_spend_cents), 0) FROM customer_sessions
            WHERE tenant_id = :tid AND event_id = :eid
          ) AS sessions_cents
        FROM events e WHERE e.tenant_id = :tid AND e.id = :eid
    """), {"tid": str(tenant_id), "eid": str(event_id)})).mappings().first()
    if row is None:
        raise SystemExit(f"ABORT: event {event_id} not found for tenant {tenant_id}")
    return dict(row)


async def _report_rows(db, tenant_id: UUID, event_id: UUID) -> list[dict]:
    rows = (await db.execute(text("""
        SELECT id, language, version, status, superseded_by,
               data_json->>'revenue_source' AS revenue_source,
               data_json->'revenue_kpis'->>'total_revenue' AS stored_total,
               md5(coalesce(data_json::text, '')) AS data_md5
        FROM reports
        WHERE tenant_id = :tid AND event_id = :eid
        ORDER BY language, version
    """), {"tid": str(tenant_id), "eid": str(event_id)})).mappings().all()
    return [dict(r) for r in rows]


def _print_rows(rows: list[dict]) -> None:
    for r in rows:
        sup = "superseded" if r["superseded_by"] else "current   "
        print(
            f"    {r['language']} v{r['version']:<2} {r['status']:<10} {sup} "
            f"source={r['revenue_source'] or 'stock_transactions(pre-migration)':<35} "
            f"total={r['stored_total'] or '—':<12} md5={r['data_md5'][:10]}"
        )


async def run(tenant_id: UUID, event_id: UUID, *, execute: bool, allow_parked: bool) -> int:
    from app.core.database import AsyncSessionLocal
    from app.modules.reports.repository import ReportRepository
    from app.modules.reports.service import ReportService

    async with AsyncSessionLocal() as db:
        facts = await _preflight(db, tenant_id, event_id)
        print(f"event: {facts['name']}  status={facts['status']}  ended={facts['ended_at']}")
        print(f"  event_orders total (new definition):   {_eur(facts['eo_cents'])}")
        print(f"  parked/unresolved (in NEITHER table):  {_eur(facts['parked_cents'])} "
              f"across {facts['parked_rows']} shop mapping(s)")
        print(f"  customer_sessions identified spend:    {_eur(facts['sessions_cents'])}")

        if facts["status"] != "COMPLETED":
            print("ABORT: event is not COMPLETED — reports require a final state.")
            return 1
        if facts["parked_rows"] and not allow_parked:
            print("ABORT: unresolved parked orders exist — that money is in NEITHER "
                  "revenue table, so a regeneration now bakes in an incomplete total. "
                  "Resolve the shop mappings first, or rerun with --allow-parked to "
                  "accept the gap knowingly.")
            return 1

        before = await _report_rows(db, tenant_id, event_id)
        print("\n  reports before:")
        _print_rows(before)

        ready_primary = [
            r for r in before
            if r["language"] == PRIMARY_LANGUAGE and r["status"] == "ready"
        ]
        if not ready_primary:
            print(f"ABORT: no ready {PRIMARY_LANGUAGE.upper()} report to regenerate from.")
            return 1
        latest_primary = max(ready_primary, key=lambda r: r["version"])
        already_migrated = latest_primary["revenue_source"] == "event_orders"

        stored = Decimal(latest_primary["stored_total"] or "0")
        delta = Decimal(facts["eo_cents"]) / 100 - stored
        print(f"\n  latest ready {PRIMARY_LANGUAGE.upper()} report: "
              f"v{latest_primary['version']} total={stored} "
              f"({latest_primary['revenue_source'] or 'pre-migration'})")
        print(f"  delta the new version will show:       {delta:+.2f}")

        if not execute:
            # Mirror the service's EVENT-scoped allocation: the new pair
            # lands past the highest version in ANY language/status.
            next_version = max(r["version"] for r in before) + 1
            action = (
                "nothing (already on event_orders; would only complete sibling/pointers)"
                if already_migrated else
                f"regenerate {PRIMARY_LANGUAGE.upper()} v{latest_primary['version']} → "
                f"v{next_version}, derive {SIBLING_LANGUAGE.upper()} "
                f"sibling from its frozen snapshot at v{next_version}, chain "
                f"supersede pointers in both languages"
            )
            print(f"\nDRY-RUN — no writes. Would do: {action}")
            print("Re-run with --execute to apply.")
            return 0

        service = ReportService(db)
        repo = ReportRepository(db)

        # ── Step 2: regenerate the primary language ──────────────────────
        if already_migrated:
            new_primary = await repo.get_by_id(tenant_id, UUID(str(latest_primary["id"])))
            print("\n  primary already on event_orders — completing sibling/pointers only.")
        else:
            print("\n  regenerating primary…")
            new_primary = await service.regenerate(
                tenant_id, UUID(str(latest_primary["id"])), generated_by=None,
            )
            print(f"  → {PRIMARY_LANGUAGE.upper()} v{new_primary.version} {new_primary.status}")

        # ── Step 3: derive the sibling from the frozen snapshot ──────────
        sibling = await service.get_report_in_language(
            tenant_id, new_primary.id, SIBLING_LANGUAGE,
        )
        if sibling.status != "ready":
            # A failed sibling row from an earlier attempt is returned
            # as-is by get_report_in_language (it matches on
            # version+language with no status check) — re-populate it
            # from the primary's frozen snapshot.
            print(f"  sibling {SIBLING_LANGUAGE.upper()} v{sibling.version} is "
                  f"'{sibling.status}' — re-deriving from the frozen snapshot…")
            sibling = await service._populate_sibling(sibling, new_primary)
        print(f"  → {SIBLING_LANGUAGE.upper()} v{sibling.version} {sibling.status}")

        # ── Step 4: chain supersede pointers, both languages ─────────────
        # regenerate() chains only the row it was invoked on. Everything
        # else that is ready, unsuperseded, and older than the new pair
        # gets pointed at the new row of ITS OWN language: the sibling
        # language's predecessor, and any same-language row left dangling
        # by historical version divergence between the languages. The
        # superseded_by re-check after get_by_id makes this a no-op for
        # rows regenerate() already chained.
        new_by_language = {PRIMARY_LANGUAGE: new_primary, SIBLING_LANGUAGE: sibling}
        for lang, new_row in new_by_language.items():
            for old in before:
                if (
                    old["language"] == lang and old["status"] == "ready"
                    and old["version"] < new_row.version and not old["superseded_by"]
                ):
                    old_row = await repo.get_by_id(tenant_id, UUID(str(old["id"])))
                    if old_row is not None and old_row.superseded_by is None:
                        await repo.supersede(old_row, new_row.id)
                        print(f"  superseded {lang.upper()} v{old_row.version} "
                              f"→ v{new_row.version}")
        await db.commit()

        # ── Step 5: verify — cent-identical + old versions untouched ─────
        after = await _report_rows(db, tenant_id, event_id)
        print("\n  reports after:")
        _print_rows(after)

        new_total_cents = round(Decimal(
            next(r for r in after
                 if r["language"] == PRIMARY_LANGUAGE and r["version"] == new_primary.version
                 )["stored_total"]
        ) * 100)
        ok_cent = int(new_total_cents) == int(facts["eo_cents"])

        before_md5 = {r["id"]: r["data_md5"] for r in before}
        touched = [
            r for r in after
            if r["id"] in before_md5 and r["data_md5"] != before_md5[r["id"]]
        ]
        sib_total = next(
            (r["stored_total"] for r in after
             if r["language"] == SIBLING_LANGUAGE and r["version"] == sibling.version),
            None,
        )
        new_total = next(
            r["stored_total"] for r in after
            if r["language"] == PRIMARY_LANGUAGE and r["version"] == new_primary.version
        )
        ok_pair = sib_total == new_total

        print(f"\n  VERIFY headline vs event_orders (to the cent): "
              f"{'PASS' if ok_cent else 'FAIL'} "
              f"(report {new_total_cents}c vs orders {facts['eo_cents']}c)")
        print(f"  VERIFY language pair identical:                {'PASS' if ok_pair else 'FAIL'} "
              f"({new_total} vs {sib_total})")
        print(f"  VERIFY old snapshots untouched:                "
              f"{'PASS' if not touched else 'FAIL: ' + str([r['id'] for r in touched])}")

        return 0 if (ok_cent and ok_pair and not touched) else 2


def main() -> None:
    p = argparse.ArgumentParser(prog="regenerate_reports_event_orders")
    p.add_argument("--tenant-id", required=True, type=UUID)
    p.add_argument("--event", required=True, type=UUID,
                   help="ONE event per invocation — run the season oldest-first")
    p.add_argument("--execute", action="store_true",
                   help="apply changes (default: dry-run, read-only)")
    p.add_argument("--allow-parked", action="store_true",
                   help="proceed even with unresolved parked orders (money in "
                        "neither revenue table) — accept the gap knowingly")
    args = p.parse_args()
    sys.exit(asyncio.run(run(
        args.tenant_id, args.event,
        execute=args.execute, allow_parked=args.allow_parked,
    )))


if __name__ == "__main__":
    main()
