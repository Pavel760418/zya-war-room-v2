"""Доступ к данным для Streamlit: загрузка, кэширование и безопасная сборка дашборда.

Инкапсулирует выбор источника (sql / excel / demo), кэширование ingestion и защитную
обёртку вокруг ``MetricsService`` — чтобы любые сбои деградировали мягко.

SQL-зависимости (pymssql / dotenv) опциональны: на Streamlit Cloud приложение
должно стартовать в Excel/Demo без падения импорта.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import streamlit as st

from app.core.config import DEFAULT_EXCEL_FILE
from app.ingestion import IngestionResult, ingest_excel
from app.ingestion.error_handling import IngestionReport, Severity, safe_call
from app.ingestion.schema import SCHEMA
from app.ingestion.template import build_excel_template, template_filename
from app.repositories.demo_repository import DemoRepository
from app.services.metrics_service import MetricsService

__all__ = [
    "load_excel_result",
    "load_demo_raw",
    "load_sql_result",
    "sql_connection_status",
    "sql_available",
    "build_dashboard_safe",
    "available_filters",
    "empty_raw",
    "get_template_bytes",
    "get_template_filename",
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
except Exception as _exc:  # noqa: BLE001 — Cloud may lack pymssql/dotenv/ FreeTDS
    _SQL_AVAILABLE = False
    _SQL_IMPORT_ERROR = f"{type(_exc).__name__}: {str(_exc)[:200]}"
    SqlDataService = None  # type: ignore[assignment, misc]


def sql_available() -> bool:
    """True only when SQL modules import AND a live connection works.

    Streamlit Cloud has no route to private 1C SQL — this keeps Cloud on Excel/Demo.
    """
    if not _SQL_AVAILABLE or SqlDataService is None:
        return False
    try:
        return bool(SqlDataService().status().ok)
    except Exception:  # noqa: BLE001
        return False


def empty_raw() -> dict:
    """Пустой, но структурно валидный ``raw`` (все листы с каноническими колонками)."""
    import pandas as pd

    raw: dict = {"meta": {}}
    for _canon, spec in SCHEMA.items():
        raw[spec.canonical] = pd.DataFrame({c.canonical: pd.Series(dtype=object) for c in spec.columns})
    return raw


@st.cache_data(show_spinner=False)
def _ingest_bytes(data: bytes, filename: str) -> IngestionResult:
    return ingest_excel(data, filename=filename)


@st.cache_data(show_spinner=False)
def _ingest_path(path_str: str, _mtime: float, filename: str) -> IngestionResult:
    return ingest_excel(path_str, filename=filename)


def load_excel_result(uploaded_bytes: Optional[bytes], filename: Optional[str]) -> IngestionResult:
    """Получить результат ingestion: из загруженного файла либо из эталонного.

    Никогда не бросает исключение — при отсутствии файла возвращает пустой,
    но валидный результат с понятным сообщением.
    """
    if uploaded_bytes is not None:
        return _ingest_bytes(uploaded_bytes, filename or "upload.xlsx")

    if DEFAULT_EXCEL_FILE.exists():
        return _ingest_path(str(DEFAULT_EXCEL_FILE), DEFAULT_EXCEL_FILE.stat().st_mtime, DEFAULT_EXCEL_FILE.name)

    report = IngestionReport(filename=None)
    report.add(Severity.WARNING, "Эталонный Excel не найден — загрузите файл через панель слева.")
    return IngestionResult(raw=empty_raw(), report=report, ok=False)


@st.cache_data(show_spinner=False)
def load_demo_raw(seed: int = 42, stores_count: int = 24) -> dict:
    """Сгенерировать demo-данные (сеть магазинов)."""
    return DemoRepository(seed=seed, stores_count=stores_count).load()


def sql_connection_status() -> Any:
    """Текущий статус SQL (без кэша — быстрый ping)."""
    if not _SQL_AVAILABLE or SqlDataService is None:
        return SqlStatus(
            ok=False,
            message="SQL-слой недоступен в этой среде (нет драйвера/секретов). Используйте Excel или Demo.",
            error=_SQL_IMPORT_ERROR or "sql_unavailable",
        )
    try:
        return SqlDataService().status()
    except Exception as exc:  # noqa: BLE001
        return SqlStatus(ok=False, message="SQL слой недоступен", error=str(exc)[:300])


@st.cache_data(show_spinner=False, ttl=60)
def load_sql_result(_refresh_token: int = 0) -> Any:
    """Загрузить raw из SQL. При недоступности — Excel (не пустой каркас)."""
    fallback_notice = "MSSQL источник недоступен, используется Excel"

    def _excel_fallback(status: Any, extra_warnings: list[str] | None = None) -> Any:
        excel = load_excel_result(None, None)
        warnings = [fallback_notice, *(extra_warnings or [])]
        if excel.report and excel.report.messages:
            warnings.append(f"Excel: {excel.report.status}")
        return SqlLoadResult(
            raw=excel.raw,
            status=status,
            warnings=warnings,
            mapping_complete=False,
            last_success_at=None,
        )

    if not _SQL_AVAILABLE or SqlDataService is None:
        return _excel_fallback(sql_connection_status(), [_SQL_IMPORT_ERROR or "sql_unavailable"])
    try:
        result = SqlDataService().load()
        if not getattr(result.status, "ok", False):
            return _excel_fallback(result.status, list(result.warnings or []))
        return result
    except Exception as exc:  # noqa: BLE001 — soft degrade to excel
        return _excel_fallback(
            SqlStatus(ok=False, message="Ошибка SQL-слоя", error=str(exc)[:300]),
            [str(exc)[:300]],
        )


@st.cache_data(show_spinner=False)
def get_template_bytes() -> bytes:
    """Сгенерировать (и закэшировать) .xlsx-шаблон для скачивания."""
    return build_excel_template()


def get_template_filename() -> str:
    return template_filename()


def available_filters(raw: dict, mode: str) -> dict:
    """Безопасно получить списки фильтров (магазины, регионы, кластеры)."""
    service, _ = safe_call(MetricsService, raw, mode=mode)
    if service is None:
        return dict(_DEFAULT_FILTERS)
    filters, _ = safe_call(service.filters, default=dict(_DEFAULT_FILTERS))
    return filters or dict(_DEFAULT_FILTERS)


def build_dashboard_safe(raw: dict, mode: str, period: str, store: Optional[str]):
    """Безопасно собрать дашборд.

    Возвращает ``(dashboard_or_None, error_or_None)``.
    """
    service, err = safe_call(MetricsService, raw, mode=mode)
    if service is None:
        return None, err
    dashboard, derr = safe_call(service.build_dashboard, period=period, store=store)
    return dashboard, derr
