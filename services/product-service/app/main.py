"""FastAPI app for the Product Service."""
from __future__ import annotations

import logging

from fastapi import FastAPI

from .database import init_db
from .routers import products

log = logging.getLogger("product-service")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Product Service",
        description="Catalog management for the e-commerce platform.",
        version="1.0.0",
    )
    app.include_router(products.router)

    @app.on_event("startup")
    def _startup() -> None:
        init_db()
        log.info("Product service started — DB schema initialised")

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "service": "product-service"}

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
