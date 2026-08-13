"""Доступность: формула агрегата, SKU-пересчёт и вёрстка карточки магазина."""
from __future__ import annotations

import pandas as pd

from app.core.business_metrics import availability_pct
from app.ingestion.sql_extract import CATALOG_QUERIES, get_query
from app.services.metrics_service import MetricsService
from app.services.sql_data_service import SqlDataService
from app.streamlit_ui.render import kpis_html


def test_availability_pct_is_available_over_basket():
    assert availability_pct(128, 250) == 51.2
    assert availability_pct(0, 250) == 0.0
    assert availability_pct(10, 0) == 0.0


def test_sku_sql_is_registered_and_lists_stock_flag():
    assert "доступность_sku" in CATALOG_QUERIES
    sql, bind = get_query("доступность_sku", params={"week_to": "2026-08-13", "week_from": "2026-08-01"})
    assert "week_to" in bind
    assert "week_from" in bind
    assert "0.001" in sql
    assert "[Остаток]" in sql
    assert "[Продажи]" in sql
    assert "[В наличии]" in sql
    assert "Корзина Топ 200" in sql
    assert "Корзина Производство" in sql
    assert "sold_sp" in sql
    q = CATALOG_QUERIES["доступность_sku"]
    assert all(t.startswith("_") for t in q.physical_tables)
    assert "доступность_сп_день" in CATALOG_QUERIES


def test_availability_meta_recounts_sku_to_match_store_kpi():
    raw = {
        "meta": {"Название сети": "Зеленое Яблоко", "Текущий день": "2026-08-12"},
        "sales_day": pd.DataFrame(
            {
                "Дата": ["2026-08-12"],
                "Магазин": ["Ленинград"],
                "Выручка факт": [4_500_000.0],
                "Выручка план": [0.0],
                "Количество чеков": [4131.0],
            }
        ),
        "sales_week": pd.DataFrame(
            {
                "Неделя": ["2026-W33"],
                "Магазин": ["Ленинград"],
                "Выручка факт": [31_000_000.0],
                "Выручка план": [0.0],
                "Количество чеков": [28000.0],
            }
        ),
        "sales_month": pd.DataFrame(
            {
                "Месяц": ["2026-08"],
                "Магазин": ["Ленинград"],
                "Выручка факт": [52_900_000.0],
                "Выручка план": [0.0],
                "Количество чеков": [48000.0],
            }
        ),
        "availability_week": pd.DataFrame(
            {
                "Неделя": ["2026-W33"],
                "Магазин": ["Ленинград"],
                "Топ ТЗ всего позиций": [250],
                "Топ ТЗ доступно позиций": [128],
                "Топ СП всего позиций": [26],
                "Топ СП доступно позиций": [6],
            }
        ),
        "availability_sku": pd.DataFrame(
            {
                "Магазин": ["Ленинград"] * 6,
                "Артикул": ["A1", "A2", "A3", "P1", "P2", "P3"],
                "Номенклатура": ["Молоко", "Хлеб", "Масло", "Салат", "Пирог", "Суп"],
                "Корзина": ["ТЗ", "ТЗ", "ТЗ", "СП", "СП", "СП"],
                "Остаток": [4.0, 0.0, 1.0, 2.0, 0.0, 0.0],
                "В наличии": [1, 0, 1, 1, 0, 0],
            }
        ),
        "sp_month": pd.DataFrame(),
        "stock_month": pd.DataFrame(),
        "losses_month": pd.DataFrame(),
        "penetration_week": pd.DataFrame(),
        "writeoff_week": pd.DataFrame(),
    }
    dash = MetricsService(raw, mode="sql").build_dashboard(period="week", store="Ленинград")
    meta = dash.meta
    check = meta["availability_check"]
    assert check[0]["Магазин"] == "Ленинград"
    assert check[0]["ТЗ %"] == 51.2
    assert check[0]["СП %"] == round(availability_pct(6, 26), 1)
    assert len(meta["availability_detail"]) == 6
    assert meta["availability_detail"][0]["В наличии"] == "нет"
    v = meta["availability_verify"]
    assert v["tz"]["available"] == 2
    assert v["tz"]["total"] == 3
    assert v["tz"]["pct"] == round(availability_pct(2, 3), 1)
    assert v["sp"]["available"] == 1
    # Full-basket KPI (250) ≠ tiny fixture SKU list — verify flags that mismatch.
    assert v["tz_match"] is False
    store = dash.store_table[0]
    assert abs(store.shop_availability - 51.2) < 0.1


def test_kpis_html_stacked_does_not_use_four_column_grid():
    html = kpis_html(
        [
            {"code": "a", "label": "Выручка неделя", "value": 31_000, "unit": "th_rub", "status_color": "green", "hint": "Недельный итог"},
            {"code": "b", "label": "Доступность ТЗ", "value": 51.2, "unit": "pct", "status_color": "yellow", "hint": "Топ ТЗ"},
        ],
        stacked=True,
    )
    assert "kpis-stack" in html
    assert "Выручка неделя" in html
    flat = kpis_html(
        [{"code": "a", "label": "X", "value": 1, "unit": "pct", "status_color": "blue"}],
        stacked=False,
    )
    assert "kpis-stack" not in flat


def test_sp_availability_rebuilds_from_sales_in_period():
    from app.services.sql_data_service import SqlDataService

    raw = {
        "meta": {"Название сети": "Зеленое Яблоко"},
        "sales_day": pd.DataFrame(
            {
                "Дата": pd.to_datetime(["2026-08-01", "2026-08-12"]),
                "Магазин": ["Ленинград", "Ленинград"],
                "Выручка факт": [1_000_000.0, 2_000_000.0],
                "Выручка план": [0.0, 0.0],
                "Количество чеков": [100.0, 200.0],
            }
        ),
        "availability_week": pd.DataFrame(
            {
                "Магазин": ["Ленинград"],
                "Топ ТЗ всего позиций": [250],
                "Топ ТЗ доступно позиций": [125],
                "Топ СП всего позиций": [3],
                "Топ СП доступно позиций": [3],
            }
        ),
        "availability_sku": pd.DataFrame(
            {
                "Магазин": ["Ленинград"] * 3,
                "Артикул": ["P1", "P2", "P3"],
                "Номенклатура": ["Салат", "Пирог", "Суп"],
                "Корзина": ["СП", "СП", "СП"],
                "Остаток": [2.0, 0.0, 1.0],
                "Продажи": [0.0, 0.0, 0.0],
                "В наличии": [1, 0, 1],
            }
        ),
        "availability_sp_day": pd.DataFrame(
            {
                "Дата": pd.to_datetime(["2026-08-01", "2026-08-12", "2026-08-12"]),
                "Магазин": ["Ленинград", "Ленинград", "Ленинград"],
                "Артикул": ["P1", "P1", "P2"],
                "Номенклатура": ["Салат", "Салат", "Пирог"],
                "Продажи": [100.0, 50.0, 20.0],
            }
        ),
        "_custom_from": "2026-08-12",
        "_custom_to": "2026-08-12",
        "_metric_profile": "pbi",
    }
    out = SqlDataService(use_env_db=False)._normalize_period_sheets(raw)
    week = out["availability_week"]
    row = week[week["Магазин"] == "Ленинград"].iloc[0]
    assert int(row["Топ СП доступно позиций"]) == 2  # P1+P2 sold on 12.08, not P3
    sku = out["availability_sku"]
    flags = dict(zip(sku["Артикул"].astype(str), sku["В наличии"]))
    assert flags["P1"] == 1
    assert flags["P2"] == 1
    assert flags["P3"] == 0
    dash = MetricsService(out, mode="sql").build_dashboard(period="month", store="Ленинград")
    store = dash.store_table[0]
    assert abs(store.production_availability - round(availability_pct(2, 3), 1)) < 0.15
    assert "продажами за выбранный период" in dash.meta["availability_formula"]


def test_window_params_tz_stock_is_previous_day():
    from datetime import date, timedelta
    import os

    params = SqlDataService(use_env_db=False)._window_params()
    lookback = int(os.environ.get("WARROOM_LOOKBACK_DAYS", "31"))
    assert params["week_to"] == date.today()
    assert params["week_from"] == date.today() - timedelta(days=lookback)
    assert params["date_to"] == date.today() + timedelta(days=1)
