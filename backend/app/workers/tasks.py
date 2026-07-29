"""Background task definitions — each async function is an arq task.

Tasks are enqueued by the cron in scheduler.py or on-demand by services.
Each task receives the arq context dict as its first positional argument.

Critical design principle: task bodies NEVER raise out to arq. We catch
everything, log it, and return a structured result. arq's retry semantics
plus our dedup logic make retries safe, but we want observability, not
silent failures or infinite retry loops.
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
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
    return {"event_id": event_id, "status": "ok", "predictions_generated": 0}


# ─── Nowcast auto-retrain (Phase F) ────────────────────────────────────────────


async def retrain_predictor(ctx: dict, tenant_id: str) -> dict:
    """Retrain the "ML Predicted" nowcast's training set from this
    tenant's COMPLETED events (see predictions/nowcast/retrain.py).

    Enqueued by EventService.end_event() right after an event's
    LIVE -> COMPLETED transition commits (app/modules/events/service.py).
    Idempotent — retrain_from_completed_events upserts by event_id, so
    re-running (retries, manual re-enqueue) never double-counts an event.

    Never raises out to arq: any failure here (bad data, disk issue) is
    logged and returned as a structured error. The predictor singleton
    keeps serving its last-known-good parquet on failure — a bad
    retrain must never take the /revenue-forecast endpoint down, and
    must never roll back the event completion that triggered it (that
    transaction has already committed by the time this task runs).
    """
    try:
        tenant_uuid = UUID(tenant_id)
    except (TypeError, ValueError) as e:
        logger.warning("retrain_predictor: bad tenant_id %s: %s", tenant_id, e)
        return {"status": "error", "reason": "invalid_uuid"}

    from app.modules.predictions.nowcast.retrain import retrain_from_completed_events

    async with async_session_factory() as session:
        try:
            return await retrain_from_completed_events(session, tenant_uuid)
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
            return {
                "status": "ok",
                "event_id": event_id,
                "reports_generated": len(reports),
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
                select(DeliveryInvoice)
                .where(
                    DeliveryInvoice.status == "PAUSED",
                    DeliveryInvoice.scan_started_at < cutoff,
                )
            )
            eligible = (await session.execute(stmt)).scalars().all()
        except Exception as e:  # noqa: BLE001
            logger.exception("cron_close_paused: list failed: %s", e)
            return {"status": "error", "eligible": 0}

        if not eligible:
            return {"status": "ok", "eligible": 0, "closed": 0, "failed": 0}

        for invoice in eligible:
            try:
                # close_scan handles its own transitions + commit. Pass
                # closed_by=None to mark this as a system action.
                svc = InvoiceService(session)
                await svc.close_scan(
                    tenant_id=invoice.tenant_id,
                    invoice_id=invoice.id,
                    closed_by=None,
                )
                closed += 1
            except InvalidInvoiceTransitionError:
                # Race: invoice changed state between our SELECT and the
                # close call. Safe to skip; next tick re-evaluates.
                pass
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "cron_close_paused: failed to close invoice=%s: %s",
                    invoice.id, e,
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
        return {
            "status":           result.status,
            "orders_seen":      result.orders_seen,
            "orders_ingested":  result.orders_ingested,
            "lines_ingested":   result.lines_ingested,
            "lines_replayed":   result.lines_replayed,
            "lines_skipped":    result.lines_skipped,
            "lines_errors":     result.lines_errors,
            "error_msg":        result.error_msg or "",
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
    # Short-circuit if Slesh isn't configured (developer envs, CI, etc.)
    if not settings.slesh_api_token:
        logger.debug("cron_poll_slesh: skipped (SLESH_API_TOKEN not configured)")
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
    if not settings.slesh_api_token:
        logger.debug("cron_sync_bars_from_slesh: skipped (no SLESH_API_TOKEN)")
        return {"status": "skipped", "reason": "no_token"}

    # Import inside function to keep module import-time cheap and
    # avoid any module-load-order surprises with the Slesh adapter.
    from app.modules.pos.adapters.slesh import SleshAdapter
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

        async with SleshAdapter(
            token=settings.slesh_api_token,
            brand_id=settings.slesh_brand_id,
            base_url=settings.slesh_base_url,
            request_timeout=settings.slesh_request_timeout,
            rate_limit_rps=settings.slesh_rate_limit_rps,
            max_retries=settings.slesh_max_retries,
        ) as adapter:
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
      - Each event\'s transition is wrapped in its own try/except so
        one failure doesn't poison the whole tick.
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

    async with async_session_factory() as session:
        # ── Responsibility 1+2: promote DRAFT/ACTIVE -> LIVE ─────────
        try:
            stmt = select(Event).where(
                and_(
                    Event.status.in_([EventStatus.DRAFT, EventStatus.ACTIVE]),
                    Event.scheduled_at <= now,
                )
            )
            due_events = (await session.execute(stmt)).scalars().all()
        except Exception as e:  # noqa: BLE001
            logger.exception("cron_auto_transition: failed to list due events: %s", e)
            return {"status": "error", **counters}

        for event in due_events:
            # Snapshot identifiers BEFORE any service call. After a
            # session.rollback() the ORM expires loaded attributes; the
            # subsequent log statement would trigger a lazy reload from
            # outside an async context and explode with MissingGreenlet,
            # masking the original (informative) exception.
            event_id_str = str(event.id)
            event_name = event.name
            event_tenant_id = event.tenant_id
            event_status_snapshot = event.status

            try:
                # Build a service for this tenant. Reuse the same session
                # so cron writes commit through one connection per tick.
                service = EventService(db=session)

                if event_status_snapshot == EventStatus.DRAFT:
                    await service.activate_event(event_tenant_id, event.id)
                    counters["activated"] += 1
                    # Now ACTIVE — chain into start
                    await service.start_event(event_tenant_id, event.id)
                    counters["started"] += 1
                    logger.info(
                        "cron_auto_transition: DRAFT->LIVE event=%s (%s)",
                        event_id_str, event_name,
                    )
                elif event_status_snapshot == EventStatus.ACTIVE:
                    await service.start_event(event_tenant_id, event.id)
                    counters["started"] += 1
                    logger.info(
                        "cron_auto_transition: ACTIVE->LIVE event=%s (%s)",
                        event_id_str, event_name,
                    )
            except Exception as e:  # noqa: BLE001
                # Most likely cause: LiveEventConflictError (another live
                # event in this tenant). Log and continue — owner gets
                # notified via the existing 409 flow when they retry manually.
                await session.rollback()
                counters["errors"] += 1
                logger.warning(
                    "cron_auto_transition: promotion failed for event=%s (%s): %s",
                    event_id_str, event_name, e,
                )

        # ── Responsibility 3: end stale LIVE events ──────────────────
        try:
            stmt = select(Event).where(
                and_(
                    Event.status == EventStatus.LIVE,
                    Event.scheduled_end_at <= now,
                )
            )
            stale_live = (await session.execute(stmt)).scalars().all()
        except Exception as e:  # noqa: BLE001
            logger.exception("cron_auto_transition: failed to list stale live events: %s", e)
            return {"status": "partial_error", **counters}

        for event in stale_live:
            try:
                # 60-min silence guard: only end if no recent stock tx
                # Tighter silence query: filter by THIS event's id.
                # StockTransaction has an event_id column, so we can ask
                # precisely "was there any tx for THIS event in the last
                # 60 minutes?" — no need to lean on the one-live-per-tenant
                # invariant as a proxy.
                last_tx_stmt = (
                    select(func.max(StockTransaction.created_at))
                    .where(StockTransaction.tenant_id == event.tenant_id)
                    .where(StockTransaction.event_id == event.id)
                )
                last_tx = (await session.execute(last_tx_stmt)).scalar()

                if last_tx is not None and last_tx >= silence_threshold:
                    counters["skipped_silence"] += 1
                    logger.info(
                        "cron_auto_transition: NOT ending event=%s (%s) "
                        "— last tx at %s, within 60-min window",
                        event.id, event.name, last_tx,
                    )
                    continue

                service = EventService(db=session)
                await service.end_event(event.tenant_id, event.id)
                counters["completed"] += 1
                logger.info(
                    "cron_auto_transition: LIVE->COMPLETED event=%s (%s)",
                    event.id, event.name,
                )
            except Exception as e:  # noqa: BLE001
                await session.rollback()
                counters["errors"] += 1
                logger.warning(
                    "cron_auto_transition: ending failed for event=%s: %s",
                    event.id, e,
                )

    # Final log if anything happened
    interesting = (counters["activated"] or counters["started"]
                   or counters["completed"] or counters["errors"])
    if interesting:
        logger.info("cron_auto_transition tick: %s", counters)

    return {"status": "ok", **counters}
