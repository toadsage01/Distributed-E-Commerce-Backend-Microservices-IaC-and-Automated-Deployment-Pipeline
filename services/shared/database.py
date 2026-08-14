"""SQLAlchemy session + declarative base.

One RDS Postgres instance is shared by all services, but each service uses
its OWN schema (e.g. `users`, `products`, `orders`). That keeps the
"database per service" pattern visible without paying for three RDS
instances — see ARCHITECTURE.md for the explicit trade-off note.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from .config import get_platform_settings


Base = declarative_base()


def make_engine(schema_name: str) -> Engine:
    """Build a SQLAlchemy engine pinned to a specific Postgres schema.

    Every service calls this with its own schema name. The `search_path`
    option means ORM models don't need to specify the schema on every
    table — they just use plain table names and Postgres resolves them.

    SQLite (used in tests) ignores the schema argument — tests run with
    a fresh DB every time so schema isolation isn't needed.
    """
    settings = get_platform_settings()
    url = settings.database_url
    is_sqlite = url.startswith("sqlite")

    if is_sqlite:
        return create_engine(url, connect_args={"check_same_thread": False})

    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        connect_args={"options": f"-csearch_path={schema_name}"},
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Context-managed DB session with auto-commit/rollback.

    Usage:
        with session_scope(SessionLocal) as db:
            db.add(...)
    """
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
