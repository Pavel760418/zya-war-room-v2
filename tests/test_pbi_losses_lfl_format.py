"""Регрессии Parts 0–10: списания/расходы, средний чек, формат млн, LFL без синтетики."""
from __future__ import annotations

import pandas as pd

from app.metrics.loss_articles import (
    COMMODITY_WRITEOFF_ARTICLES,
    EXPENSE_ARTICLES,
    classify_article,
    is_commodity_writeoff,
    is_expense,
)
from app.services.metrics_service import MetricsService
from app.services.pbi_parity_loader import build_pbi_losses_day, lfl_rto_pct
from app.streamlit_ui.formatting import format_currency_mln, format_kpi_value, format_money


def test_commodity_excludes_expenses():
    assert "Обед персонала" in EXPENSE_ARTICLES
    assert "Представительские расходы" in EXPENSE_ARTICLES
    assert not is_commodity_writeoff("Обед персонала")
    assert is_commodity_writeoff("Потеря потребительских свойств")
    assert is_expense("Обед персонала")
    assert classify_article("Обед персонала") == "Расходы"
    assert set(COMMODITY_WRITEOFF_ARTICLES) == {
        "Потеря потребительских свойств",
        "Списание овощи и фрукты",
    }


def test_build_losses_splits_groups():
    wo = pd.DataFrame(
        {
            "Дата": ["2026-08-12", "2026-08-12"],
            "Магазин": ["Автодом", "Автодом"],
            "Статья списания": list(COMMODITY_WRITEOFF_ARTICLES),
            "Сумма": [1000.0, 500.0],
        }
    )
    exp = pd.DataFrame(
        {
            "Дата": ["2026-08-12"],
            "Магазин": ["Автодом"],
            "Статья списания": ["Обед персонала"],
            "Сумма": [200.0],
        }
    )
    inv = pd.DataFrame(
        {
            "Дата": ["2026-08-12"],
            "Магазин": ["Автодом"],
            "Сумма": [300.0],
        }
    )
    out = build_pbi_losses_day(wo, inv, writeoff_all=wo, expenses=exp)
    groups = set(out["Группа"].astype(str))
    assert "Списания" in groups
    assert "Расходы" in groups
    assert any("Недостач" in g for g in groups)
    assert "Списания (PBI)" not in set(out["Вид потерь"].astype(str))


def test_lfl_formula_blank_on_zero_ly():
    assert lfl_rto_pct(100, 0) is None
    assert abs(lfl_rto_pct(110, 100) - 10.0) < 1e-9


def test_money_format_mln():
    assert format_currency_mln(29_566_049) == "29,57 млн руб."
    assert format_money(29_566_049, unit="rub") == "29,57 млн руб."
    assert format_kpi_value(924, "ticket") == "924,00 руб."


def test_avg_ticket_pbi_parity_no_x1000():
    raw = {
        "meta": {"Название сети": "Зеленое Яблоко", "Текущий день": "2026-08-12"},
        "_pbi_parity": True,
        "_money_unit": "rub",
        "_report_day": "2026-08-12",
        "_ly_available": False,
        "_plan_available": False,
        "sales_day": pd.DataFrame(
            {
                "Дата": ["2026-08-12", "2026-08-12"],
                "Магазин": ["А", "Б"],
                "Выручка факт": [10_000_000.0, 5_000_000.0],
                "Выручка план": [0.0, 0.0],
                "Количество чеков": [10000.0, 5000.0],
            }
        ),
        "sales_week": pd.DataFrame(),
        "sales_month": pd.DataFrame(
            {
                "Месяц": ["2026-08", "2026-08"],
                "Магазин": ["А", "Б"],
                "Выручка факт": [10_000_000.0, 5_000_000.0],
                "Выручка план": [0.0, 0.0],
                "Количество чеков": [10000.0, 5000.0],
            }
        ),
        "availability_week": pd.DataFrame(),
        "sp_month": pd.DataFrame(),
        "losses_month": pd.DataFrame(
            {
                "Дата": ["2026-08-12", "2026-08-12"],
                "Магазин": ["А", "Б"],
                "Вид потерь": ["Потеря потребительских свойств", "Обед персонала"],
                "Группа": ["Списания", "Расходы"],
                "Статья списания": ["Потеря потребительских свойств", "Обед персонала"],
                "Сумма": [100_000.0, 50_000.0],
            }
        ),
        "penetration_week": pd.DataFrame(),
        "writeoff_week": pd.DataFrame(),
        "stock_month": pd.DataFrame(),
    }
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day")
    ticket = next(k for k in dash.kpis if k.code == "avg_ticket_day")
    assert abs(ticket.value - 1000.0) < 0.5  # 15M / 15k
    assert ticket.value < 5000  # not 1_000_000
    # Спи = РТО С: статья Обед входит в списания магазина Б
    row_a = next(r for r in dash.store_table if r.store == "А")
    row_b = next(r for r in dash.store_table if r.store == "Б")
    assert abs(row_a.losses - 100_000) < 1
    assert abs(row_b.losses - 50_000) < 1
    assert all(r.yoy is None for r in dash.store_table)
    assert "1,056" not in str(dash.model_dump())
    assert any(k.code == "lfl_rto" for k in dash.kpis)


def test_no_pseudo_pbi_writeoff_row():
    raw = {
        "meta": {"Название сети": "Зеленое Яблоко"},
        "_pbi_parity": True,
        "_money_unit": "rub",
        "_report_day": "2026-08-12",
        "_ly_available": False,
        "_plan_available": False,
        "sales_day": pd.DataFrame(
            {
                "Дата": ["2026-08-12"],
                "Магазин": ["А"],
                "Выручка факт": [1_000_000.0],
                "Выручка план": [0.0],
                "Количество чеков": [1000.0],
            }
        ),
        "sales_week": pd.DataFrame(),
        "sales_month": pd.DataFrame(
            {
                "Месяц": ["2026-08"],
                "Магазин": ["А"],
                "Выручка факт": [1_000_000.0],
                "Выручка план": [0.0],
                "Количество чеков": [1000.0],
            }
        ),
        "availability_week": pd.DataFrame(),
        "sp_month": pd.DataFrame(),
        "losses_month": pd.DataFrame(
            {
                "Дата": ["2026-08-12", "2026-08-12"],
                "Магазин": ["А", "А"],
                "Вид потерь": ["Потеря потребительских свойств", "Списание овощи и фрукты"],
                "Группа": ["Списания", "Списания"],
                "Сумма": [10_000.0, 5_000.0],
            }
        ),
        "penetration_week": pd.DataFrame(),
        "writeoff_week": pd.DataFrame(),
        "stock_month": pd.DataFrame(),
    }
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day")
    names = [x.group for x in dash.losses]
    assert "Списания (PBI)" not in names
    assert "Потеря потребительских свойств" in names
