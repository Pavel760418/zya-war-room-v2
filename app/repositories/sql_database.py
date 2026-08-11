"""Low-level read-only Microsoft SQL Server access via pymssql.

Rules:
- SELECT only (enforced by allowing only statements that start with SELECT/WITH/EXEC sp_help... no — only SELECT/WITH)
- Parameterized queries only (no string concatenation of user input into SQL)
- Never log DATABASE_URL or passwords
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from typing import Any, Iterable, Iterator, Mapping, Optional, Sequence, Union

import pandas as pd

from app.core.settings import DatabaseSettings, parse_database_url, redact_error

# Statements we refuse even if somehow passed in.
_FORBIDDEN_PREFIXES = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "truncate",
    "merge",
    "exec",
    "execute",
    "grant",
    "revoke",
    "backup",
    "restore",
    "kill",
    "reconfigure",
)


@dataclass
class SqlStatus:
    ok: bool
    message: str
    server: Optional[str] = None
    database: Optional[str] = None
    engine: Optional[str] = None
    last_success_at: Optional[str] = None
    error: Optional[str] = None


@dataclass
class SqlDatabase:
    """Connection helper. Instantiation does not connect."""

    settings: DatabaseSettings
    connect_timeout: int = 8
    _last_success_at: Optional[datetime] = field(default=None, init=False, repr=False)

    @classmethod
    def from_env(cls, connect_timeout: int = 8) -> Optional["SqlDatabase"]:
        cfg = parse_database_url()
        if cfg is None:
            return None
        return cls(settings=cfg, connect_timeout=connect_timeout)

    def _connect_kwargs(self, database: Optional[str] = None) -> dict[str, Any]:
        return {
            "server": self.settings.host,
            "port": self.settings.port,
            "user": self.settings.user,
            "password": self.settings.password,
            "database": database if database is not None else self.settings.database,
            "login_timeout": self.connect_timeout,
            "timeout": self.connect_timeout,
            "as_dict": False,
        }

    @contextmanager
    def connection(self, database: Optional[str] = None) -> Iterator[Any]:
        import time

        import pymssql

        attempts = max(1, int(os.environ.get("WARROOM_SQL_RETRIES", "4")))
        delay = float(os.environ.get("WARROOM_SQL_RETRY_DELAY", "0.6"))
        last_exc: Optional[BaseException] = None
        for attempt in range(1, attempts + 1):
            try:
                conn = pymssql.connect(**self._connect_kwargs(database=database))
                try:
                    yield conn
                    self._last_success_at = datetime.now(timezone.utc)
                finally:
                    conn.close()
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt >= attempts:
                    break
                time.sleep(min(delay * (2 ** (attempt - 1)), 8.0))
        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _assert_readonly(sql: str) -> str:
        cleaned = sql.strip().lstrip("(").strip()
        # Allow leading comments
        while cleaned.startswith("--") or cleaned.startswith("/*"):
            if cleaned.startswith("--"):
                cleaned = cleaned.split("\n", 1)[-1].strip()
            else:
                end = cleaned.find("*/")
                cleaned = cleaned[end + 2 :].strip() if end >= 0 else cleaned
        head = cleaned.split(None, 1)[0].lower() if cleaned else ""
        if head not in ("select", "with"):
            raise ValueError("Только SELECT/WITH разрешены в War Room SQL-слое.")
        lowered = cleaned.lower()
        for bad in _FORBIDDEN_PREFIXES:
            # crude guard against stacked statements
            if f";{bad}" in lowered.replace(" ", ""):
                raise ValueError("Обнаружена запрещённая SQL-команда.")
        return sql

    def ping(self) -> SqlStatus:
        cfg = self.settings
        if not cfg.database:
            return SqlStatus(
                ok=False,
                message="DATABASE_URL без имени базы — укажите /DatabaseName",
                server=cfg.host,
                database=None,
                error="missing_database",
            )
        try:
            with self.connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT @@VERSION AS v, DB_NAME() AS db")
                row = cur.fetchone()
                version = str(row[0])[:120] if row else "Microsoft SQL Server"
                dbname = str(row[1]) if row and row[1] else cfg.database
            return SqlStatus(
                ok=True,
                message="SQL подключение активно",
                server=cfg.host,
                database=dbname,
                engine=version,
                last_success_at=self._last_success_at.isoformat() if self._last_success_at else None,
            )
        except Exception as exc:  # noqa: BLE001 — soft degrade
            return SqlStatus(
                ok=False,
                message="SQL недоступен",
                server=cfg.host,
                database=cfg.database or None,
                error=redact_error(exc),
            )

    @staticmethod
    def _bind_params(params: Optional[Union[Sequence[Any], Mapping[str, Any]]]) -> Any:
        if params is None:
            return None
        if isinstance(params, Mapping):
            return dict(params)
        return tuple(params)

    def fetch_all(
        self, sql: str, params: Optional[Union[Sequence[Any], Mapping[str, Any]]] = None
    ) -> list[tuple]:
        self._assert_readonly(sql)
        with self.connection() as conn:
            cur = conn.cursor()
            bind = self._bind_params(params)
            if bind is not None:
                cur.execute(sql, bind)
            else:
                cur.execute(sql)
            rows = cur.fetchall() or []
            self._last_success_at = datetime.now(timezone.utc)
            return list(rows)

    def fetch_df(
        self,
        sql: str,
        params: Optional[Union[Sequence[Any], Mapping[str, Any]]] = None,
        columns: Optional[Iterable[str]] = None,
    ) -> pd.DataFrame:
        self._assert_readonly(sql)
        with self.connection() as conn:
            cur = conn.cursor()
            bind = self._bind_params(params)
            if bind is not None:
                cur.execute(sql, bind)
            else:
                cur.execute(sql)
            rows = cur.fetchall() or []
            if columns is None:
                columns = [d[0] for d in (cur.description or [])]
            self._last_success_at = datetime.now(timezone.utc)
            return pd.DataFrame.from_records(rows, columns=list(columns))

    def list_databases(self) -> pd.DataFrame:
        sql = """
        SELECT name, database_id, state_desc, recovery_model_desc
        FROM sys.databases
        WHERE state_desc = 'ONLINE'
          AND name NOT IN ('master', 'tempdb', 'model', 'msdb')
        ORDER BY name
        """
        # Connect to master for catalog
        with self.connection(database="master") as conn:
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall() or []
            cols = [d[0] for d in (cur.description or [])]
            return pd.DataFrame.from_records(rows, columns=cols)

    def list_schemas(self) -> pd.DataFrame:
        sql = """
        SELECT s.name AS schema_name, s.schema_id
        FROM sys.schemas AS s
        WHERE s.name NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest', 'db_owner', 'db_accessadmin',
                             'db_securityadmin', 'db_ddladmin', 'db_backupoperator',
                             'db_datareader', 'db_datawriter', 'db_denydatareader', 'db_denydatawriter')
        ORDER BY s.name
        """
        return self.fetch_df(sql)

    def list_tables_and_views(self) -> pd.DataFrame:
        sql = """
        SELECT
            TABLE_SCHEMA AS schema_name,
            TABLE_NAME AS object_name,
            TABLE_TYPE AS object_type
        FROM INFORMATION_SCHEMA.TABLES
        ORDER BY TABLE_SCHEMA, TABLE_TYPE, TABLE_NAME
        """
        return self.fetch_df(sql)

    def list_columns(self, schema: str, table: str) -> pd.DataFrame:
        sql = """
        SELECT
            COLUMN_NAME AS column_name,
            DATA_TYPE AS data_type,
            IS_NULLABLE AS is_nullable,
            CHARACTER_MAXIMUM_LENGTH AS max_length,
            NUMERIC_PRECISION AS numeric_precision,
            ORDINAL_POSITION AS ordinal_position
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
        """
        return self.fetch_df(sql, params=(schema, table))

    def probe_select_permission(self) -> tuple[bool, str]:
        """Check that SELECT works; does not attempt writes."""
        try:
            self.fetch_all("SELECT 1 AS ok")
            return True, "SELECT разрешён"
        except Exception as exc:  # noqa: BLE001
            return False, redact_error(exc)

    @property
    def last_success_iso(self) -> Optional[str]:
        if self._last_success_at is None:
            return None
        return self._last_success_at.isoformat()
