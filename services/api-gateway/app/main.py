"""FastAPI app for the API Gateway."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .routers import proxy
from .ratelimit import setup_rate_limiting

log = logging.getLogger("api-gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("API Gateway started — routing to %d downstream services", 3)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="API Gateway",
        description=(
            "Single entry point for the e-commerce platform. Verifies JWTs, "
            "enforces API-key + rate-limit, and routes to downstream services."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    # Wire slowapi rate limiter
    setup_rate_limiting(app)

    # Health + meta routes (these don't go through the proxy)
    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "service": "api-gateway"}

    # Everything else → proxy router
    app.include_router(proxy.router)

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
