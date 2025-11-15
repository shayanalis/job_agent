"""SQLAlchemy base configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker, scoped_session, Session
from sqlalchemy.pool import StaticPool

from config.settings import DATABASE_URL


class Base(DeclarativeBase):
    """Base class for all ORM models."""


def _prepare_sqlite_path(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return
    if not url.database:
        return
    Path(url.database).parent.mkdir(parents=True, exist_ok=True)


def create_sqlalchemy_engine(database_url: str = DATABASE_URL) -> Engine:
    """Create SQLAlchemy engine with sensible defaults for SQLite."""
    _prepare_sqlite_path(database_url)
    engine_kwargs = {}
    connect_args = {}

    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if database_url.endswith(":memory:") or database_url.endswith(":/memory:"):
            engine_kwargs["poolclass"] = StaticPool

    return create_engine(database_url, connect_args=connect_args, **engine_kwargs)


_ENGINE: Engine | None = None
_SESSION_FACTORY: Callable[[], Session] | None = None


def get_engine(database_url: str = DATABASE_URL) -> Engine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_sqlalchemy_engine(database_url)
    return _ENGINE


def get_session_factory(database_url: str = DATABASE_URL):
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        engine = get_engine(database_url)
        _SESSION_FACTORY = scoped_session(
            sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
        )
    return _SESSION_FACTORY

