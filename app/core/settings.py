"""Runtime settings for War Room (secrets only via environment / EnvironmentFile).

Never put passwords or connection strings in source code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

# Preferred secret locations (first existing wins). Never commit these files.
_SECRET_CANDIDATES = (
    Path.home() / ".config" / "warroom" / "warroom.env",
    Path("/etc/warroom.env"),
    Path(__file__).resolve().parents[2] / ".env",
)


def _load_secret_files() -> Optional[Path]:
    for path in _SECRET_CANDIDATES:
        if path.is_file():
            load_dotenv(path, override=False)
            return path
    # Also allow process env already injected by systemd EnvironmentFile.
    load_dotenv(override=False)
    return None


_load_secret_files()


@dataclass(frozen=True)
class DatabaseSettings:
    """Parsed DATABASE_URL for pymssql (mssql+pymssql://user:pass@host:port/db)."""

    url: str
    host: str
    port: int
    user: str
    password: str
    database: str
    secrets_file: Optional[str] = None


@dataclass(frozen=True)
class AppSettings:
    data_source_default: str  # sql | excel | demo
    sql_connect_timeout: int
    database_url: Optional[str]
    secrets_file: Optional[str]


def get_app_settings() -> AppSettings:
    secrets = _load_secret_files()
    return AppSettings(
        data_source_default=os.getenv("WARROOM_DATA_SOURCE", "sql").strip().lower() or "sql",
        sql_connect_timeout=int(os.getenv("WARROOM_SQL_TIMEOUT", "8")),
        database_url=os.getenv("DATABASE_URL") or None,
        secrets_file=str(secrets) if secrets else None,
    )


def parse_database_url(url: Optional[str] = None) -> Optional[DatabaseSettings]:
    """Parse DATABASE_URL. Returns None if missing/empty. Does not log secrets."""
    settings = get_app_settings()
    raw = (url or settings.database_url or "").strip()
    if not raw:
        return None

    # Accept both mssql+pymssql:// and plain mssql://
    normalized = raw.replace("mssql+pymssql://", "mssql://", 1)
    parsed = urlparse(normalized)
    if parsed.scheme not in ("mssql", "mssql+pymssql"):
        # Also accept generic form host already in netloc
        if "://" not in raw:
            return None

    host = parsed.hostname or ""
    port = int(parsed.port or 1433)
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    database = (parsed.path or "").lstrip("/") or ""

    if not host or not user:
        return None

    return DatabaseSettings(
        url=raw,
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        secrets_file=settings.secrets_file,
    )


def redact_error(exc: BaseException) -> str:
    """Human-readable error without connection string / password leakage."""
    text = str(exc)
    db = parse_database_url()
    if db and db.password:
        text = text.replace(db.password, "***")
    if db and db.url:
        text = text.replace(db.url, "DATABASE_URL")
    # Strip common credential patterns
    for marker in ("pwd=", "password=", "PWD=", "Password="):
        if marker in text:
            parts = text.split(marker)
            text = parts[0] + marker + "***"
    return text[:500]
