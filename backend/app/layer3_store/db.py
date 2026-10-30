"""Engine/session factory. DATABASE_URL: postgresql+psycopg://... or sqlite:///path."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

DEFAULT_URL = "sqlite:///./artifacts/clinical.db"


def database_url() -> str:
    return os.environ.get("DATABASE_URL") or DEFAULT_URL


def make_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, future=True, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite enforces FKs only when asked to
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return engine


def session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def migrate(url: str | None = None) -> None:
    """Apply Alembic migrations to head (also used for SQLite in tests/dev)."""
    from alembic import command
    from alembic.config import Config
    root = Path(__file__).resolve().parents[3]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "backend" / "app" / "layer3_store" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url or database_url())
    command.upgrade(cfg, "head")
