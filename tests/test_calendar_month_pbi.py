"""Месяц PBI = весь календарный месяц, не MTD до выбранного дня."""
from __future__ import annotations

import pandas as pd

from app.services.metrics_service import MetricsService
from app.services.sql_data_service import SqlDataService


def _aug_grain() -> pd.DataFrame:
    days = pd.date_range("2026-08-01", "2026-08-13", freq="D")
    rows = []
    for d in days:
        n_stores = 2 if d.day == 13 else 3
        stores = ["Автодом", "БКК", "Акушинка"][:n_stores]
        for i, s in enumerate(stores):
            rows.append(
                {
                    "Дата": d,
                    "Магазин": s,
                    "Выручка факт": 1_000_000.0 + i * 1000,
                    "Выручка план": 0.0,
                    "Количество чеков": 100.0,
                }
            )
    return pd.DataFrame(rows)


def test_pbi_month_is_full_calendar_month_not_mtd():
    svc = SqlDataService(use_env_db=False)
    raw = svc.empty_raw()
    raw["_metric_profile"] = "pbi"
    raw["_pbi_parity"] = True
    raw["_money_unit"] = "rub"
    raw["_anchor_date"] = "2026-08-01"
    raw["sales_day"] = _aug_grain()
    raw = svc._normalize_period_sheets(raw)
    assert raw["_month_from"] == "2026-08-01"
    assert raw["_month_to"] == "2026-08-12"  # 13-е неполное (2 из 3)
    month_rev = float(pd.to_numeric(raw["sales_month"]["Выручка факт"], errors="coerce").sum())
    day_rev = float(pd.to_numeric(raw["sales_day"]["Выручка факт"], errors="coerce").sum())
    # День 01.08 ≈ 3 млн; месяц 1–12 ≈ 36 млн, не 3 млн
    assert day_rev < 4_000_000
    assert month_rev > 30_000_000
    assert abs(month_rev - 12 * (1_000_000 + 1_001_000 + 1_002_000)) < 1


def test_pbi_month_lfl_uses_full_month_window():
    svc = SqlDataService(use_env_db=False)
    raw = svc.empty_raw()
    raw["_metric_profile"] = "pbi"
    raw["_pbi_parity"] = True
    raw["_money_unit"] = "rub"
    raw["_anchor_date"] = "2026-08-01"
    g26 = _aug_grain()
    g25 = g26.copy()
    g25["Дата"] = pd.to_datetime(g25["Дата"]) - pd.DateOffset(years=1)
    g25["Выручка факт"] = g25["Выручка факт"] / 1.0808  # ~8.08% LFL
    rto = pd.concat([g26, g25], ignore_index=True)
    raw["sales_day"] = g26
    raw["pbi_rto_day"] = rto
    raw = svc._normalize_period_sheets(raw)
    dash = MetricsService(raw, mode="sql").build_dashboard(period="month")
    lfl = next(k for k in dash.kpis if k.code == "lfl_rto")
    assert lfl.value is not None
    assert abs(lfl.value - 8.08) < 0.05
    rev = next(k for k in dash.kpis if k.code == "revenue_month")
    assert rev.value > 30_000_000
