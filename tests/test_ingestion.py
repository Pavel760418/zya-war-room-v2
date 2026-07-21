"""Smoke/unit тесты устойчивого ingestion-слоя и его связки с MetricsService.

Проверяем, что «битые» файлы не роняют приложение и что best-effort mapping
восстанавливает листы/колонки.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from app.ingestion import ingest_excel
from app.ingestion.data_validation import coerce_numeric_series, coerce_string_series
from app.ingestion.error_handling import Severity
from app.ingestion.sample_inputs import (
    build_broken_workbook,
    build_clean_workbook,
    build_unreadable_bytes,
    default_excel_path,
)
from app.ingestion.text_utils import normalize, similarity
from app.services.metrics_service import MetricsService


# --------------------------------------------------------------------------- #
# text_utils
# --------------------------------------------------------------------------- #
def test_normalize_strips_case_space_and_specials():
    assert normalize("  Выручка\nФАКТ ") == "выручкафакт"
    assert normalize("Топ ТЗ, всего-позиций") == normalize("топ тз всего позиций")
    assert normalize("ё-тест") == normalize("е тест")


def test_similarity_bounds():
    assert similarity("магазин", "магазин") == 1.0
    assert 0.0 <= similarity("выручка", "выручкафакт") <= 1.0


# --------------------------------------------------------------------------- #
# coercion
# --------------------------------------------------------------------------- #
def test_coerce_numeric_handles_text_nan_inf_and_separators():
    series = pd.Series(["1 250,5", "плохо", np.nan, np.inf, 42, "12%"])
    out, coerced, filled = coerce_numeric_series(series, default=0.0, fill_default=True)
    assert list(out) == [1250.5, 0.0, 0.0, 0.0, 42.0, 12.0]
    assert filled == 3  # "плохо", NaN, inf -> default
    assert coerced >= 4  # всё, что не было нативным числом
    assert not any(math.isinf(v) or math.isnan(v) for v in out)


def test_coerce_string_collapses_whitespace():
    series = pd.Series(["  Каспийск ", "Мах\nачкала", np.nan])
    out, _, filled = coerce_string_series(series, default="", fill_default=True)
    assert list(out) == ["Каспийск", "Мах ачкала", ""]
    assert filled == 1


# --------------------------------------------------------------------------- #
# Полный pipeline
# --------------------------------------------------------------------------- #
def test_real_pilot_file_ingests_and_builds_dashboard():
    path = default_excel_path()
    if not path.exists():
        pytest.skip("эталонный Excel отсутствует")
    res = ingest_excel(str(path), filename=path.name)
    assert res.ok is True
    assert res.has_store_data is True
    assert res.report.status == Severity.SUCCESS
    for col in ("Магазин", "Выручка факт", "Выручка план", "Количество чеков"):
        assert col in res.raw["sales_month"].columns
    dash = MetricsService(res.raw, mode="excel").build_dashboard(period="month")
    assert len(dash.kpis) == 5
    assert len(dash.store_table) >= 1


def test_clean_generated_workbook_two_stores():
    res = ingest_excel(build_clean_workbook(), filename="clean.xlsx")
    assert res.ok and res.has_store_data
    assert res.raw["sales_month"]["Магазин"].nunique() == 2
    dash = MetricsService(res.raw, mode="excel").build_dashboard(period="day")
    assert len(dash.store_table) == 2


def test_broken_workbook_recovers_without_crash():
    res = ingest_excel(build_broken_workbook(), filename="broken.xlsx")
    # Файл частично битый, но приложение не падает и что-то собирает.
    assert res.ok is True
    assert res.has_store_data is True

    sales = res.report.sheet("sales_month")
    assert sales.found is True
    # Лист найден по алиасу («Продажи Месяц»).
    assert sales.match_method in {"alias", "fuzzy"}
    # Заголовок был сдвинут вниз.
    assert sales.header_row and sales.header_row > 0
    # Хотя бы одна колонка восстановлена по алиасу.
    assert any(c.recovered for c in sales.columns)

    # Лист доступности удалён целиком — помечен как отсутствующий, но не рушит сборку.
    availability = res.report.sheet("availability_week")
    assert availability.found is False

    dash = MetricsService(res.raw, mode="excel").build_dashboard(period="month")
    assert len(dash.store_table) >= 1  # данные всё равно собрались


def test_broken_workbook_coerces_bad_number_to_default():
    res = ingest_excel(build_broken_workbook(), filename="broken.xlsx")
    revenues = res.raw["sales_month"]["Выручка факт"].tolist()
    # "плохое_число" должно было превратиться в 0.0, а не уронить парсинг.
    assert 0.0 in revenues
    assert all(isinstance(v, (int, float)) for v in revenues)


def test_unreadable_file_is_fatal_but_safe():
    res = ingest_excel(build_unreadable_bytes(), filename="bad.bin")
    assert res.ok is False
    assert res.report.fatal is True
    assert res.has_store_data is False
    # MetricsService на пустых данных не должен падать.
    dash = MetricsService(res.raw, mode="excel").build_dashboard(period="month")
    assert dash.store_table == []
    assert dash.drilldown is None
    assert len(dash.kpis) == 5


def test_missing_columns_get_safe_defaults():
    # Лист продаж только с магазином и выручкой — остальные колонки должны появиться.
    df = pd.DataFrame({"Магазин": ["A", "B"], "Выручка": [100, 200]})
    import io

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="продажи_месяц", index=False)
    res = ingest_excel(buffer.getvalue(), filename="partial.xlsx")
    cols = res.raw["sales_month"].columns
    assert "Выручка план" in cols and "Количество чеков" in cols
    assert (res.raw["sales_month"]["Выручка план"] == 0).all()
