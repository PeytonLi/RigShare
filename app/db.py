from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings

def _database_url() -> str:
    url = get_settings().database_url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


_settings_url = _database_url()
_connect_args: dict[str, object] = {}
_engine_kwargs: dict[str, object] = {}
if _settings_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
    _engine_kwargs["poolclass"] = StaticPool

engine = create_engine(_settings_url, connect_args=_connect_args, **_engine_kwargs)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create missing tables, then backfill columns added after a table shipped.

    create_all never alters an existing table, so any column added later is
    absent in an already-deployed database and every SELECT on that model
    500s. This used to be a hand-written ALTER list, which is how
    items.lender_chat_id got missed and took out the dashboard. Reconciling
    against the metadata instead means adding a column to models.py is enough.
    """
    from sqlalchemy import inspect, text

    from app.models import Base

    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                # NOT NULL needs a default to backfill; those only appear on
                # tables create_all just made, which already have them.
                if column.name in existing or not column.nullable:
                    continue
                ddl = column.type.compile(engine.dialect)
                conn.execute(
                    text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {ddl}")
                )
