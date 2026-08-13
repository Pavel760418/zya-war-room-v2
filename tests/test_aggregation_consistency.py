"""Регрессия: день⊂неделя⊂месяц и магазин⊂сеть для выручки/чеков/потерь."""
from __future__ import annotations

import pandas as pd

from app.services.metrics_service import MetricsService
from app.services.sql_data_service import SqlDataService


def _raw_two_days() -> dict:
    """Фикстура: Акушинка 09+10.08 и второй магазин; потери по дням."""
    grain = pd.DataFrame(
        {
            "Дата": pd.to_datetime(
                ["2026-08-09", "2026-08-10", "2026-08-09", "2026-08-10"]
            ),
            "Магазин": ["Акушинка", "Акушинка", "БКК", "БКК"],
            "Выручка факт": [2_111_162.41, 2_141_430.61, 3_000_000.0, 3_200_000.0],
            "Выручка план": [0.0, 0.0, 0.0, 0.0],
            "Количество чеков": [1944.0, 2163.0, 4000.0, 4200.0],
        }
    )
    svc = SqlDataService(use_env_db=False)
    raw = svc.empty_raw()
    raw["_metric_profile"] = "legacy"
    raw["sales_day"] = grain
    raw["losses_month"] = pd.DataFrame(
        {
            "Дата": pd.to_datetime(
                ["2026-08-09", "2026-08-10", "2026-08-10", "2026-08-09", "2026-08-10"]
            ),
            "Магазин": ["Акушинка", "Акушинка", "Акушинка", "БКК", "БКК"],
            "Вид потерь": [
                "Хоз нужды",
                "Хоз нужды",
                "Инвентаризация",
                "Хоз нужды",
                "Инвентаризация",
            ],
            "Сумма": [50_000.0, 60_000.0, 20_000.0, 80_000.0, 10_000.0],
        }
    )
    raw["writeoff_week"] = pd.DataFrame(
        {
            "Дата": pd.to_datetime(["2026-08-09", "2026-08-10"]),
            "Магазин": ["Акушинка", "Акушинка"],
            "Статья списания": ["Хоз нужды", "Хоз нужды"],
            "Сумма": [50_000.0, 60_000.0],
        }
    )
    raw["penetration_week"] = pd.DataFrame(
        {
            "Дата": pd.to_datetime(["2026-08-09", "2026-08-10"]),
            "Магазин": ["Акушинка", "Акушинка"],
            "Чеков всего": [1944.0, 2163.0],
            "Чеков с СП": [400.0, 500.0],
            "Чеков с Паскуччи": [20.0, 30.0],
        }
    )
    return svc._normalize_period_sheets(raw)


def test_day_week_month_sales_consistency():
    raw = _raw_two_days()
    assert raw["_report_day"] == "2026-08-10"
    day = MetricsService(raw, mode="sql").rows("day")
    week = MetricsService(raw, mode="sql").rows("week")
    month = MetricsService(raw, mode="sql").rows("month")

    aku_day = next(r for r in day if r.store == "Акушинка")
    aku_week = next(r for r in week if r.store == "Акушинка")
    aku_month = next(r for r in month if r.store == "Акушинка")

    assert aku_day.checks == 2163
    assert abs(aku_day.revenue - 2141.43061) < 0.1
    # 09+10 в одном 7-дневном окне и в августе
    assert aku_week.checks == 1944 + 2163
    assert abs(aku_week.revenue - (2_111_162.41 + 2_141_430.61) / 1000) < 0.2
    assert aku_month.checks == aku_week.checks
    assert abs(aku_month.revenue - aku_week.revenue) < 0.2


def test_store_sum_equals_network():
    raw = _raw_two_days()
    m = MetricsService(raw, mode="sql")
    for period in ("day", "week", "month"):
        rows = m.rows(period)
        net = m.build_dashboard(period=period, store=None)
        assert abs(sum(r.revenue for r in rows) - sum(r.revenue for r in net.store_table)) < 0.01
        assert abs(sum(r.checks for r in rows) - sum(r.checks or 0 for r in net.store_table)) < 0.01
        assert abs(sum(r.losses or 0 for r in rows) - sum(r.losses or 0 for r in net.store_table)) < 0.01


def test_losses_and_shortage_non_zero_and_period_aligned():
    raw = _raw_two_days()
    m = MetricsService(raw, mode="sql")
    day = next(r for r in m.rows("day") if r.store == "Акушинка")
    week = next(r for r in m.rows("week") if r.store == "Акушинка")
    assert day.losses > 0
    assert day.inventory_shortage > 0
    assert week.losses > day.losses  # 09+10 > только 10
    assert abs(week.losses - (50 + 60)) < 0.2  # тыс. руб., без недостач
    assert abs(week.inventory_shortage - 20) < 0.2
    dash_week = m.build_dashboard(period="week", store="Акушинка")
    writeoff_kpi = next(k for k in dash_week.kpis if k.code == "writeoff_pct")
    assert writeoff_kpi.value > 0
    inv_kpi = next(k for k in dash_week.kpis if k.code == "inventory_shortage")
    assert inv_kpi.value > 0


def test_aug9_plus_aug10_in_week_window():
    """Контроль: 1944+2163 чека Акушинки входят в неделю, оканчивающуюся 10.08."""
    raw = _raw_two_days()
    week = next(r for r in MetricsService(raw, mode="sql").rows("week") if r.store == "Акушинка")
    assert week.checks == 4107
    assert abs(week.revenue - 4_252_593.02 / 1000) < 0.2


def test_revenue_formatting_not_crushed_for_week_scale():
    from app.streamlit_ui.formatting import format_currency_thousands

    # 15 076 тыс. → 15,08 млн руб.
    assert format_currency_thousands(15075.9) == "15,08 млн руб."
