"""Service DB for WAR_ROM analytics metadata (SQLite by default).

Never writes to SQL Server 1C (retail). Migrations are applied here only.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "var" / "db" / "warroom_service.sqlite"
SCHEMA_SQL = Path(__file__).resolve().parent / "migrations" / "001_analytics_schema.sql"


def service_db_url() -> str:
    raw = (os.getenv("WARROM_SERVICE_DATABASE_URL") or "").strip()
    if raw:
        return raw
    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DEFAULT_DB_PATH}"


def get_engine() -> Engine:
    url = service_db_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, connect_args=connect_args)


def apply_migrations(engine: Engine | None = None) -> None:
    eng = engine or get_engine()
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    with eng.begin() as conn:
        # SQLite executes multiple statements via executescript on raw connection
        if eng.dialect.name == "sqlite":
            raw = conn.connection.dbapi_connection
            raw.executescript(sql)
        else:
            for stmt in sql.split(";"):
                s = stmt.strip()
                if s:
                    conn.execute(text(s))


SessionLocal = sessionmaker(autocommit=False, autoflush=False, future=True)


def session_factory(engine: Engine | None = None) -> sessionmaker:
    eng = engine or get_engine()
    return sessionmaker(bind=eng, autocommit=False, autoflush=False, future=True)
