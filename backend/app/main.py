"""FastAPI application factory with health check endpoint at /api/v1/health."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
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
