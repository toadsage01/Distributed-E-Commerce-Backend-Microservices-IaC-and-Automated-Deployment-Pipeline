"""DB engine + session factory for the User Service."""
from __future__ import annotations

from services.shared.database import Base, make_engine, make_session_factory

from .config import settings

engine = make_engine(settings.db_schema)
SessionLocal = make_session_factory(engine)


def init_db() -> None:
    """Create schema + tables. Called on app startup.

    In a real prod system you'd use Alembic migrations; for resume-scope
    this is fine and avoids the migration toolchain overhead.
    """
    from sqlalchemy import text
    with engine.connect() as conn:
        # SQLite (tests) doesn't support CREATE SCHEMA — skip it.
        if not str(engine.url).startswith("sqlite"):
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {settings.db_schema}"))
            conn.commit()
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency that yields a DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
