"""Доступ к данным для Streamlit: загрузка, кэширование и безопасная сборка дашборда.

Инкапсулирует выбор источника (sql / excel / demo), кэширование ingestion и защитную
обёртку вокруг ``MetricsService`` — чтобы любые сбои деградировали мягко.
"""
from __future__ import annotations

from typing import Optional

import streamlit as st

from app.core.config import DEFAULT_EXCEL_FILE
from app.ingestion import IngestionResult, ingest_excel
from app.ingestion.error_handling import IngestionReport, Severity, safe_call
from app.ingestion.schema import SCHEMA
from app.ingestion.template import build_excel_template, template_filename
from app.repositories.demo_repository import DemoRepository
from app.repositories.sql_database import SqlStatus
from app.services.metrics_service import MetricsService
from app.services.sql_data_service import SqlDataService, SqlLoadResult

__all__ = [
    "load_excel_result",
    "load_demo_raw",
    "load_sql_result",
    "sql_connection_status",
    "build_dashboard_safe",
    "available_filters",
    "empty_raw",
    "get_template_bytes",
    "get_template_filename",
]

_DEFAULT_FILTERS = {"periods": ["day", "week", "month"], "stores": [], "regions": [], "clusters": [], "formats": []}


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


def sql_connection_status() -> SqlStatus:
    """Текущий статус SQL (без кэша — быстрый ping)."""
    try:
        return SqlDataService().status()
    except Exception as exc:  # noqa: BLE001
        return SqlStatus(ok=False, message="SQL слой недоступен", error=str(exc)[:300])


@st.cache_data(show_spinner=False, ttl=60)
def load_sql_result(_refresh_token: int = 0) -> SqlLoadResult:
    """Загрузить raw из SQL. ``_refresh_token`` сбрасывает кэш при кнопке «Обновить»."""
    try:
        return SqlDataService().load()
    except Exception as exc:  # noqa: BLE001 — soft degrade
        empty = SqlDataService().empty_raw()
        return SqlLoadResult(
            raw=empty,
            status=SqlStatus(ok=False, message="Ошибка SQL-слоя", error=str(exc)[:300]),
            warnings=[str(exc)[:300]],
            mapping_complete=False,
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
