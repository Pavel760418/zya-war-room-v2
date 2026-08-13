"""Регрессии: остатки-снимок, потери без задвоения, M09 методология."""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.ingestion.sql_extract import T_SHIFT_GOODS, T_STOCK_TOTALS, get_query
from app.services.metrics_service import MetricsService


def test_stock_sql_uses_totals_snapshot_not_120d_window():
    sql, _ = get_query(
        "остатки_месяц",
        params={"month_from": date.today().replace(day=1), "month_to": date.today()},
    )
    assert T_STOCK_TOTALS == "_AccumRgT6616"
    assert "_AccumRgT6616" in sql
    assert "DATEADD(day, -120" not in sql
    assert "_RecordKind" not in sql


def test_penetration_sql_uses_shift_goods_vt2284():
    sql, _ = get_query(
        "пенетрация_неделя",
        params={"date_from": date.today(), "date_to": date.today()},
    )
    assert T_SHIFT_GOODS == "_Document119_VT2284"
    assert "_Document119_VT2284" in sql
    assert "_Fld2286RRef" in sql
    assert "_Fld2295" in sql
    assert "_AccumRg6691" not in sql


def test_losses_sql_inventory_uses_header_once():
    sql, _ = get_query(
        "потери_месяц",
        params={"date_from": date.today().replace(day=1), "date_to": date.today()},
    )
    assert "_Fld2523" in sql
    assert "_Document124_VT2532" not in sql  # нет JOIN строк → нет задвоения hdr
    assert "SELECT SUM(CAST(vt._Fld4685" in sql.replace("\n", " ")


def test_stock_autodom_non_negative_from_fixture():
    raw = {
        "meta": {"Название сети": "Зеленое Яблоко", "Текущий день": "2026-08-10"},
        "sales_day": pd.DataFrame(
            {"Дата": ["2026-08-10"], "Магазин": ["Автодом"], "Выручка факт": [1e6], "Выручка план": [0], "Количество чеков": [100]}
        ),
        "sales_week": pd.DataFrame(
            {"Неделя": ["w"], "Магазин": ["Автодом"], "Выручка факт": [1e6], "Выручка план": [0], "Количество чеков": [100]}
        ),
        "sales_month": pd.DataFrame(
            {"Месяц": ["2026-08"], "Магазин": ["Автодом"], "Выручка факт": [1e6], "Выручка план": [0], "Количество чеков": [100]}
        ),
        "availability_week": pd.DataFrame(),
        "sp_month": pd.DataFrame(),
        "stock_month": pd.DataFrame(
            {
                "Месяц": ["2026-08"],
                "Магазин": ["Автодом"],
                "Остатки на конец месяца факт": [49_541_367.08],
                "Остатки на конец месяца план": [0],
            }
        ),
        "losses_month": pd.DataFrame(),
        "losses_day": pd.DataFrame(),
        "penetration_week": pd.DataFrame(),
        "writeoff_week": pd.DataFrame(),
    }
    row = next(r for r in MetricsService(raw, mode="sql").rows("month") if r.store == "Автодом")
    assert row.stock_fact > 0
    assert abs(row.stock_fact - 49541.4) < 1.0


def test_losses_one_doc_equals_line_sum_no_article_multiplier():
    """Статья в шапке: 12 строк × 3652 суммарно, не 12×3652."""
    raw = {
        "meta": {"Название сети": "ЗЯ", "Текущий день": "2026-08-11"},
        "sales_day": pd.DataFrame(
            {"Дата": ["2026-08-11"], "Магазин": ["Акушинка"], "Выручка факт": [2e6], "Выручка план": [0], "Количество чеков": [2000]}
        ),
        "sales_week": pd.DataFrame(),
        "sales_month": pd.DataFrame(
            {"Месяц": ["2026-08"], "Магазин": ["Акушинка"], "Выручка факт": [2e6], "Выручка план": [0], "Количество чеков": [2000]}
        ),
        "availability_week": pd.DataFrame(),
        "sp_month": pd.DataFrame(),
        "stock_month": pd.DataFrame(),
        "losses_day": pd.DataFrame(
            {
                "Дата": ["2026-08-11", "2026-08-11"],
                "Магазин": ["Акушинка", "Акушинка"],
                "Вид потерь": ["Потеря потребительских свойств", "Инвентаризация"],
                "Сумма": [3652.0, 974.94],
            }
        ),
        "losses_month": pd.DataFrame(
            {
                "Дата": ["2026-08-11", "2026-08-11"],
                "Магазин": ["Акушинка", "Акушинка"],
                "Вид потерь": ["Потеря потребительских свойств", "Инвентаризация"],
                "Сумма": [3652.0, 974.94],
            }
        ),
        "penetration_week": pd.DataFrame(),
        "writeoff_week": pd.DataFrame(),
    }
    row = next(r for r in MetricsService(raw, mode="sql").rows("day") if r.store == "Акушинка")
    assert abs(row.losses - 3652.0 / 1000) < 0.05  # списания без недостач
    assert abs(row.inventory_shortage - 974.94 / 1000) < 0.05
    # не 12× статья
    assert row.losses < 40
