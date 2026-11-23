"""قاعدة البيانات: محرك واحد وجلسات لكل طلب."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """تاريخ ووقت بتوقيت UTC دائمًا، في PostgreSQL وSQLite على السواء."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def default_database_url() -> str:
    from marsad.core.paths import ensure_storage

    root = ensure_storage().root
    return f"sqlite:///{(root / 'marsad-dev.db').as_posix()}"


def init_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    from marsad.config import get_settings

    url = url or get_settings().database_url or default_database_url()
    kwargs = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _fk_on(dbapi_conn, _):  # فرض المفاتيح الأجنبية في SQLite، وتمكين SAVEPOINT
            dbapi_conn.isolation_level = None
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(_engine, "begin")
        def _begin(conn):
            conn.exec_driver_sql("BEGIN")
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    return _engine or init_engine()


def get_db() -> Iterator[Session]:
    if _SessionLocal is None:
        init_engine()
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate() -> None:
    """يطبّق الترحيلات حتى آخر إصدار. يُستدعى عند بدء كل خدمة."""
    from marsad.migrate import upgrade

    upgrade(get_engine())
