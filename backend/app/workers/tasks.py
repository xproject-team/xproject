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


async def generate_report(ctx: dict, event_id: str) -> dict:
    """Generate the post-event report including AI narrative and PDF.

    Stub: real implementation ships with the reports module.
    """
    return {"event_id": event_id, "status": "ok"}