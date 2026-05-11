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
from app.modules.events.models import Event

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
                Event.status == "live",
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
    from app.modules.events.models import Event as _Event
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
                Event.status == "live",
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

