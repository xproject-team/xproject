"""arq worker settings and scheduled job configuration.

Start the worker with:
    arq app.workers.scheduler.WorkerSettings
"""
from arq.connections import RedisSettings

from app.core.config import settings
from app.workers.tasks import evaluate_alerts, generate_report, run_predictions


class WorkerSettings:
    """arq worker configuration — registers functions and cron jobs."""

    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions = [run_predictions, evaluate_alerts, generate_report]
    cron_jobs = []  # add arq.cron() instances here for time-based scheduling
