"""Тесты формул KPI (каталог M01–M29) и end-to-end MetricsService."""
from __future__ import annotations

from app.core.business_metrics import (
    PLAN_GREEN,
    PLAN_YELLOW,
    availability_pct,
    avg_ticket,
    penetration_pct,
    plan_completion_pct,
    status_plan_pct,
)
from app.core.config import DEFAULT_EXCEL_FILE
from app.core.data_source import configured_data_source_mode
from app.ingestion import ingest_excel
from app.ingestion.sample_inputs import build_alias_shuffled_workbook, build_clean_workbook
from app.services.metrics_service import MetricsService


def test_data_source_default_is_excel(monkeypatch):
    monkeypatch.delenv("DATA_SOURCE_MODE", raising=False)
    monkeypatch.delenv("WARROOM_DATA_SOURCE", raising=False)
    assert configured_data_source_mode() == "excel"


def test_plan_traffic_light_matches_catalog_m03():
    assert status_plan_pct(PLAN_GREEN) == "green"
    assert status_plan_pct(PLAN_YELLOW) == "yellow"
    assert status_plan_pct(98.5) == "red"
    assert plan_completion_pct(100, 100) == 100.0
    assert abs(plan_completion_pct(99, 100) - 99.0) < 1e-9


def test_penetration_and_availability_formulas():
    assert penetration_pct(25, 100) == 25.0
    assert availability_pct(90, 100) == 90.0
    assert avg_ticket(10_000, 50) == 200.0


def test_pilot_fixed_template_end_to_end():
    path = DEFAULT_EXCEL_FILE
    assert path.exists(), f"missing pilot excel: {path}"
    res = ingest_excel(str(path), filename=path.name)
    assert res.ok and res.has_store_data
    for period in ("day", "week", "month"):
        dash = MetricsService(res.raw, mode="excel").build_dashboard(period=period)
        assert len(dash.kpis) == 5
        assert len(dash.store_table) >= 1
        assert dash.kpis[0].value is not None


def test_alias_shuffled_workbook_builds_dashboard():
    res = ingest_excel(build_alias_shuffled_workbook(), filename="alias.xlsx")
    assert res.ok and res.has_store_data
    assert "Выручка факт" in res.raw["sales_month"].columns
    assert "Выручка план" in res.raw["sales_month"].columns  # defaulted
    dash = MetricsService(res.raw, mode="excel").build_dashboard(period="month")
    assert len(dash.store_table) == 2
    week = MetricsService(res.raw, mode="excel").build_dashboard(period="week")
    sp = next(k for k in week.kpis if k.code == "sp_penetration")
    assert sp.value > 0  # from penetration_week aliases
    # M29 inventory from loss_type
    store = next(r for r in dash.store_table if r.store == "Каспийск")
    assert store.inventory_shortage > 0


def test_clean_workbook_metrics_smoke():
    res = ingest_excel(build_clean_workbook(), filename="clean.xlsx")
    dash = MetricsService(res.raw, mode="excel").build_dashboard(period="month")
    assert dash.store_table
    assert status_plan_pct(dash.store_table[0].plan_pct) in {"green", "yellow", "red", "blue"}
