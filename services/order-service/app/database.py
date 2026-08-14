"""DB engine + session factory for the Order Service."""
from __future__ import annotations

from services.shared.database import Base, make_engine, make_session_factory

from .config import settings

engine = make_engine(settings.db_schema)
SessionLocal = make_session_factory(engine)


def init_db() -> None:
    from sqlalchemy import text
    with engine.connect() as conn:
        if not str(engine.url).startswith("sqlite"):
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {settings.db_schema}"))
            conn.commit()
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
