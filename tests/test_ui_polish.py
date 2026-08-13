"""UI polish: 2 decimals, Итого, store-sliced losses, no PBI jargon in KPI hints."""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.services.metrics_service import MetricsService
from app.services.sql_data_service import SqlDataService
from app.streamlit_ui.formatting import format_kpi_value, pct
from app.streamlit_ui.period_range import (
    default_period_range,
    default_yesterday,
    format_period_label,
    format_sync_caption,
)
from app.streamlit_ui.views import _losses_structure_rows


def _raw_two_stores() -> dict:
    return {
        "meta": {"Название сети": "Зеленое Яблоко", "Текущий день": "2026-08-12"},
        "_pbi_parity": True,
        "_money_unit": "rub",
        "_report_day": "2026-08-12",
        "_ly_available": False,
        "_plan_available": False,
        "sales_day": pd.DataFrame(
            {
                "Дата": ["2026-08-12", "2026-08-12"],
                "Магазин": ["Ленинград", "Автодом"],
                "Выручка факт": [10_000_000.0, 20_000_000.0],
                "Выручка план": [0.0, 0.0],
                "Количество чеков": [9000.0, 18000.0],
            }
        ),
        "sales_week": pd.DataFrame(),
        "sales_month": pd.DataFrame(
            {
                "Месяц": ["2026-08", "2026-08"],
                "Магазин": ["Ленинград", "Автодом"],
                "Выручка факт": [10_000_000.0, 20_000_000.0],
                "Выручка план": [0.0, 0.0],
                "Количество чеков": [9000.0, 18000.0],
            }
        ),
        "availability_week": pd.DataFrame(),
        "sp_month": pd.DataFrame(),
        "losses_month": pd.DataFrame(
            {
                "Дата": ["2026-08-12", "2026-08-12", "2026-08-12"],
                "Магазин": ["Ленинград", "Ленинград", "Автодом"],
                "Вид потерь": ["Хоз нужды", "Обед персонала", "Хоз нужды"],
                "Группа": ["Списания", "Расходы", "Списания"],
                "Статья списания": ["Хоз нужды", "Обед персонала", "Хоз нужды"],
                "Сумма": [400_000.0, 100_000.0, 800_000.0],
            }
        ),
        "penetration_week": pd.DataFrame(),
        "writeoff_week": pd.DataFrame(),
        "stock_month": pd.DataFrame(),
    }


def test_two_decimal_money_and_pct():
    assert format_kpi_value(4_500_000, "rub") == "4,50 млн руб."
    assert pct(4.87) == "4,87"
    assert format_kpi_value(51.2, "pct") == "51,20%"


def test_losses_structure_has_total_and_store_slice():
    raw = _raw_two_stores()
    net = MetricsService(raw, mode="sql").build_dashboard(period="day")
    net_groups = {x.group for x in net.losses}
    assert "Хоз нужды" in net_groups
    assert "Обед персонала" in net_groups
    net_amt = sum(x.amount for x in net.losses)
    assert abs(net_amt - 1_300_000) < 1

    store = MetricsService(raw, mode="sql").build_dashboard(period="day", store="Ленинград")
    store_amt = sum(x.amount for x in store.losses)
    assert abs(store_amt - 500_000) < 1
    assert all("Автодом" not in (x.group or "") for x in store.losses)

    rows = _losses_structure_rows([x.model_dump() for x in store.losses], "rub")
    assert rows[-1]["Статья"] == "Итого"
    assert "0,50 млн руб." in rows[-1]["Сумма"] or "500" in rows[-1]["Сумма"]
    assert rows[-1]["% вклада"] == "100,00%"


def test_store_kpi_lfl_uses_store_not_network():
    """Карточка LFL при фильтре магазина = LFL строки, не сети."""
    raw = _raw_two_stores()
    raw["_ly_available"] = True
    raw["_month_from"] = "2026-08-01"
    raw["_month_to"] = "2026-08-12"
    raw["pbi_rto_day"] = pd.DataFrame(
        {
            "Дата": (
                ["2026-08-12", "2026-08-12", "2025-08-12", "2025-08-12"]
            ),
            "Магазин": ["Ленинград", "Автодом", "Ленинград", "Автодом"],
            "Выручка факт": [10_000_000.0, 20_000_000.0, 20_000_000.0, 10_000_000.0],
        }
    )
    svc = MetricsService(raw, mode="sql")
    net = svc.build_dashboard(period="day")
    store = svc.build_dashboard(period="day", store="Ленинград")
    net_lfl = next(k for k in net.kpis if k.code == "lfl_rto")
    store_lfl = next(k for k in store.kpis if k.code == "lfl_rto")
    assert abs(net_lfl.value - 0.0) < 0.05
    assert abs(store_lfl.value - (-50.0)) < 0.05
    rev = next(k for k in store.kpis if k.code.startswith("revenue"))
    assert rev.yoy is not None
    assert abs(rev.yoy - (-50.0)) < 0.05


def test_month_kpis_put_penetration_after_lfl():
    raw = _raw_two_stores()
    raw["penetration_week"] = pd.DataFrame(
        {
            "Магазин": ["Ленинград", "Автодом"],
            "Чеков всего": [1000.0, 2000.0],
            "Чеков с СП": [400.0, 600.0],
            "Чеков с Паскуччи": [50.0, 80.0],
        }
    )
    dash = MetricsService(raw, mode="sql").build_dashboard(period="month")
    codes = [k.code for k in dash.kpis]
    assert "sp_penetration" in codes
    assert "pascucci_penetration" in codes
    assert codes.index("lfl_rto") < codes.index("sp_penetration")
    assert codes.index("sp_penetration") < codes.index("pascucci_penetration")
    pas = next(k for k in dash.kpis if k.code == "pascucci_penetration")
    assert "NEEDS_REVIEW" in (pas.hint or "")
    dd = dash.drilldown
    assert dd is not None
    card_codes = {k.code for k in dd.month_kpis}
    assert "month_sp_pen" in card_codes
    assert "month_pas_pen" in card_codes


def test_kpi_hints_have_no_pbi_jargon():
    dash = MetricsService(_raw_two_stores(), mode="sql").build_dashboard(period="month")
    blob = " ".join(f"{k.label} {k.hint or ''}" for k in dash.kpis)
    assert "DIVIDE" not in blob
    assert "1РТО И" not in blob
    assert "DATEADD" not in blob
    assert "Спи ТКПТ" not in blob
    assert "псевдо-агрегат" not in blob
    inv = next(k for k in dash.kpis if k.code == "inventory_shortage_month")
    assert "от выручки" in (inv.hint or "")
    lfl = next(k for k in dash.kpis if k.code == "lfl_rto")
    assert "DIVIDE" not in (lfl.hint or "")


def test_sync_caption_drops_cache_boilerplate():
    text = format_sync_caption({"_data_source": "local_cache", "_cache_synced_at": "2026-08-13T13:01:00+03:00"}, None)
    assert "локального кэша" not in text
    assert "Снимок на сервере" not in text
    assert "Данные обновлены из 1С" in text


def test_default_yesterday_and_period_label():
    assert default_yesterday(today=date(2026, 8, 13), max_day=date(2026, 8, 13)) == date(2026, 8, 12)
    assert format_period_label(date(2026, 8, 12), date(2026, 8, 12)) == "12.08.2026"
    assert format_period_label("2026-08-01", "2026-08-12") == "01.08.2026 – 12.08.2026"


def test_default_period_range_month_and_week():
    a = date(2026, 8, 1)
    mx = date(2026, 8, 13)
    assert default_period_range(a, "day", mx) == (a, a)
    w0, w1 = default_period_range(a, "week", mx)
    assert w0.weekday() == 0
    assert w1 >= w0
    m0, m1 = default_period_range(a, "month", mx)
    assert m0 == date(2026, 8, 1)
    assert m1 == date(2026, 8, 13)


def test_custom_range_slices_month_window():
    raw = {
        "sales_day": pd.DataFrame(
            {
                "Дата": pd.to_datetime(["2026-08-01", "2026-08-05", "2026-08-12"] * 2),
                "Магазин": ["Ленинград"] * 3 + ["Автодом"] * 3,
                "Выручка факт": [1_000_000.0, 2_000_000.0, 3_000_000.0, 1_000_000.0, 2_000_000.0, 3_000_000.0],
                "Выручка план": [0.0] * 6,
                "Количество чеков": [100.0] * 6,
            }
        ),
        "_anchor_date": "2026-08-01",
        "_metric_profile": "pbi",
        "_custom_from": "2026-08-01",
        "_custom_to": "2026-08-05",
        "_ui_period": "month",
    }
    out = SqlDataService(use_env_db=False)._normalize_period_sheets(raw)
    assert out["_month_from"] == "2026-08-01"
    assert out["_month_to"] == "2026-08-05"
    assert out["_week_from"] == "2026-08-01"
    assert out["_week_to"] == "2026-08-05"
    month = out["sales_month"]
    assert float(month["Выручка факт"].sum()) == 6_000_000.0
    assert float(out["sales_day"]["Выручка факт"].sum()) == 6_000_000.0
    assert float(out["sales_week"]["Выручка факт"].sum()) == 6_000_000.0


def test_custom_range_lfl_matches_selected_window():
    """LFL = DATEADD −1 YEAR по выбранным датам, не по календарному месяцу якоря."""
    raw = _raw_two_stores()
    raw["_ly_available"] = True
    raw["_report_day"] = "2026-08-12"
    raw["_custom_from"] = "2026-08-12"
    raw["_custom_to"] = "2026-08-12"
    raw["pbi_rto_day"] = pd.DataFrame(
        {
            "Дата": [
                "2026-08-01",
                "2026-08-12",
                "2025-08-01",
                "2025-08-12",
            ],
            "Магазин": ["Ленинград"] * 4,
            "Выручка факт": [10_000_000.0, 12_000_000.0, 8_000_000.0, 10_000_000.0],
        }
    )
    raw["sales_month"] = pd.DataFrame(
        {
            "Месяц": ["2026-08"],
            "Магазин": ["Ленинград"],
            "Выручка факт": [12_000_000.0],
            "Выручка план": [0.0],
            "Количество чеков": [1000.0],
        }
    )
    day = MetricsService(raw, mode="sql").build_dashboard(period="month")
    lfl = next(k for k in day.kpis if k.code == "lfl_rto")
    assert abs(lfl.value - 20.0) < 0.05  # 12M / 10M − 1
    raw["_custom_from"] = "2026-08-01"
    raw["_custom_to"] = "2026-08-12"
    raw["sales_month"] = pd.DataFrame(
        {
            "Месяц": ["2026-08"],
            "Магазин": ["Ленинград"],
            "Выручка факт": [22_000_000.0],
            "Выручка план": [0.0],
            "Количество чеков": [2000.0],
        }
    )
    month = MetricsService(raw, mode="sql").build_dashboard(period="month")
    lfl_m = next(k for k in month.kpis if k.code == "lfl_rto")
    assert abs(lfl_m.value - (22_000_000 / 18_000_000 - 1) * 100) < 0.05
    assert month.meta["period_label"] == "01.08.2026 – 12.08.2026"
