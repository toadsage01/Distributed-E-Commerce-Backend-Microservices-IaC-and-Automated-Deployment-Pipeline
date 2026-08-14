"""FastAPI app for the User Service."""
from __future__ import annotations

import logging

from fastapi import FastAPI

from .database import init_db
from .routers import auth, users

log = logging.getLogger("user-service")


def create_app() -> FastAPI:
    app = FastAPI(
        title="User Service",
        description="Auth + user profile management for the e-commerce platform.",
        version="1.0.0",
    )
    app.include_router(auth.router)
    app.include_router(users.router)

    @app.on_event("startup")
    def _startup() -> None:
        init_db()
        log.info("User service started — DB schema initialised")

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "service": "user-service"}

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
