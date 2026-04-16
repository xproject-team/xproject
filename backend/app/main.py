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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
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
    from app.modules.inventory.router import router as inventory_router
    from app.modules.pos.router import router as pos_router
    from app.modules.alerts.router import router as alerts_router
    from app.modules.warehouse.router import router as warehouse_router
    from app.modules.predictions.router import router as predictions_router
    from app.modules.anomaly.router import router as anomaly_router
    from app.modules.reports.router import router as reports_router
    from app.modules.chat.router import router as chat_router
    from app.realtime.websocket import router as ws_router

    prefix = "/api/v1"
    app.include_router(auth_router, prefix=f"{prefix}/auth", tags=["auth"])
    app.include_router(events_router, prefix=f"{prefix}/events", tags=["events"])
    app.include_router(venues_router, prefix=f"{prefix}/venues", tags=["venues"])
    app.include_router(bars_router, prefix=f"{prefix}/bars", tags=["bars"])
    app.include_router(products_router, prefix=f"{prefix}/products", tags=["products"])
    app.include_router(event_products_router, prefix=f"{prefix}/event-products", tags=["event-products"])
    app.include_router(bar_stock_router, prefix=f"{prefix}/bar-stock", tags=["bar-stock"])
    app.include_router(inventory_router, prefix=f"{prefix}/inventory", tags=["inventory"])
    app.include_router(pos_router, prefix=f"{prefix}/pos", tags=["pos"])
    app.include_router(alerts_router, prefix=f"{prefix}/alerts", tags=["alerts"])
    app.include_router(warehouse_router, prefix=f"{prefix}/warehouse", tags=["warehouse"])
    app.include_router(predictions_router, prefix=f"{prefix}/predictions", tags=["predictions"])
    app.include_router(anomaly_router, prefix=f"{prefix}/anomaly", tags=["anomaly"])
    app.include_router(reports_router, prefix=f"{prefix}/reports", tags=["reports"])
    app.include_router(chat_router, prefix=f"{prefix}/chat", tags=["chat"])
    app.include_router(ws_router, prefix=f"{prefix}/ws", tags=["websocket"])

    @app.get("/api/v1/health", tags=["health"])
    async def health_check():
        """Service liveness probe."""
        return {"status": "ok", "service": "xproject-api", "version": "0.1.0"}

    return app


app = create_app()
