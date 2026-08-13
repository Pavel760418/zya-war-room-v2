"""Регрессии UAT: ранжирование, карточка периодов, риск без плана, остатки, план/LY."""
from __future__ import annotations

import pandas as pd

from app.services.metrics_service import RANKING_METRIC_LABEL, MetricsService
from app.services.sql_data_service import SqlDataService
from app.streamlit_ui.render import hero_html, store_table_html


def _fixture_raw(*, with_plan: bool = False) -> dict:
    plan = 1_000_000.0 if with_plan else 0.0
    grain = pd.DataFrame(
        {
            "Дата": pd.to_datetime(
                [
                    "2026-08-09",
                    "2026-08-10",
                    "2026-08-09",
                    "2026-08-10",
                    "2026-08-09",
                    "2026-08-10",
                ]
            ),
            "Магазин": ["Акушинка", "Акушинка", "БКК", "БКК", "Сити", "Сити"],
            "Выручка факт": [
                2_000_000.0,
                2_100_000.0,
                3_000_000.0,
                3_200_000.0,
                1_500_000.0,
                1_600_000.0,
            ],
            "Выручка план": [plan] * 6,
            "Количество чеков": [2000.0, 2100.0, 4000.0, 4200.0, 1500.0, 1600.0],
        }
    )
    svc = SqlDataService(use_env_db=False)
    raw = svc.empty_raw()
    raw["_metric_profile"] = "legacy"
    raw["sales_day"] = grain
    raw["losses_month"] = pd.DataFrame(
        {
            "Дата": pd.to_datetime(
                ["2026-08-10", "2026-08-10", "2026-08-10", "2026-08-10", "2026-08-10", "2026-08-10"]
            ),
            "Магазин": ["Акушинка", "Акушинка", "БКК", "БКК", "Сити", "Сити"],
            "Вид потерь": [
                "Хоз нужды",
                "Инвентаризация",
                "Хоз нужды",
                "Инвентаризация",
                "Хоз нужды",
                "Инвентаризация",
            ],
            # Сити — высокие потери %, БКК — низкие
            "Сумма": [40_000.0, 20_000.0, 10_000.0, 5_000.0, 120_000.0, 80_000.0],
        }
    )
    raw["availability_week"] = pd.DataFrame(
        {
            "Магазин": ["Акушинка", "БКК", "Сити"],
            "Топ ТЗ всего позиций": [100, 100, 100],
            "Топ ТЗ доступно позиций": [96, 97, 50],
            "Топ СП всего позиций": [50, 50, 50],
            "Топ СП доступно позиций": [47, 48, 20],
        }
    )
    raw["sp_month"] = pd.DataFrame(
        {
            "Магазин": ["Акушинка", "БКК", "Сити"],
            "Выручка СП": [700_000.0, 1_200_000.0, 200_000.0],
            "Выручка всего": [2_100_000.0, 3_200_000.0, 1_600_000.0],
        }
    )
    raw["stock_month"] = pd.DataFrame(
        {
            "Магазин": ["Акушинка", "БКК", "Сити"],
            "Остатки на конец месяца факт": [10_000_000.0, 12_000_000.0, 8_000_000.0],
            "Остатки на конец месяца план": [0.0, 0.0, 0.0],
        }
    )
    raw = svc._normalize_period_sheets(raw)
    raw["_ly_available"] = False
    return raw


def test_leaders_not_equal_outsiders_without_plan():
    raw = _fixture_raw(with_plan=False)
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day")
    top = {r.store for r in dash.top_stores}
    bottom = {r.store for r in dash.bottom_stores}
    assert top, "ожидались лидеры"
    assert bottom, "ожидались аутсайдеры"
    assert top != bottom
    assert top.isdisjoint(bottom) or len(dash.store_table) < 4
    assert dash.meta["ranking_metric"] == RANKING_METRIC_LABEL
    # БКК с низкими потерями — лидер; Сити с высокими — аутсайдер
    assert "БКК" in top
    assert "Сити" in bottom


def test_leaders_not_equal_outsiders_with_plan():
    raw = _fixture_raw(with_plan=True)
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day")
    assert {r.store for r in dash.top_stores} != {r.store for r in dash.bottom_stores}


def test_drilldown_three_periods_independent():
    raw = _fixture_raw(with_plan=False)
    # Добавим второй день явно в week/month отличие
    m = MetricsService(raw, mode="sql")
    dd = m.build_drilldown_for_store("Акушинка")
    assert dd is not None
    day_rev = next(k.value for k in dd.day_kpis if k.code == "day_revenue")
    week_rev = next(k.value for k in dd.week_kpis if k.code == "week_revenue")
    month_rev = next(k.value for k in dd.month_kpis if k.code == "month_revenue")
    assert day_rev != week_rev
    assert abs(week_rev - month_rev) < 0.2  # оба дня в одном месяце
    assert abs(week_rev - (2_000_000 + 2_100_000) / 1000) < 0.5


def test_risk_independent_of_missing_plan():
    raw = _fixture_raw(with_plan=False)
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day")
    assert all(r.plan_pct is None for r in dash.store_table)
    risks = {r.risk_level for r in dash.store_table}
    assert len(risks) >= 2, f"риск должен дифференцироваться, получено {risks}"
    plan_alerts = [a for a in dash.alerts if a.title == "План под риском"]
    assert plan_alerts == []
    assert any(a.title == "План — не задан" for a in dash.alerts)


def test_yoy_not_synthetic_constant():
    raw = _fixture_raw(with_plan=False)
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day")
    assert all(r.yoy is None for r in dash.store_table)
    html = store_table_html([r.model_dump() for r in dash.store_table], ly_available=False)
    assert "нет данных" in html
    assert "5,6" not in html


def test_stock_hints_have_no_legacy_120d_or_accumrg6601():
    raw = _fixture_raw(with_plan=False)
    dash = MetricsService(raw, mode="sql").build_dashboard(period="month")
    blob = " ".join((k.hint or "") for k in dash.kpis)
    assert "_AccumRg6601" not in blob
    assert "120д" not in blob
    assert "_Document" not in blob
    dd = dash.drilldown
    assert dd is not None
    stock_hint = next(k.hint for k in dd.month_kpis if k.code == "month_stock")
    assert "120д" not in stock_hint
    assert "_AccumRg" not in stock_hint


def test_hero_period_is_russian():
    raw = _fixture_raw(with_plan=False)
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day").model_dump()
    html = hero_html(dash)
    assert "DAY" not in html
    assert "День" in html


def test_day_kpi_includes_losses_pct():
    raw = _fixture_raw(with_plan=False)
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day")
    codes = {k.code for k in dash.kpis}
    assert "losses_pct_day" in codes
    assert next(k for k in dash.kpis if k.code == "losses_pct_day").label.startswith("Списания")


def test_avg_ticket_keeps_kopecks_precision():
    raw = _fixture_raw(with_plan=False)
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day")
    avg = next(k for k in dash.kpis if k.code == "avg_ticket_day")
    # сеть: sum revenue rub / checks
    expected = (2.1e6 + 3.2e6 + 1.6e6) / (2100 + 4200 + 1600)
    assert abs(avg.value - expected) < 0.05


def test_report_day_majority_threshold():
    """День с 80%+ магазинов предпочтительнее более полного, но более старого."""
    grain = pd.DataFrame(
        {
            "Дата": pd.to_datetime(
                ["2026-08-10"] * 5 + ["2026-08-11"] * 4
            ),
            "Магазин": [f"M{i}" for i in range(5)] + [f"M{i}" for i in range(4)],
            "Выручка факт": [1000.0] * 9,
            "Выручка план": [0.0] * 9,
            "Количество чеков": [10.0] * 9,
        }
    )
    svc = SqlDataService(use_env_db=False)
    raw = svc.empty_raw()
    raw["_metric_profile"] = "legacy"
    raw["sales_day"] = grain
    raw = svc._normalize_period_sheets(raw)
    # max=5, threshold=ceil(4)=4 → 11.08 с 4 магазинами (legacy 80%)
    assert raw["_report_day"] == "2026-08-11"
    assert raw["_report_incomplete"] is True
