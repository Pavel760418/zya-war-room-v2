"""Тесты источника чеков (ЗакрытиеСмены) и разбивки потерь по статьям."""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.ingestion.sql_extract import T_SHIFT, T_SHIFT_CASH, get_query
from app.services.metrics_service import MetricsService
from app.streamlit_ui.formatting import format_checks


def test_sales_sql_uses_shift_close_not_goods_receipt():
    sql, _ = get_query("продажи_день", params={"date_from": date.today(), "date_to": date.today()})
    assert T_SHIFT == "_Document119"
    assert T_SHIFT_CASH == "_Document119_VT2313"
    assert "_Document119" in sql
    assert "_Document119_VT2313" in sql
    assert "_Fld2319" in sql
    assert "_Fld6977" in sql
    assert "_Fld2267RRef" in sql
    assert "_Document156" not in sql
    assert "_Fld4036" not in sql


def test_akushinka_fixture_avg_ticket_realistic():
    """Контрольная фикстура: Акушинка 2026-08-10 — 2163 чека, 2 141 430.61 руб."""
    checks = 2163.0
    revenue = 2_141_430.61
    avg = revenue / checks
    assert 900 < avg < 1500  # реалистичный средний чек розницы
    assert format_checks(checks) == "2 163"


def test_metrics_service_shift_checks_and_loss_articles():
    raw = {
        "meta": {"Название сети": "Зеленое Яблоко", "Текущий день": "2026-08-10"},
        "sales_day": pd.DataFrame(
            {
                "Дата": ["2026-08-10"],
                "Магазин": ["Акушинка"],
                "Выручка факт": [2_141_430.61],
                "Выручка план": [0.0],
                "Количество чеков": [2163.0],
            }
        ),
        "sales_week": pd.DataFrame(),
        "sales_month": pd.DataFrame(
            {
                "Месяц": ["2026-08"],
                "Магазин": ["Акушинка"],
                "Выручка факт": [2_141_430.61],
                "Выручка план": [0.0],
                "Количество чеков": [2163.0],
            }
        ),
        "availability_week": pd.DataFrame(),
        "sp_month": pd.DataFrame(
            {
                "Месяц": ["2026-08"],
                "Магазин": ["Акушинка"],
                "Выручка СП": [500_000.0],
                "Выручка всего": [2_141_430.61],
            }
        ),
        "stock_month": pd.DataFrame(),
        "losses_month": pd.DataFrame(
            {
                "Месяц": ["2026-08", "2026-08", "2026-08"],
                "Магазин": ["Акушинка", "Акушинка", "Акушинка"],
                "Вид потерь": ["Хоз нужды", "Обед персонала", "Инвентаризация"],
                "Сумма": [100_000.0, 20_000.0, 5_000.0],
            }
        ),
        "losses_day": pd.DataFrame(
            {
                "Дата": ["2026-08-10", "2026-08-10", "2026-08-10"],
                "Магазин": ["Акушинка", "Акушинка", "Акушинка"],
                "Вид потерь": ["Хоз нужды", "Обед персонала", "Инвентаризация"],
                "Сумма": [100_000.0, 20_000.0, 5_000.0],
            }
        ),
        "penetration_week": pd.DataFrame(),
        "writeoff_week": pd.DataFrame(
            {
                "Неделя": ["2026-W32", "2026-W32"],
                "Магазин": ["Акушинка", "Акушинка"],
                "Статья списания": ["Хоз нужды", "Обед персонала"],
                "Сумма": [100_000.0, 20_000.0],
            }
        ),
    }
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day", store="Акушинка")
    row = dash.store_table[0]
    assert row.checks == 2163
    assert 900 < row.avg_ticket < 1500
    assert row.losses > 0
    assert row.inventory_shortage > 0
    groups = {x.group for x in dash.losses}
    assert "Хоз нужды" in groups
    assert "Обед персонала" in groups
    assert "Инвентаризация" in groups


def test_losses_sql_joins_reference82_and_inventory_fields():
    sql, _ = get_query(
        "потери_месяц",
        params={"date_from": date.today().replace(day=1), "date_to": date.today()},
    )
    assert "_Reference82" in sql
    assert "_Fld4669RRef" in sql
    assert "_Fld4658RRef" in sql  # магазин списания
    assert "_Fld2513RRef" in sql  # магазин инвентаризации
    assert "_Fld2523" in sql  # сумма отклонения шапки
    assert "_Fld4656RRef" not in sql
    assert "_Fld2511RRef" not in sql
