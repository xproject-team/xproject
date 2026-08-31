"""Background task definitions — each async function is an arq task.

Tasks are enqueued by the cron in scheduler.py or on-demand by services.
Each task receives the arq context dict as its first positional argument.

Critical design principle: task bodies NEVER raise out to arq. We catch
everything, log it, and return a structured result. arq's retry semantics
plus our dedup logic make retries safe, but we want observability, not
silent failures or infinite retry loops.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal as async_session_factory
from app.modules.auth.models import User  # noqa: F401 (needed for ORM mapper init)
from app.modules.alerts.engine import AlertsOrchestrator
from app.modules.events.models import Event, EventStatus

logger = logging.getLogger(__name__)


# ─── Alert evaluation (the hot path) ──────────────────────────────────────────


async def evaluate_alerts(
    ctx: dict,
    tenant_id: str,
    event_id: str,
) -> dict:
    """Run one depletion-alert evaluation pass for one tenant × event.

    Enqueued by the cron every 5 minutes (one job per live event). Can also
    be enqueued on-demand (e.g. right after a large POS transaction batch)
    for a lower-latency alert.

    Arguments are passed as strings (UUIDs aren't directly JSON-serializable
    by arq without a custom serializer). We parse at the boundary.

    Returns a counters dict for observability:
        {'checked': N, 'fired': M, 'auto_resolved': K, 'status': 'ok'|'error'}
    """
    try:
        tenant_uuid = UUID(tenant_id)
        event_uuid = UUID(event_id)
    except (TypeError, ValueError) as e:
        logger.warning("evaluate_alerts: bad UUID args %s %s: %s",
                       tenant_id, event_id, e)
        return {"status": "error", "reason": "invalid_uuid"}

    session: AsyncSession
    async with async_session_factory() as session:
        try:
            evaluator = AlertsOrchestrator(session)
            counters = await evaluator.run_all(tenant_uuid, event_uuid)
            await session.commit()
            return {"status": "ok", **counters}
        except Exception as e:  # noqa: BLE001
            # Soft failure: log, roll back, return structured error. arq will
            # NOT retry (we've swallowed the exception deliberately) — the
            # next cron tick runs evaluation again anyway.
            logger.exception(
                "evaluate_alerts failed: tenant=%s event=%s: %s",
                tenant_id, event_id, e,
            )
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return {"status": "error", "reason": str(e)[:200]}


async def cron_evaluate_all_live_events(ctx: dict) -> dict:
    """Cron entry point: find every live event across all tenants and enqueue
    one evaluate_alerts job per event.

    Runs every 5 minutes. Keeps arq free to dispatch the actual evaluations
    to worker slots in parallel. If there are zero live events, does nothing.
    """
    enqueued = 0
    skipped = 0

    async with async_session_factory() as session:
        try:
            stmt = select(Event.id, Event.tenant_id).where(
                Event.status == EventStatus.LIVE,
            )
            rows = (await session.execute(stmt)).all()
        except Exception as e:  # noqa: BLE001
            logger.exception("cron: failed to list live events: %s", e)
            return {"status": "error", "enqueued": 0}

    redis = ctx["redis"]
    for event_id, tenant_id in rows:
        try:
            job = await redis.enqueue_job(
                "evaluate_alerts",
                str(tenant_id),
                str(event_id),
                _job_id=f"eval:{tenant_id}:{event_id}",
            )
            if job is None:
                # _job_id collision — a previous job is already pending for
                # this event. That's fine; the earlier tick's work will run.
                skipped += 1
            else:
                enqueued += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "cron: failed to enqueue for event=%s: %s",
                event_id, e,
            )

    if enqueued or skipped:
        logger.info(
            "cron: enqueued=%d skipped=%d for %d live events",
            enqueued, skipped, len(rows),
        )
    return {
        "status": "ok",
        "live_events": len(rows),
        "enqueued": enqueued,
        "skipped": skipped,
    }


# ─── Other tasks (stubs — unchanged from before) ──────────────────────────────


async def run_predictions(ctx: dict, event_id: str) -> dict:
    """Generate ML demand predictions for all SKUs in the given event.

    Stub: real implementation ships with the predictions module.
    """
    # Stage-one observability: this has always been a stub returning a
    # fixed ok — say so in the payload rather than letting the zero look
    # like a measured outcome (docs/job-status-semantics.md).
    return {
        "event_id": event_id,
        "status": "ok",
        "predictions_generated": 0,
        "stub": True,
        "note": "not implemented — fixed response; no prediction work was performed",
    }


# ─── Nowcast auto-retrain (Phase F) ────────────────────────────────────────────


async def retrain_predictor(ctx: dict, tenant_id: str) -> dict:
    """Retrain the "ML Predicted" nowcast's training set from this
    tenant's COMPLETED events (see predictions/nowcast/retrain.py).

    Enqueued by EventService.end_event() right after an event's
    LIVE -> COMPLETED transition commits (app/modules/events/service.py).
    Idempotent — retrain_from_completed_events upserts by event_id, so
    re-running (retries, manual re-enqueue) never double-counts an event.

    Persists to model_artifacts (tenant_id-scoped, versioned, durable —
    same mechanism as retrain_demand_predictor below, re-platformed off
    the old shared/ephemeral parquet files in 2026-08; see
    nowcast/predictor.py's module docstring for why). Never raises out
    to arq: any failure here is logged and returned as a structured
    error. The active model_artifacts row keeps serving the
    last-known-good fit on failure — a bad retrain must never take the
    /revenue-forecast endpoint down, and must never roll back the event
    completion that triggered it (that transaction has already
    committed by the time this task runs).
    """
    try:
        tenant_uuid = UUID(tenant_id)
    except (TypeError, ValueError) as e:
        logger.warning("retrain_predictor: bad tenant_id %s: %s", tenant_id, e)
        return {"status": "error", "reason": "invalid_uuid"}

    from app.modules.predictions.nowcast.retrain import retrain_from_completed_events

    async with async_session_factory() as session:
        try:
            return await retrain_from_completed_events(
                session, tenant_uuid, triggered_by="event_completed",
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("retrain_predictor failed: tenant=%s: %s", tenant_id, e)
            return {"status": "error", "reason": str(e)[:200]}


async def retrain_demand_predictor(ctx: dict, tenant_id: str, event_id: str | None = None) -> dict:
    """Retrain the drinks-demand forecaster (bar/hour/category) from
    this tenant's COMPLETED events (see predictions/demand/retrain.py).

    Same trigger and isolation contract as retrain_predictor, above —
    enqueued by EventService.end_event() right after an event's
    LIVE -> COMPLETED transition commits, never raises out to arq, and
    a failure here must never roll back the event completion that
    triggered it. Versioned (model_artifacts), not a parquet overwrite
    like the nowcast — see retrain.py's module docstring for why.
    """
    try:
        tenant_uuid = UUID(tenant_id)
    except (TypeError, ValueError) as e:
        logger.warning("retrain_demand_predictor: bad tenant_id %s: %s", tenant_id, e)
        return {"status": "error", "reason": "invalid_uuid"}

    event_uuid: UUID | None = None
    if event_id:
        try:
            event_uuid = UUID(event_id)
        except (TypeError, ValueError):
            event_uuid = None

    from app.modules.predictions.demand.retrain import retrain_demand_model

    async with async_session_factory() as session:
        try:
            return await retrain_demand_model(
                session, tenant_uuid,
                triggered_by="event_completed",
                triggered_by_event_id=event_uuid,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("retrain_demand_predictor failed: tenant=%s: %s", tenant_id, e)
            return {"status": "error", "reason": str(e)[:200]}


# ─── Customer-features population (Reports improvement) ──────────────────────

async def populate_customer_features(ctx: dict, tenant_id: str, event_id: str) -> dict:
    """Build customer_sessions/customer_purchases for one just-completed
    event (see app/scripts/build_customer_features.py::build_event).

    Enqueued by EventService.end_event() right after LIVE -> COMPLETED
    commits, alongside the nowcast/demand retrain triggers -- same
    isolation contract, never raises out to arq, never rolls back the
    event completion that triggered it.

    Called with expected_customers=None: the manual-backfill drift-
    protection anchor doesn't exist for an automatic trigger on a brand
    new event, so the write always proceeds (see build_event's
    docstring for why that's safe here and not for the manual path).

    The report-generation cron does not hard-depend on this finishing in
    time -- it prefers to wait for this job (customer_sessions existing
    for the event) but generates the report anyway past a hard cutoff
    even if this never completes (see reports/repository.py's
    list_events_needing_reports). A failure here degrades the report's
    Guests/Comparison/Decomposition sections, never blocks it.
    """
    try:
        tenant_uuid = UUID(tenant_id)
        event_uuid = UUID(event_id)
    except (TypeError, ValueError) as e:
        logger.warning("populate_customer_features: bad UUID args %s %s: %s",
                       tenant_id, event_id, e)
        return {"status": "error", "reason": "invalid_uuid"}

    from app.scripts.build_customer_features import build_event

    try:
        report = await build_event(tenant_id=tenant_uuid, event_id=event_uuid)
        # Stage-one observability: the facts a human needs to judge
        # whether this run did anything — what the event held
        # (confirmed orders), what carried an identity (the exact
        # expression the builder consumes), and what came out. Queried,
        # not claimed. No verdict here: stage two decides what counts
        # as failure after these numbers have been watched.
        from sqlalchemy import text as _text

        from app.modules.events.models import EventOrder as _EventOrder

        async with async_session_factory() as facts_session:
            confirmed_orders = (await facts_session.execute(
                select(func.count()).select_from(_EventOrder).where(
                    _EventOrder.tenant_id == tenant_uuid,
                    _EventOrder.event_id == event_uuid,
                    _EventOrder.confirmed_line_count > 0,
                )
            )).scalar_one()
            identified_orders = (await facts_session.execute(_text(
                "SELECT count(*) FROM event_orders "
                "WHERE tenant_id = :tid AND event_id = :eid "
                "  AND confirmed_line_count > 0 "
                "  AND raw_extras->'user'->>'_id' IS NOT NULL"
            ), {"tid": str(tenant_uuid), "eid": str(event_uuid)})).scalar_one()
        return {
            "status": "ok" if report.sanity_passed else "error",
            "sessions_created": report.sessions_created,
            "purchases_created": report.purchases_created,
            "distinct_customers": report.distinct_customers,
            "confirmed_orders_seen": int(confirmed_orders),
            "identified_orders_seen": int(identified_orders),
            "zero_line_orders": report.zero_line_orders,
        }
    except Exception as e:  # noqa: BLE001
        logger.exception(
            "populate_customer_features failed: tenant=%s event=%s: %s",
            tenant_id, event_id, e,
        )
        return {"status": "error", "reason": str(e)[:200]}


# ─── Customer intelligence refresh (Day 4) ────────────────────────────────────

async def refresh_customer_intelligence(ctx: dict, tenant_id: str, event_id: str) -> dict:
    """Recompute the customer-intelligence panel for one LIVE event,
    write it to the ~30s cache fresh, and push a thin "something
    changed" WebSocket notification — same pattern as evaluate_alerts:
    background compute, then notify, frontend refetches via the
    (now-warm) GET endpoint. Never raises out to arq.
    """
    try:
        tenant_uuid = UUID(tenant_id)
        event_uuid = UUID(event_id)
    except (TypeError, ValueError) as e:
        logger.warning("refresh_customer_intelligence: bad UUID args %s %s: %s",
                       tenant_id, event_id, e)
        return {"status": "error", "reason": "invalid_uuid"}

    from app.modules.customer_intelligence.service import get_customer_intelligence_cached

    async with async_session_factory() as session:
        try:
            await get_customer_intelligence_cached(
                session, tenant_uuid, event_uuid, datetime.now(timezone.utc), use_cache=False,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception(
                "refresh_customer_intelligence failed: tenant=%s event=%s: %s",
                tenant_id, event_id, e,
            )
            return {"status": "error", "reason": str(e)[:200]}

    # get_customer_intelligence_cached always WRITES the fresh cache
    # entry (use_cache=False only skips the READ), so the endpoint's
    # next poll hits a warm cache regardless of whether this notify
    # step below succeeds.
    try:
        from app.core.redis_client import publish as _ws_publish
        await _ws_publish(
            f"event:{event_id}",
            json.dumps({"type": "customer_intelligence.refreshed", "event_id": event_id}),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("refresh_customer_intelligence: WS notify failed: %s", e)

    return {"status": "ok"}


async def cron_refresh_customer_intelligence_for_all_live_events(ctx: dict) -> dict:
    """Cron entry point: find every LIVE event across all tenants and
    enqueue one refresh_customer_intelligence job per event. Same
    enumerate-then-fan-out shape as cron_evaluate_all_live_events.
    """
    enqueued = 0
    skipped = 0

    async with async_session_factory() as session:
        try:
            stmt = select(Event.id, Event.tenant_id).where(
                Event.status == EventStatus.LIVE,
            )
            rows = (await session.execute(stmt)).all()
        except Exception as e:  # noqa: BLE001
            logger.exception("cron: failed to list live events for customer-intelligence refresh: %s", e)
            return {"status": "error", "enqueued": 0}

    redis = ctx["redis"]
    for event_id, tenant_id in rows:
        try:
            job = await redis.enqueue_job(
                "refresh_customer_intelligence",
                str(tenant_id),
                str(event_id),
                _job_id=f"ci_refresh:{tenant_id}:{event_id}",
            )
            if job is None:
                skipped += 1
            else:
                enqueued += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "cron: failed to enqueue customer-intelligence refresh for event=%s: %s",
                event_id, e,
            )

    return {"status": "ok", "enqueued": enqueued, "skipped": skipped}


# ─── Post-event report generation ─────────────────────────────────────────────


async def generate_report(ctx: dict, event_id: str) -> dict:
    """Generate post-event reports (IT + EN) for one completed event.

    Enqueued by cron_generate_reports_for_completed_events 15+ min after
    an event's ended_at timestamp. Can also be enqueued on-demand by
    other code paths (e.g. a future admin endpoint).

    The tenant_id is derived from the event row — we don't pass it as a
    parameter because the cron scans cross-tenant (runs in system context,
    not user context; see spec §5.2).

    Idempotent: generate_for_event_batch skips languages that already
    have a report row for this event. Safe to retry.

    Returns counters for observability:
        {"status": "ok", "reports_generated": N, "event_id": "..."}
    """
    try:
        event_uuid = UUID(event_id)
    except (TypeError, ValueError) as e:
        logger.warning("generate_report: bad event_id %s: %s", event_id, e)
        return {"status": "error", "reason": "invalid_uuid"}

    # Lazy imports — avoids loading reportlab + matplotlib at module import
    # time, which would slow worker boot for tenants that never generate
    # reports. First cron tick pays the cost; subsequent ticks are warm.
    from app.modules.events.models import Event as _Event, EventStatus
    from app.modules.reports.service import ReportService

    async with async_session_factory() as session:
        try:
            event_row = (
                await session.execute(
                    select(_Event.tenant_id).where(_Event.id == event_uuid)
                )
            ).scalar_one_or_none()
            if event_row is None:
                logger.warning("generate_report: event %s not found", event_id)
                return {"status": "error", "reason": "event_not_found"}

            service = ReportService(session)
            reports = await service.generate_for_event_batch(
                tenant_id=event_row,
                event_id=event_uuid,
            )
            # Stage-one observability: generate_for_event_batch swallows
            # per-language failures, so reports_generated alone cannot
            # distinguish "both generated" from "both failed". Report
            # per-language DB truth — the latest report row's status per
            # language, queried after the fact (query, don't claim).
            from app.modules.reports.models import Report as _Report

            lang_rows = (await session.execute(
                select(_Report.language, _Report.version, _Report.status)
                .where(_Report.event_id == event_uuid)
                .order_by(_Report.language, _Report.version)
            )).all()
            languages: dict[str, str] = {}
            for lang, _version, report_status in lang_rows:
                languages[str(lang)] = str(report_status)  # last = latest version
            for expected in ("it", "en"):
                languages.setdefault(expected, "missing")
            return {
                "status": "ok",
                "event_id": event_id,
                "reports_generated": len(reports),
                "languages": languages,
            }
        except Exception as e:  # noqa: BLE001
            logger.exception(
                "generate_report failed: event=%s: %s", event_id, e,
            )
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return {"status": "error", "reason": str(e)[:200]}


async def cron_generate_reports_for_completed_events(ctx: dict) -> dict:
    """Cron entry point: find completed events past their grace window and
    enqueue report generation for each.

    Runs on off-minutes so it doesn't contend with the alerts cron which
    runs on :00, :05, :10, etc. Eligibility per spec §5.2:
      - status = COMPLETED
      - ended_at is not null
      - ended_at < now - 15 min (grace for late POS transactions)
      - NOT EXISTS any report row for this event

    Uses ReportRepository.list_events_needing_reports which encodes all
    three conditions in one SQL statement.
    """
    from app.modules.reports.repository import ReportRepository

    enqueued = 0
    skipped = 0

    async with async_session_factory() as session:
        try:
            repo = ReportRepository(session)
            eligible = await repo.list_events_needing_reports(grace_minutes=15)
        except Exception as e:  # noqa: BLE001
            logger.exception("cron_generate_reports: list failed: %s", e)
            return {"status": "error", "eligible": 0}

    redis = ctx["redis"]
    for event in eligible:
        try:
            job = await redis.enqueue_job(
                "generate_report",
                str(event.id),
                _job_id=f"report:{event.id}",
            )
            if job is None:
                skipped += 1
            else:
                enqueued += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "cron_generate_reports: enqueue failed for event=%s: %s",
                event.id, e,
            )

    if enqueued or skipped:
        logger.info(
            "cron_generate_reports: enqueued=%d skipped=%d of %d eligible",
            enqueued, skipped, len(eligible),
        )
    return {
        "status": "ok",
        "eligible": len(eligible),
        "enqueued": enqueued,
        "skipped": skipped,
    }



async def cron_close_paused_invoices(ctx: dict) -> dict:
    """Cron entry point: auto-close warehouse invoices that have been
    PAUSED for more than 48 hours.

    Per docs/warehouse-module-spec.md §5, paused sessions can sit forever
    waiting for a resume that may never come (truck rescheduled, staff
    forgot, shift ended). After 48h we force-close with whatever scans
    are on file. The reconciliation engine runs against the partial scan
    set and the invoice transitions to DISCREPANCY (not VERIFIED — a
    paused-then-auto-closed session almost certainly has unscanned items).

    Runs on minute offsets {2, 7, 12, ...} to avoid colliding with the
    alerts cron (:00) and reports cron (:01). Cheap query — uses the
    existing (tenant_id, status) index on delivery_invoices.

    No fan-out: the work per invoice is just a status transition + the
    discrepancy report compute. Both fast (<200ms total). Doing it inline
    avoids Redis enqueue overhead and contention.

    F-03 (2026-08): each invoice is processed in its OWN freshly opened
    session, not a session shared across the whole tick — the same fix
    F-02 applied to cron_auto_transition_event_statuses. Previously, a
    failure closing one invoice left the shared session's transaction
    aborted (no rollback), so the very next invoice's first query failed
    immediately too — logged as if THAT invoice individually failed to
    close, cascading through every remaining invoice in the tick from one
    root cause. A session per invoice means a failure can only ever
    affect that one invoice's own (otherwise-empty) transaction.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.modules.warehouse.models import DeliveryInvoice
    from app.modules.warehouse.invoice_service import (
        InvoiceService,
        InvalidInvoiceTransitionError,
    )

    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    closed = 0
    failed = 0

    async with async_session_factory() as session:
        try:
            stmt = (
                select(DeliveryInvoice.id, DeliveryInvoice.tenant_id)
                .where(
                    DeliveryInvoice.status == "PAUSED",
                    DeliveryInvoice.scan_started_at < cutoff,
                )
                .order_by(DeliveryInvoice.scan_started_at.asc())
            )
            eligible = (await session.execute(stmt)).all()
        except Exception as e:  # noqa: BLE001
            logger.exception("cron_close_paused: list failed: %s", e)
            return {"status": "error", "eligible": 0}

    if not eligible:
        return {"status": "ok", "eligible": 0, "closed": 0, "failed": 0}

    for invoice_id, tenant_id in eligible:
        async with async_session_factory() as invoice_session:
            try:
                # close_scan handles its own transitions + commit. Pass
                # closed_by=None to mark this as a system action.
                svc = InvoiceService(invoice_session)
                await svc.close_scan(
                    tenant_id=tenant_id,
                    invoice_id=invoice_id,
                    closed_by=None,
                )
                closed += 1
            except InvalidInvoiceTransitionError:
                # Race: invoice changed state between our SELECT and the
                # close call. Safe to skip; next tick re-evaluates. Scoped
                # to invoice_session only (F-03) — cannot affect any
                # other invoice's processing.
                await invoice_session.rollback()
            except Exception as e:  # noqa: BLE001
                # Scoped to invoice_session only (F-03) — see note above.
                await invoice_session.rollback()
                logger.warning(
                    "cron_close_paused: failed to close invoice=%s: %s",
                    invoice_id, e,
                )
                failed += 1

    if closed or failed:
        logger.info(
            "cron_close_paused: closed=%d failed=%d of %d eligible",
            closed, failed, len(eligible),
        )
    return {
        "status": "ok",
        "eligible": len(eligible),
        "closed": closed,
        "failed": failed,
    }

# ─── Slesh POS polling (one job per live event) ───────────────────────────────


async def poll_slesh_for_event(
    ctx: dict,
    tenant_id: str,
    event_id: str,
) -> dict:
    """Run one Slesh polling cycle for one tenant × event.

    Enqueued by ``cron_poll_slesh_for_all_live_events`` every 5 minutes.
    Wraps ``poll_slesh_orders()`` from ``app/modules/pos/slesh_poller.py``
    so the cron + arq machinery don't need to know about Slesh internals.

    Returns a counters dict for observability:
        {'status': 'ok' | 'error' | 'circuit_open',
         'orders_seen': N, 'orders_ingested': M, 'lines_ingested': L,
         'lines_replayed': R, 'lines_skipped': S, 'lines_errors': E,
         'error_msg': '...'}
    """
    # Local import (not top-level) to avoid pulling the whole POS module
    # into every task module's import path on worker boot. tasks.py is
    # imported by scheduler.py at startup, so heavy module imports here
    # would slow worker startup with no benefit.
    from app.modules.pos.slesh_poller import poll_slesh_orders

    try:
        result = await poll_slesh_orders(
            tenant_id=UUID(tenant_id),
            event_id=UUID(event_id),
        )
        # Stage-one observability: the counters alone cannot tell a
        # healthy quiet minute from a cycle that saw work and dropped
        # all of it. Add the window actually polled and a skip-reason
        # histogram — the inputs to a verdict, not a verdict; 'ok'
        # still means what it meant (transport completed).
        skip_reasons: dict[str, int] = {}
        for order_result in result.per_order_results:
            for reason in getattr(order_result, "skip_reasons", []):
                if "parked" in reason:
                    key = "parked_unmapped_shop"
                elif "no product matched" in reason:
                    key = "no_product_match"
                elif "refunded" in reason:
                    key = "refunded_line"
                elif "no shop reference" in reason:
                    key = "no_shop_reference"
                else:
                    key = "other"
                skip_reasons[key] = skip_reasons.get(key, 0) + 1
        return {
            "status":           result.status,
            "orders_seen":      result.orders_seen,
            "orders_ingested":  result.orders_ingested,
            "lines_ingested":   result.lines_ingested,
            "lines_replayed":   result.lines_replayed,
            "lines_skipped":    result.lines_skipped,
            "lines_errors":     result.lines_errors,
            "error_msg":        result.error_msg or "",
            "window_since":     (result.window.since_ts.isoformat()
                                 if result.window else None),
            "window_until":     (result.window.until_ts.isoformat()
                                 if result.window else None),
            "lines_skipped_reasons": skip_reasons,
        }
    except Exception as e:  # noqa: BLE001 — arq must never see a raise
        logger.exception(
            "poll_slesh_for_event: tenant=%s event=%s unexpected failure",
            tenant_id, event_id,
        )
        return {
            "status":    "error",
            "error_msg": f"{type(e).__name__}: {e}",
        }


async def cron_poll_slesh_for_all_live_events(ctx: dict) -> dict:
    """Cron entry point: enumerate every live event and enqueue one
    ``poll_slesh_for_event`` job per (tenant, event).

    Runs every 5 minutes on off-minute slots {3, 8, 13, ...} so it never
    collides with cron_evaluate_all_live_events {0,5,10,...},
    cron_generate_reports_for_completed_events {1,6,11,...}, or
    cron_close_paused_invoices {2,7,12,...}.

    If SLESH_API_TOKEN is not configured, returns immediately — useful
    for developer machines without Slesh credentials.

    Mirrors cron_evaluate_all_live_events structurally so the pattern
    stays consistent across all our crons.
    """
    # Short-circuit if no POS adapter is configured and usable (developer
    # envs, CI). The check is adapter-aware, not token-aware: staging with
    # POS_ADAPTER=fake and no token MUST poll — the ingestion path is what
    # staging exists to rehearse. The skip payload is byte-identical to
    # the pre-factory behavior (production regression contract).
    from app.modules.pos.adapters.factory import pos_adapter_configured

    if not pos_adapter_configured():
        logger.debug(
            "cron_poll_slesh: skipped (no POS adapter configured — "
            "SLESH_API_TOKEN absent and POS_ADAPTER is not 'fake')"
        )
        return {"status": "skipped", "reason": "no_token", "enqueued": 0}

    enqueued = 0
    skipped  = 0

    async with async_session_factory() as session:
        try:
            stmt = select(Event.id, Event.tenant_id).where(
                Event.status == EventStatus.LIVE,
            )
            rows = (await session.execute(stmt)).all()
        except Exception as e:  # noqa: BLE001
            logger.exception("cron_poll_slesh: failed to list live events: %s", e)
            return {"status": "error", "enqueued": 0}

    redis = ctx["redis"]
    for event_id, tenant_id in rows:
        try:
            job = await redis.enqueue_job(
                "poll_slesh_for_event",
                str(tenant_id),
                str(event_id),
                _job_id=f"slesh:{tenant_id}:{event_id}",
            )
            if job is None:
                # _job_id collision — previous poll for this event hasn't
                # finished yet. Skip rather than queue two; protects
                # Slesh's rate limit + prevents duplicate work.
                skipped += 1
            else:
                enqueued += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "cron_poll_slesh: failed to enqueue for event=%s: %s",
                event_id, e,
            )

    if enqueued or skipped:
        logger.info(
            "cron_poll_slesh: enqueued=%d skipped=%d for %d live events",
            enqueued, skipped, len(rows),
        )
    return {
        "status":      "ok",
        "live_events": len(rows),
        "enqueued":    enqueued,
        "skipped":     skipped,
    }


async def cron_sync_bars_from_slesh(ctx: dict) -> dict:
    """Cron entry point: pull shop list from Slesh and upsert into bars.

    Runs at worker startup (run_at_startup=True) + once per hour on
    minute=4. The function is inlined (no per-event enqueue) because:
      - Bars sync is O(num_live_events) lightweight calls
      - Hourly cadence means no contention concern
      - Fewer moving parts = fewer crash surfaces on Sundance night

    For each LIVE event:
      1. Build a SleshAdapter from settings
      2. Call sync_shops() which:
         - creates new bars from Slesh shops we don't have
         - updates names + is_active for shops we already track
         - deactivates bars whose slesh_negozio_id no longer appears
           in Slesh's response (NEVER deletes — preserves FK chains)

    If SLESH_API_TOKEN is not configured, returns immediately. Useful
    for dev machines without Slesh credentials and for CI.

    Mirrors cron_poll_slesh_for_all_live_events for live-event
    enumeration, but does its work inline instead of enqueueing
    per-event jobs.
    """
    from app.modules.pos.adapters.factory import pos_adapter_configured

    if not pos_adapter_configured():
        logger.debug(
            "cron_sync_bars_from_slesh: skipped (no POS adapter configured — "
            "SLESH_API_TOKEN absent and POS_ADAPTER is not 'fake')"
        )
        return {"status": "skipped", "reason": "no_token"}

    # Import inside function to keep module import-time cheap and
    # avoid any module-load-order surprises with the POS adapter.
    from app.modules.pos.adapters.factory import get_pos_adapter
    from app.modules.pos.sync_service import sync_shops

    totals = {"created": 0, "updated": 0, "skipped": 0, "deactivated": 0, "errors": 0}
    events_processed = 0

    async with async_session_factory() as session:
        try:
            stmt = select(Event.id, Event.tenant_id).where(
                Event.status == EventStatus.LIVE,
            )
            rows = (await session.execute(stmt)).all()
        except Exception as e:  # noqa: BLE001
            logger.exception(
                "cron_sync_bars_from_slesh: failed to list live events: %s", e,
            )
            return {"status": "error", "events_processed": 0}

        async with get_pos_adapter() as adapter:
            for event_id, tenant_id in rows:
                try:
                    result = await sync_shops(
                        db=session,
                        adapter=adapter,
                        tenant_id=tenant_id,
                        event_id=event_id,
                    )
                    await session.commit()
                    totals["created"]     += result.created
                    totals["updated"]     += result.updated
                    totals["skipped"]     += result.skipped
                    totals["deactivated"] += result.deactivated
                    events_processed += 1
                    logger.info(
                        "cron_sync_bars_from_slesh: event=%s %s",
                        event_id, result,
                    )
                except Exception as e:  # noqa: BLE001
                    # Slesh down, network blip, etc. Roll back this event's
                    # partial work, log, continue with next event. Never
                    # let one failure poison the whole run on Sundance.
                    await session.rollback()
                    totals["errors"] += 1
                    logger.warning(
                        "cron_sync_bars_from_slesh: failed for event=%s: %s",
                        event_id, e,
                    )

    logger.info(
        "cron_sync_bars_from_slesh: %d/%d events processed, totals=%s",
        events_processed, len(rows), totals,
    )
    return {
        "status":           "ok",
        "events_processed": events_processed,
        "events_total":     len(rows),
        **totals,
    }


async def cron_auto_transition_event_statuses(ctx: dict) -> dict:
    """Cron entry point: auto-transition events based on scheduled times.

    Runs every 5 min on minute={5} (off-slot from existing crons —
    {0}, {1}, {2}, {3}, {4} are taken).

    Three responsibilities per tick (all idempotent — safe to retry):

    1. DRAFT events with scheduled_at <= now()
       Auto-promote: activate (DRAFT→ACTIVE) then start (ACTIVE→LIVE)
       Two-step transition because the state machine requires it.
       Owner forgot to do either step. Cron rescues.

    2. ACTIVE events with scheduled_at <= now()
       Auto-promote: start (ACTIVE→LIVE)
       Owner activated but forgot to start.

    3. LIVE events with scheduled_end_at <= now() AND no Slesh
       transaction in the last 60 minutes
       Auto-promote: end (LIVE→COMPLETED)
       The 60-min silence guard prevents a transient outage from
       accidentally ending a still-busy event.

    Honest design notes:
      - We call the existing service methods (activate_event,
        start_event, end_event). They handle assert_transition,
        idempotency, the one-live-per-tenant invariant, and commit
        the transaction. Cron stays a thin orchestrator.
      - F-02 (2026-08): each event is processed in its OWN freshly
        opened session, not a session shared across the whole tick.
        Previously, one event's session.rollback() (e.g. on
        LiveEventConflictError) expired every ORM object tracked by
        the shared session — including OTHER, not-yet-processed
        events still sitting in the due_events/stale_live list — and
        the next iteration's very first attribute access on one of
        those expired objects crashed with MissingGreenlet, uncaught,
        killing the rest of the tick. A separate session per event
        means a rollback can only ever affect that one event's own
        (otherwise-empty) transaction; nothing about it reaches any
        other event's processing. due_events is also now explicitly
        ordered by scheduled_at so a stuck/conflicting event can't
        occupy the same list position every tick — though with the
        per-event session fix, no other event is at risk of being
        starved by it either way.
      - On Sundance night, this is the safety net for Omar forgetting
        to click "Start" at 7pm. The 5-min cadence means a worst-case
        delay of ~5 min from scheduled_at to actual LIVE.
    """
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import select, func, and_, or_
    from app.modules.events.models import Event, EventStatus
    from app.modules.events.service import EventService
    from app.modules.stock_transactions.models import StockTransaction

    now = datetime.now(timezone.utc)
    silence_threshold = now - timedelta(minutes=60)

    counters = {
        "activated":   0,   # DRAFT -> ACTIVE
        "started":     0,   # ACTIVE -> LIVE
        "completed":   0,   # LIVE -> COMPLETED
        "skipped_silence": 0,  # LIVE past end, but recent tx -> wait
        "errors":      0,
    }

    # ── Responsibility 1+2: promote DRAFT/ACTIVE -> LIVE ─────────────
    try:
        async with async_session_factory() as session:
            stmt = (
                select(Event)
                .where(
                    and_(
                        Event.status.in_([EventStatus.DRAFT, EventStatus.ACTIVE]),
                        Event.scheduled_at <= now,
                    )
                )
                .order_by(Event.scheduled_at.asc())
            )
            due_events = (await session.execute(stmt)).scalars().all()
            # Snapshot everything the loop below needs while these objects
            # are still live — each event is then processed in its own
            # fresh session (F-02), so nothing after this point should
            # touch these ORM objects again.
            due_snapshots = [
                (event.id, event.tenant_id, event.name, event.status)
                for event in due_events
            ]
    except Exception as e:  # noqa: BLE001
        logger.exception("cron_auto_transition: failed to list due events: %s", e)
        return {"status": "error", **counters}

    for event_id, event_tenant_id, event_name, event_status_snapshot in due_snapshots:
        async with async_session_factory() as event_session:
            try:
                service = EventService(db=event_session)

                if event_status_snapshot == EventStatus.DRAFT:
                    await service.activate_event(event_tenant_id, event_id)
                    counters["activated"] += 1
                    # Now ACTIVE — chain into start
                    await service.start_event(event_tenant_id, event_id)
                    counters["started"] += 1
                    logger.info(
                        "cron_auto_transition: DRAFT->LIVE event=%s (%s)",
                        event_id, event_name,
                    )
                elif event_status_snapshot == EventStatus.ACTIVE:
                    await service.start_event(event_tenant_id, event_id)
                    counters["started"] += 1
                    logger.info(
                        "cron_auto_transition: ACTIVE->LIVE event=%s (%s)",
                        event_id, event_name,
                    )
            except Exception as e:  # noqa: BLE001
                # Most likely cause: LiveEventConflictError (another live
                # event in this tenant). Log and continue — owner gets
                # notified via the existing 409 flow when they retry
                # manually. This rollback is scoped to event_session only
                # (F-02) — it cannot affect any other event's processing.
                await event_session.rollback()
                counters["errors"] += 1
                logger.warning(
                    "cron_auto_transition: promotion failed for event=%s (%s): %s",
                    event_id, event_name, e,
                )

    # ── Responsibility 3: end stale LIVE events ──────────────────────
    try:
        async with async_session_factory() as session:
            stmt = select(Event).where(
                and_(
                    Event.status == EventStatus.LIVE,
                    Event.scheduled_end_at <= now,
                )
            )
            stale_live = (await session.execute(stmt)).scalars().all()
            stale_snapshots = [
                (event.id, event.tenant_id, event.name)
                for event in stale_live
            ]
    except Exception as e:  # noqa: BLE001
        logger.exception("cron_auto_transition: failed to list stale live events: %s", e)
        return {"status": "partial_error", **counters}

    for event_id, event_tenant_id, event_name in stale_snapshots:
        async with async_session_factory() as event_session:
            try:
                # 60-min silence guard: only end if no recent stock tx
                # Tighter silence query: filter by THIS event's id.
                # StockTransaction has an event_id column, so we can ask
                # precisely "was there any tx for THIS event in the last
                # 60 minutes?" — no need to lean on the one-live-per-tenant
                # invariant as a proxy.
                last_tx_stmt = (
                    select(func.max(StockTransaction.created_at))
                    .where(StockTransaction.tenant_id == event_tenant_id)
                    .where(StockTransaction.event_id == event_id)
                )
                last_tx = (await event_session.execute(last_tx_stmt)).scalar()

                if last_tx is not None and last_tx >= silence_threshold:
                    counters["skipped_silence"] += 1
                    logger.info(
                        "cron_auto_transition: NOT ending event=%s (%s) "
                        "— last tx at %s, within 60-min window",
                        event_id, event_name, last_tx,
                    )
                    continue

                service = EventService(db=event_session)
                await service.end_event(event_tenant_id, event_id)
                counters["completed"] += 1
                logger.info(
                    "cron_auto_transition: LIVE->COMPLETED event=%s (%s)",
                    event_id, event_name,
                )
            except Exception as e:  # noqa: BLE001
                # Scoped to event_session only (F-02) — see note above.
                await event_session.rollback()
                counters["errors"] += 1
                logger.warning(
                    "cron_auto_transition: ending failed for event=%s: %s",
                    event_id, e,
                )

    # Final log if anything happened
    interesting = (counters["activated"] or counters["started"]
                   or counters["completed"] or counters["errors"])
    if interesting:
        logger.info("cron_auto_transition tick: %s", counters)

    return {"status": "ok", **counters}
