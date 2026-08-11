"""Runtime settings for War Room.

Secrets resolution order:
1. Streamlit ``st.secrets`` (Cloud / local ``.streamlit/secrets.toml``)
2. Environment variables (systemd / shell / ``warroom.env``)
3. Optional dotenv files under ``~/.config/warroom/warroom.env``

``DATABASE_URL`` **or** ``DB_HOST``+``DB_NAME``+``DB_USER``+``DB_PASSWORD`` are required
for the SQL-only product path.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote_plus, unquote, urlparse

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover

    def load_dotenv(*_args, **_kwargs) -> bool:  # type: ignore[misc]
        return False


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
    load_dotenv(override=False)
    return None


_load_secret_files()


def _streamlit_secrets() -> dict[str, Any]:
    try:
        import streamlit as st

        secrets = getattr(st, "secrets", None)
        if secrets is None:
            return {}
        # st.secrets behaves like a mapping; convert carefully
        out: dict[str, Any] = {}
        try:
            for key in secrets:
                out[str(key)] = secrets[key]
        except Exception:  # noqa: BLE001
            # Fallback: known keys
            for key in (
                "DATABASE_URL",
                "DB_HOST",
                "DB_PORT",
                "DB_NAME",
                "DB_USER",
                "DB_PASSWORD",
                "DATA_SOURCE_MODE",
                "WARROOM_DATA_SOURCE",
                "WARROOM_SQL_TIMEOUT",
            ):
                try:
                    if key in secrets:
                        out[key] = secrets[key]
                except Exception:  # noqa: BLE001
                    pass
        # Nested [database] block
        try:
            db = secrets.get("database") if hasattr(secrets, "get") else None
            if db is not None:
                for k in ("url", "host", "port", "name", "user", "password"):
                    try:
                        if k in db and db[k] not in (None, ""):
                            out[f"db_{k}" if k != "url" else "DATABASE_URL"] = db[k]
                            if k == "url":
                                out["DATABASE_URL"] = db[k]
                            elif k == "host":
                                out["DB_HOST"] = db[k]
                            elif k == "port":
                                out["DB_PORT"] = db[k]
                            elif k == "name":
                                out["DB_NAME"] = db[k]
                            elif k == "user":
                                out["DB_USER"] = db[k]
                            elif k == "password":
                                out["DB_PASSWORD"] = db[k]
                    except Exception:  # noqa: BLE001
                        pass
        except Exception:  # noqa: BLE001
            pass
        return out
    except Exception:  # noqa: BLE001
        return {}


def _secret_get(name: str, default: Optional[str] = None) -> Optional[str]:
    secrets = _streamlit_secrets()
    if name in secrets and secrets[name] not in (None, ""):
        return str(secrets[name]).strip()
    env = os.getenv(name)
    if env is not None and str(env).strip() != "":
        return str(env).strip()
    return default


def _compose_database_url_from_parts() -> Optional[str]:
    host = _secret_get("DB_HOST")
    name = _secret_get("DB_NAME")
    user = _secret_get("DB_USER")
    password = _secret_get("DB_PASSWORD") or ""
    port = _secret_get("DB_PORT") or "1433"
    if not host or not name or not user:
        return None
    return f"mssql+pymssql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{name}"


@dataclass(frozen=True)
class DatabaseSettings:
    url: str
    host: str
    port: int
    user: str
    password: str
    database: str
    secrets_file: Optional[str] = None


@dataclass(frozen=True)
class AppSettings:
    data_source_default: str  # mssql | demo (excel only for tests)
    sql_connect_timeout: int
    database_url: Optional[str]
    secrets_file: Optional[str]
    missing_secret_keys: tuple[str, ...]


def missing_database_secret_keys() -> tuple[str, ...]:
    """Which connection keys are absent (for the UI error screen)."""
    if _secret_get("DATABASE_URL"):
        return ()
    missing: list[str] = []
    for key in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        # password may be empty for trusted networks — still require the key present
        if key == "DB_PASSWORD":
            secrets = _streamlit_secrets()
            if key not in secrets and os.getenv(key) is None and not _secret_get("DATABASE_URL"):
                # allow empty password if other parts exist
                if not (_secret_get("DB_HOST") and _secret_get("DB_NAME") and _secret_get("DB_USER")):
                    missing.append(key)
            continue
        if not _secret_get(key):
            missing.append(key)
    if missing:
        # Also report DATABASE_URL as the preferred single key
        return ("DATABASE_URL", *missing)
    return ("DATABASE_URL",) if not _compose_database_url_from_parts() else ()


def get_app_settings() -> AppSettings:
    secrets_path = _load_secret_files()
    raw_mode = (
        _secret_get("DATA_SOURCE_MODE")
        or _secret_get("WARROOM_DATA_SOURCE")
        or "mssql"
    ).strip().lower() or "mssql"
    if raw_mode in ("mssql", "sql"):
        raw_mode = "mssql"
    elif raw_mode == "demo":
        raw_mode = "demo"
    else:
        # excel is internal/test only — product default remains mssql
        raw_mode = "mssql" if raw_mode == "excel" else "mssql"

    db_url = _secret_get("DATABASE_URL") or _compose_database_url_from_parts()
    timeout_raw = _secret_get("WARROOM_SQL_TIMEOUT") or "8"
    try:
        timeout = int(timeout_raw)
    except ValueError:
        timeout = 8

    return AppSettings(
        data_source_default=raw_mode,
        sql_connect_timeout=timeout,
        database_url=db_url,
        secrets_file=str(secrets_path) if secrets_path else None,
        missing_secret_keys=missing_database_secret_keys() if not db_url else (),
    )


def parse_database_url(url: Optional[str] = None) -> Optional[DatabaseSettings]:
    settings = get_app_settings()
    raw = (url or settings.database_url or "").strip()
    if not raw:
        return None

    normalized = raw.replace("mssql+pymssql://", "mssql://", 1)
    parsed = urlparse(normalized)
    if parsed.scheme not in ("mssql", "mssql+pymssql"):
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
    text = str(exc)
    db = parse_database_url()
    if db and db.password:
        text = text.replace(db.password, "***")
    if db and db.url:
        text = text.replace(db.url, "DATABASE_URL")
    for marker in ("pwd=", "password=", "PWD=", "Password="):
        if marker in text:
            parts = text.split(marker)
            text = parts[0] + marker + "***"
    return text[:500]
