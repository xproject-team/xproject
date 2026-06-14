"""FastAPI application factory with health check endpoint at /api/v1/health."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.realtime.publisher import start_subscriber
from app.realtime.websocket import manager as _ws_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the Redis pub/sub subscriber as a background task.

    On shutdown, the task is cancelled cleanly. The subscriber survives
    Redis reconnections internally (redis-py auto-reconnects).
    """
    sub_task = asyncio.create_task(start_subscriber(_ws_manager))
    try:
        yield
    finally:
        sub_task.cancel()
        try:
            await sub_task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    # Configure logging FIRST — anything that imports/runs after this
    # will use our settings (level, format, library suppression).
    from app.core.logging_config import configure_logging
    configure_logging()

    app = FastAPI(
        lifespan=lifespan,
        title="XProject API",
        description="AI-powered operational intelligence platform for hospitality events",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )

    # CORS — allow local dev + production frontend domain. Set
    # CORS_EXTRA_ORIGINS env var (comma-separated) to add more.
    import os
    cors_origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "https://vera-event.com",
        "https://www.vera-event.com",
    ]
    extra = os.getenv("CORS_EXTRA_ORIGINS", "").strip()
    if extra:
        cors_origins.extend([o.strip() for o in extra.split(",") if o.strip()])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register module routers
    from app.modules.auth.router import router as auth_router
    from app.modules.events.router import router as events_router
    from app.modules.venues.router import router as venues_router
    from app.modules.bars.router import router as bars_router
    from app.modules.products.router import router as products_router
    from app.modules.event_products.router import router as event_products_router
    from app.modules.bar_stock.router import router as bar_stock_router
    from app.modules.recipes.router import router as recipes_router
    from app.modules.stock_transactions.router import router as stock_transactions_router
    from app.modules.inventory.router import router as inventory_router
    from app.modules.pos.router import router as pos_router
    from app.modules.pos.proposals_router import router as pos_proposals_router
    from app.modules.alerts.router import router as alerts_router
    from app.modules.warehouse.router import router as warehouse_router
    from app.modules.predictions.router import router as predictions_router
    from app.modules.anomaly.router import router as anomaly_router
    from app.modules.reports.router import router as reports_router
    from app.modules.chat.router import router as chat_router
    from app.modules.event_storage.router import router as event_storage_router
    from app.realtime.websocket import router as ws_router

    prefix = "/api/v1"
    app.include_router(auth_router, prefix=f"{prefix}/auth", tags=["auth"])
    app.include_router(events_router, prefix=f"{prefix}/events", tags=["events"])
    app.include_router(venues_router, prefix=f"{prefix}/venues", tags=["venues"])
    app.include_router(bars_router, prefix=f"{prefix}/bars", tags=["bars"])
    app.include_router(products_router, prefix=f"{prefix}/products", tags=["products"])
    app.include_router(event_products_router, prefix=f"{prefix}/event-products", tags=["event-products"])
    app.include_router(bar_stock_router, prefix=f"{prefix}/bar-stock", tags=["bar-stock"])
    app.include_router(recipes_router, prefix=f"{prefix}/recipes", tags=["recipes"])
    app.include_router(stock_transactions_router, prefix=f"{prefix}/stock-transactions", tags=["stock-transactions"])
    app.include_router(inventory_router, prefix=f"{prefix}/inventory", tags=["inventory"])
    app.include_router(pos_router, prefix=f"{prefix}/pos", tags=["pos"])
    app.include_router(pos_proposals_router, prefix=f"{prefix}/pos", tags=["pos:proposals"])
    app.include_router(alerts_router, prefix=f"{prefix}/alerts", tags=["alerts"])
    app.include_router(warehouse_router, prefix=f"{prefix}/warehouse", tags=["warehouse"])
    app.include_router(predictions_router, prefix=f"{prefix}/predictions", tags=["predictions"])
    app.include_router(anomaly_router, prefix=f"{prefix}/anomaly", tags=["anomaly"])
    app.include_router(reports_router, prefix=f"{prefix}/reports", tags=["reports"])
    app.include_router(chat_router, prefix=f"{prefix}/chat", tags=["chat"])
    app.include_router(event_storage_router, prefix=f"{prefix}/event-storage", tags=["event-storage"])
    app.include_router(ws_router, prefix=f"{prefix}/ws", tags=["websocket"])

    @app.get("/api/v1/health", tags=["health"])
    async def health_check():
        """Service liveness probe."""
        return {"status": "ok", "service": "xproject-api", "version": "0.1.0"}

    @app.get("/api/v1/health/deep", tags=["health"])
    async def health_deep():
        """Deep health probe — checks every critical subsystem.

        On Sundance day, hit this endpoint to verify the box is fully alive.
        Returns 200 always (so monitoring tools can parse it), but each
        component reports its own status independently. Owner can see at
        a glance which subsystem broke.

        Components checked:
        - postgres   : can execute a SELECT 1
        - redis      : can PING the broker
        - minio      : can list buckets (chat attachments need this)
        - live_event : is there an event in LIVE status right now
        """
        import time
        from sqlalchemy import select, func
        from app.core.database import AsyncSessionLocal
        from app.modules.events.models import Event, EventStatus

        components = {}

        # ── postgres ───────────────────────────────────────────────────
        t0 = time.perf_counter()
        try:
            async with AsyncSessionLocal() as session:
                r = (await session.execute(select(func.now()))).scalar_one()
            components["postgres"] = {
                "status": "ok",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "server_time": r.isoformat() if r else None,
            }
        except Exception as e:  # noqa: BLE001
            components["postgres"] = {"status": "error", "error": str(e)[:200]}

        # ── redis ──────────────────────────────────────────────────────
        t0 = time.perf_counter()
        try:
            from app.core.redis_client import get_redis
            r = await get_redis()
            pong = await r.ping()
            components["redis"] = {
                "status": "ok" if pong else "error",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        except Exception as e:  # noqa: BLE001
            components["redis"] = {"status": "error", "error": str(e)[:200]}

        # ── minio ──────────────────────────────────────────────────────
        t0 = time.perf_counter()
        try:
            from app.core.storage import _internal_client
            _internal_client.list_buckets()
            components["minio"] = {
                "status": "ok",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        except Exception as e:  # noqa: BLE001
            components["minio"] = {"status": "error", "error": str(e)[:200]}

        # ── live event ─────────────────────────────────────────────────
        try:
            async with AsyncSessionLocal() as session:
                row = (await session.execute(
                    select(Event.id, Event.name, Event.tenant_id)
                    .where(Event.status == EventStatus.LIVE)
                )).first()
            if row:
                components["live_event"] = {
                    "status": "ok",
                    "event_id": str(row[0]),
                    "event_name": row[1],
                    "tenant_id": str(row[2]),
                }
            else:
                components["live_event"] = {
                    "status": "none",
                    "note": "no event currently in LIVE state",
                }
        except Exception as e:  # noqa: BLE001
            components["live_event"] = {"status": "error", "error": str(e)[:200]}

        overall = "ok" if all(
            c.get("status") in ("ok", "none") for c in components.values()
        ) else "degraded"

        return {
            "status": overall,
            "service": "xproject-api",
            "version": "0.1.0",
            "components": components,
        }

    return app


app = create_app()
