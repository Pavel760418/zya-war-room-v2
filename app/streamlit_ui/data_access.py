"""Доступ к данным для Streamlit: SQL-only путь + безопасная сборка дашборда.

Excel остаётся только для юнит-тестов (``app.ingestion`` / ``tests/``).
Пользовательский UI никогда не переключается на Excel при сбое SQL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import streamlit as st

from app.core.settings import missing_database_secret_keys
from app.ingestion.error_handling import safe_call
from app.ingestion.schema import SCHEMA
from app.repositories.demo_repository import DemoRepository
from app.services.metrics_service import MetricsService

__all__ = [
    "load_demo_raw",
    "load_sql_result",
    "sql_connection_status",
    "sql_available",
    "build_dashboard_safe",
    "available_filters",
    "empty_raw",
    "render_sql_connection_error",
    "SqlStatus",
    "SqlLoadResult",
]


_DEFAULT_FILTERS = {"periods": ["day", "week", "month"], "stores": [], "regions": [], "clusters": [], "formats": []}


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
class SqlLoadResult:
    raw: dict
    status: SqlStatus
    warnings: list[str] = field(default_factory=list)
    mapping_complete: bool = False
    last_success_at: Optional[str] = None
    confidence_notes: list[str] = field(default_factory=list)


_SQL_IMPORT_ERROR: Optional[str] = None
try:
    from app.repositories.sql_database import SqlStatus as _SqlStatusImpl
    from app.services.sql_data_service import SqlDataService, SqlLoadResult as _SqlLoadResultImpl

    SqlStatus = _SqlStatusImpl  # type: ignore[misc, assignment]
    SqlLoadResult = _SqlLoadResultImpl  # type: ignore[misc, assignment]
    _SQL_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001
    _SQL_AVAILABLE = False
    _SQL_IMPORT_ERROR = f"{type(_exc).__name__}: {str(_exc)[:200]}"
    SqlDataService = None  # type: ignore[assignment, misc]


def sql_available() -> bool:
    if not _SQL_AVAILABLE or SqlDataService is None:
        return False
    try:
        return bool(SqlDataService().status().ok)
    except Exception:  # noqa: BLE001
        return False


def empty_raw() -> dict:
    import pandas as pd

    raw: dict = {"meta": {}}
    for _canon, spec in SCHEMA.items():
        raw[spec.canonical] = pd.DataFrame({c.canonical: pd.Series(dtype=object) for c in spec.columns})
    return raw


@st.cache_data(show_spinner="Загружаем демо-данные...")
def load_demo_raw(seed: int = 42, stores_count: int = 24) -> dict:
    return DemoRepository(seed=seed, stores_count=stores_count).load()


def sql_connection_status() -> Any:
    if not _SQL_AVAILABLE or SqlDataService is None:
        missing = missing_database_secret_keys()
        return SqlStatus(
            ok=False,
            message="SQL-слой недоступен (нет драйвера pymssql или ошибка импорта).",
            error=_SQL_IMPORT_ERROR or "sql_unavailable",
            engine=",".join(missing) if missing else None,
        )
    try:
        return SqlDataService().status()
    except Exception as exc:  # noqa: BLE001
        return SqlStatus(ok=False, message="SQL слой недоступен", error=str(exc)[:300])


@st.cache_data(show_spinner="Загружаем данные из локального снимка...", ttl=60)
def load_sql_result(_refresh_token: int = 0) -> Any:
    """Загрузить raw из локального кэша (или live SQL только если явно включено).

    TTL 60с: десятки параллельных сессий не пересчитывают тяжёлую загрузку заново.
    """
    if not _SQL_AVAILABLE or SqlDataService is None:
        status = sql_connection_status()
        return SqlLoadResult(
            raw=empty_raw(),
            status=status,
            warnings=[status.message, status.error or ""],
            mapping_complete=False,
            last_success_at=None,
        )
    try:
        svc = SqlDataService()
        result = svc.load()
        src = (result.raw or {}).get("_data_source") or (
            "live_sql" if svc.uses_live_sql else "local_cache"
        )
        # Явный след для аудита: что читает пользовательский UI.
        print(
            f"[warroom.data] source={src} live_sql={svc.uses_live_sql} "
            f"server={getattr(result.status, 'server', None)} "
            f"synced_at={result.last_success_at}",
            flush=True,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        return SqlLoadResult(
            raw=empty_raw(),
            status=SqlStatus(ok=False, message="Ошибка SQL-слоя", error=str(exc)[:300]),
            warnings=[str(exc)[:300]],
            mapping_complete=False,
            last_success_at=None,
        )


def render_sql_connection_error(status: Any) -> None:
    """Полноэкранная ошибка подключения в стиле дашборда (без Excel-fallback)."""
    missing = missing_database_secret_keys()
    err = getattr(status, "error", None) or ""
    msg = getattr(status, "message", "") or "Нет подключения к MSSQL"
    st.markdown(
        """
        <div class="hero-card" style="padding:2rem 1.5rem;margin-bottom:1rem;">
          <div class="pill">МегаМетрики</div>
          <h2 style="margin:0.6rem 0 0.4rem;">Нет подключения к базе 1С (MSSQL)</h2>
          <p class="subtle" style="max-width:52rem;">
            Приложение работает только через SQL. Задайте Secrets и убедитесь, что хост доступен
            с машины, где крутится Streamlit.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.error(f"{msg}" + (f" · `{err}`" if err else ""))
    if missing or err == "missing_database_url":
        st.markdown("**Не заданы обязательные Secrets:**")
        keys = missing or ("DATABASE_URL", "DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD")
        for k in keys:
            st.code(k, language=None)
        st.markdown(
            "Скопируйте блок из `.streamlit/secrets.toml.example` в "
            "**Streamlit Cloud → Settings → Secrets** (или локальный "
            "`.streamlit/secrets.toml` / `~/.config/warroom/warroom.env`)."
        )
    st.markdown(
        """
```toml
# Вариант A — одна строка
DATABASE_URL = "mssql+pymssql://USER:PASSWORD@HOST:1433/DATABASE"

# Вариант B — отдельные ключи
DB_HOST = "192.168.2.10"
DB_PORT = "1433"
DB_NAME = "retail"
DB_USER = "readonly_user"
DB_PASSWORD = "***"
```
        """
    )
    if getattr(status, "server", None):
        st.caption(f"Сервер из конфигурации: `{status.server}` / БД: `{status.database or '—'}`")


def available_filters(raw: dict, mode: str) -> dict:
    service, _ = safe_call(MetricsService, raw, mode=mode)
    if service is None:
        return dict(_DEFAULT_FILTERS)
    filters, _ = safe_call(service.filters, default=dict(_DEFAULT_FILTERS))
    return filters or dict(_DEFAULT_FILTERS)


def build_dashboard_safe(raw: dict, mode: str, period: str, store: Optional[str]):
    service, err = safe_call(MetricsService, raw, mode=mode)
    if service is None:
        return None, err
    dashboard, derr = safe_call(service.build_dashboard, period=period, store=store)
    return dashboard, derr
