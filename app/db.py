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
    from sqlalchemy import text

    from app.models import Base

    Base.metadata.create_all(bind=engine)
    extras = (
        "ALTER TABLE loans ADD COLUMN IF NOT EXISTS band_room_id VARCHAR",
        "ALTER TABLE loans ADD COLUMN IF NOT EXISTS sandbox_id VARCHAR",
        "ALTER TABLE loans ADD COLUMN IF NOT EXISTS compare_metric INTEGER",
        "ALTER TABLE loans ADD COLUMN IF NOT EXISTS terac_opportunity_id VARCHAR",
        "ALTER TABLE items ADD COLUMN IF NOT EXISTS lender_chat_id VARCHAR",
    )
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            for stmt in extras:
                conn.execute(text(stmt))
