"""Background task definitions — each async function is an arq task.

Enqueue via: await redis.enqueue_job("run_predictions", event_id=42)
All tasks receive the arq context dict as their first positional argument.
"""


async def run_predictions(ctx: dict, event_id: int) -> dict:
    """Generate ML demand predictions for all SKUs in the given event.

    Enqueued periodically by the scheduler and on-demand via the API.
    """
    # TODO: call PredictionService
    return {"event_id": event_id, "status": "ok", "predictions_generated": 0}


async def evaluate_alerts(ctx: dict, event_id: int) -> dict:
    """Evaluate alert rules against current metrics for the given event.

    Enqueued after each POS transaction batch or on a fixed interval.
    """
    # TODO: call alerts.engine.evaluate_rules and persist triggered alerts
    return {"event_id": event_id, "status": "ok", "alerts_fired": 0}


async def generate_report(ctx: dict, event_id: int) -> dict:
    """Generate the post-event report including AI narrative and PDF.

    Enqueued automatically when an event transitions to 'ended' status.
    """
    # TODO: call ReportService
    return {"event_id": event_id, "status": "ok"}
