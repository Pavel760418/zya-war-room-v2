"""Доступ к данным для Streamlit: загрузка, кэширование и безопасная сборка дашборда.

Инкапсулирует выбор источника (demo / excel), кэширование ingestion и защитную
обёртку вокруг ``MetricsService`` — чтобы любые сбои деградировали мягко.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import streamlit as st

from app.core.config import DEFAULT_EXCEL_FILE
from app.ingestion import IngestionResult, ingest_excel
from app.ingestion.error_handling import IngestionReport, Severity, safe_call
from app.ingestion.schema import SCHEMA
from app.repositories.demo_repository import DemoRepository
from app.services.metrics_service import MetricsService

__all__ = ["load_excel_result", "load_demo_raw", "build_dashboard_safe", "available_filters", "empty_raw"]

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
