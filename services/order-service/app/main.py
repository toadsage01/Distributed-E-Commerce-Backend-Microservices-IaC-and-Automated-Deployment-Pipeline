"""FastAPI app for the Order Service."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .clients import product_client, user_client
from .database import init_db
from .routers import orders

log = logging.getLogger("order-service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("Order service started — DB schema initialised")
    yield
    # Close httpx clients on shutdown
    await user_client.close()
    await product_client.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Order Service",
        description="Order flow + inter-service orchestration.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.include_router(orders.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "service": "order-service"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    from .config import settings

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.env == "local",
    )
