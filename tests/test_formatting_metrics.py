"""Тесты форматирования чисел и согласованности среднего чека / доступности / СП%."""
from __future__ import annotations

import pandas as pd

from app.core.business_metrics import avg_ticket, availability_pct, own_production_share_pct
from app.services.metrics_service import MetricsService
from app.streamlit_ui.formatting import format_checks, format_currency_thousands, format_kpi_value


def test_format_currency_thousands_spaces_and_suffix():
    # Единый формат Часть 2: млн руб.
    assert format_currency_thousands(1100) == "1,10 млн руб."
    assert format_currency_thousands(1_100_000) == "1,10 млн руб."
    assert "млн руб." in format_currency_thousands(42.0)
    assert format_currency_thousands(15075.9) == "15,08 млн руб."
    assert format_currency_thousands(29424.5) == "29,42 млн руб."
    assert format_kpi_value(15075.9, "th_rub") == "15,08 млн руб."


def test_format_checks_integer():
    assert format_checks(6042) == "6 042"
    assert format_checks(6.0) == "6"
    assert format_kpi_value(6042, "checks") == "6 042"


def test_avg_ticket_from_consistent_sources():
    # 14_795_032.92 / 612 ≈ 24175.22
    assert abs(avg_ticket(14_795_032.92, 612) - (14_795_032.92 / 612)) < 1e-6
    assert avg_ticket(10_000, 0) == 0.0


def test_availability_and_sp_share_formulas():
    assert availability_pct(133, 250) == 53.2
    assert abs(own_production_share_pct(300, 1000) - 30.0) < 1e-9
    # Guard against inverted formula (was ~79552%)
    assert own_production_share_pct(1000, 300) > 100  # numerator>denom is data issue, not inverted calc
    assert own_production_share_pct(300, 1000) < 100


def test_metrics_service_avg_ticket_and_thousands_units():
    raw = {
        "meta": {"Название сети": "Зеленое Яблоко", "Текущий день": "2026-08-11"},
        "sales_day": pd.DataFrame(
            {
                "Дата": ["2026-08-11", "2026-08-11"],
                "Магазин": ["Акушинка", "Каспийск"],
                "Выручка факт": [1_100_000.0, 600_000.0],
                "Выручка план": [1_000_000.0, 500_000.0],
                "Количество чеков": [100.0, 50.0],
            }
        ),
        "sales_week": pd.DataFrame(),
        "sales_month": pd.DataFrame(
            {
                "Месяц": ["2026-08", "2026-08"],
                "Магазин": ["Акушинка", "Каспийск"],
                "Выручка факт": [1_100_000.0, 600_000.0],
                "Выручка план": [1_000_000.0, 500_000.0],
                "Количество чеков": [100.0, 50.0],
            }
        ),
        "availability_week": pd.DataFrame(
            {
                "Неделя": ["2026-W32", "2026-W32"],
                "Магазин": ["Акушинка", "Каспийск"],
                "Топ ТЗ всего позиций": [250, 250],
                "Топ ТЗ доступно позиций": [133, 120],
                "Топ СП всего позиций": [26, 26],
                "Топ СП доступно позиций": [20, 18],
            }
        ),
        "sp_month": pd.DataFrame(
            {
                "Месяц": ["2026-08", "2026-08"],
                "Магазин": ["Акушинка", "Каспийск"],
                "Выручка СП": [220_000.0, 90_000.0],
                "Выручка всего": [1_100_000.0, 600_000.0],
            }
        ),
        "stock_month": pd.DataFrame(),
        "losses_month": pd.DataFrame(
            {
                "Месяц": ["2026-08", "2026-08"],
                "Магазин": ["Акушинка", "Акушинка"],
                "Вид потерь": ["Списания", "Инвентаризация"],
                "Сумма": [50_000.0, 10_000.0],
            }
        ),
        "penetration_week": pd.DataFrame(),
        "writeoff_week": pd.DataFrame(),
    }
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day")
    store = next(r for r in dash.store_table if r.store == "Акушинка")
    assert store.checks == 100
    assert store.avg_ticket == 11000
    assert abs(store.revenue - 1100.0) < 0.1  # тыс. руб.
    assert abs(store.shop_availability - 53.2) < 0.1
    assert abs(store.own_production_share_pct - 20.0) < 0.1
    rev_kpi = next(k for k in dash.kpis if k.code == "revenue_day")
    assert rev_kpi.unit == "th_rub"
    checks_kpi = next(k for k in dash.kpis if k.code == "checks_day")
    assert checks_kpi.value == 150  # network
    assert "Списания" in {x.group for x in dash.losses} or any(
        x.get("group") == "Списания" for x in dash.charts.get("losses_structure", [])
    )
