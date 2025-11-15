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


_ENGINES: dict[str, Engine] = {}
_SESSION_FACTORIES: dict[str, Callable[[], Session]] = {}


def get_engine(database_url: str = DATABASE_URL) -> Engine:
    engine = _ENGINES.get(database_url)
    if engine is None:
        engine = create_sqlalchemy_engine(database_url)
        _ENGINES[database_url] = engine
    return engine


def get_session_factory(database_url: str = DATABASE_URL):
    factory = _SESSION_FACTORIES.get(database_url)
    if factory is None:
        engine = get_engine(database_url)
        factory = scoped_session(
            sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
        )
        _SESSION_FACTORIES[database_url] = factory
    return factory

