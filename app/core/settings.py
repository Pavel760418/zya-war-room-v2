"""Runtime settings for War Room.

Secrets resolution order:
1. Streamlit ``st.secrets`` (Cloud / local ``.streamlit/secrets.toml``)
2. Environment variables (systemd / shell / ``warroom.env``)
3. Optional dotenv files under ``~/.config/warroom/warroom.env``
4. LAN edge bridge defaults (``app.core._cloud_bridge``) for Streamlit Cloud
   when direct MSSQL is unreachable from the internet.

``DATABASE_URL`` **or** gateway (``WARROOM_GATEWAY_URL`` + token) is required.
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
    Path.home() / ".config" / "warroom" / "gateway.env",
    Path("/etc/warroom.env"),
    Path(__file__).resolve().parents[2] / ".env",
)


def _load_secret_files() -> Optional[Path]:
    found = None
    for path in _SECRET_CANDIDATES:
        if path.is_file():
            load_dotenv(path, override=False)
            found = found or path
    load_dotenv(override=False)
    return found


_load_secret_files()


def _bridge_defaults() -> tuple[Optional[str], Optional[str]]:
    try:
        from app.core import _cloud_bridge as bridge

        return getattr(bridge, "GATEWAY_URL", None), getattr(bridge, "GATEWAY_TOKEN", None)
    except Exception:  # noqa: BLE001
        return None, None


def _streamlit_secrets() -> dict[str, Any]:
    try:
        import streamlit as st

        secrets = getattr(st, "secrets", None)
        if secrets is None:
            return {}
        out: dict[str, Any] = {}
        try:
            for key in secrets:
                out[str(key)] = secrets[key]
        except Exception:  # noqa: BLE001
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
                "WARROOM_GATEWAY_URL",
                "WARROOM_GATEWAY_TOKEN",
            ):
                try:
                    if key in secrets:
                        out[key] = secrets[key]
                except Exception:  # noqa: BLE001
                    pass
        try:
            db = secrets.get("database") if hasattr(secrets, "get") else None
            if db is not None:
                for k in ("url", "host", "port", "name", "user", "password"):
                    try:
                        if k in db and db[k] not in (None, ""):
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
            gw = secrets.get("gateway") if hasattr(secrets, "get") else None
            if gw is not None:
                if "url" in gw and gw["url"]:
                    out["WARROOM_GATEWAY_URL"] = gw["url"]
                if "token" in gw and gw["token"]:
                    out["WARROOM_GATEWAY_TOKEN"] = gw["token"]
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
class GatewaySettings:
    url: str
    token: str


@dataclass(frozen=True)
class AppSettings:
    data_source_default: str  # mssql | demo (excel only for tests)
    sql_connect_timeout: int
    database_url: Optional[str]
    secrets_file: Optional[str]
    missing_secret_keys: tuple[str, ...]
    gateway_url: Optional[str] = None
    gateway_token: Optional[str] = None


def get_gateway_settings() -> Optional[GatewaySettings]:
    bridge_url, bridge_token = _bridge_defaults()
    url = _secret_get("WARROOM_GATEWAY_URL") or bridge_url
    token = _secret_get("WARROOM_GATEWAY_TOKEN") or bridge_token
    if url and token:
        return GatewaySettings(url=url.rstrip("/"), token=token)
    return None


def missing_database_secret_keys() -> tuple[str, ...]:
    """Keys absent for direct SQL. Empty if gateway bridge can serve Cloud."""
    if get_gateway_settings() is not None:
        return ()
    if _secret_get("DATABASE_URL"):
        return ()
    missing: list[str] = []
    for key in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        if key == "DB_PASSWORD":
            if not (_secret_get("DB_HOST") and _secret_get("DB_NAME") and _secret_get("DB_USER")):
                if not _secret_get(key) and os.getenv(key) is None:
                    missing.append(key)
            continue
        if not _secret_get(key):
            missing.append(key)
    if missing:
        return ("DATABASE_URL", "WARROOM_GATEWAY_URL", "WARROOM_GATEWAY_TOKEN", *missing)
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
        raw_mode = "mssql"

    db_url = _secret_get("DATABASE_URL") or _compose_database_url_from_parts()
    gw = get_gateway_settings()
    timeout_raw = _secret_get("WARROOM_SQL_TIMEOUT") or "60"
    try:
        timeout = int(timeout_raw)
    except ValueError:
        timeout = 60

    missing = () if (db_url or gw) else missing_database_secret_keys()

    return AppSettings(
        data_source_default=raw_mode,
        sql_connect_timeout=timeout,
        database_url=db_url,
        secrets_file=str(secrets_path) if secrets_path else None,
        missing_secret_keys=missing,
        gateway_url=gw.url if gw else None,
        gateway_token=gw.token if gw else None,
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
    gw = get_gateway_settings()
    if gw and gw.token:
        text = text.replace(gw.token, "***")
    for marker in ("pwd=", "password=", "PWD=", "Password="):
        if marker in text:
            parts = text.split(marker)
            text = parts[0] + marker + "***"
    return text[:500]
