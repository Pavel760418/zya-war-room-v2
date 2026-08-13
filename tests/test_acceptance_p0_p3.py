"""Регрессии приёмки P0–P3: ранжирование, термины, _Marked, UX-прозрачность."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.ingestion import sql_extract
from app.services.metrics_service import RANKING_METRIC_LABEL, MetricsService, RANK_MEDIAN_FLOOR
from app.services.sql_data_service import SqlDataService
from app.streamlit_ui.render import hero_html, store_table_html
from tests.test_uat_regressions import _fixture_raw

ROOT = Path(__file__).resolve().parents[1]
UI_GLOBS = [
    "app/streamlit_app.py",
    "streamlit_app.py",
    "app/streamlit_ui/*.py",
    "app/services/metrics_service.py",
    "app/static/index.html",
]


def test_micro_stores_excluded_from_leaders():
    """Магазины с выручкой <40% медианы не попадают в Лидеры."""
    raw = _fixture_raw(with_plan=False)
    # Добавим микромагазин с нулевыми потерями — раньше ошибочно становился «лидером»
    day = raw["sales_day"].copy()
    micro = day.iloc[0:1].copy()
    micro["Магазин"] = "Яблоко 101"
    micro["Выручка факт"] = 50_000.0  # << медианы
    micro["Количество чеков"] = 20.0
    raw["sales_day"] = pd.concat([day, micro], ignore_index=True)
    raw["losses_month"] = pd.concat(
        [
            raw["losses_month"],
            pd.DataFrame(
                {
                    "Дата": pd.to_datetime(["2026-08-10"]),
                    "Магазин": ["Яблоко 101"],
                    "Вид потерь": ["Хоз нужды"],
                    "Сумма": [0.0],
                }
            ),
        ],
        ignore_index=True,
    )
    m = MetricsService(raw, mode="sql")
    top, bottom, insufficient = m.rank_stores(m.rows("day"), n=5)
    assert all(r.store != "Яблоко 101" for r in top)
    assert any(r.store == "Яблоко 101" for r in insufficient)
    dash = m.build_dashboard(period="day")
    assert "Яблоко 101" not in {r.store for r in dash.top_stores}
    assert "Яблоко 101" in dash.meta.get("insufficient_stores", [])
    assert RANK_MEDIAN_FLOOR == 0.40
    assert "40%" in dash.meta["ranking_metric"] or "40" in dash.meta["ranking_metric"]


def test_terminology_forbidden_user_facing_duplicates():
    """Запрещённые жаргон/дубли терминов в пользовательском UI-коде."""
    forbidden = [
        "кокпит",
        "из SQL",
        "нет данных за LY",
        ">СП %<",
        "СП дост.",
        ">Недостача<",
    ]
    # Допустимо только «Недостачи» (мн.ч.) и «Доля СП» / «Доступность СП»
    hits: list[str] = []
    for pattern in UI_GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in forbidden:
                if token in text:
                    hits.append(f"{path.relative_to(ROOT)}: {token}")
    assert hits == [], "запрещённые термины в UI:\n" + "\n".join(hits)


def test_yoy_uses_full_phrase_not_ly_abbr():
    raw = _fixture_raw(with_plan=False)
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day")
    html = store_table_html([r.model_dump() for r in dash.store_table], ly_available=False)
    assert "нет данных" in html
    assert "нет данных за LY" not in html


def test_hero_panel_title_and_focus():
    raw = _fixture_raw(with_plan=False)
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day").model_dump()
    html = hero_html(dash)
    assert "Панель управления сетью" in html
    assert "кокпит" not in html.lower()
    assert "Главный фокус" in html
    assert dash["meta"].get("focus_text")


def test_loss_drivers_and_network_context_in_drilldown():
    raw = _fixture_raw(with_plan=False)
    m = MetricsService(raw, mode="sql")
    dd = m.build_drilldown_for_store("Сити", period="day")
    assert dd is not None
    assert dd.loss_drivers, "ожидались top-статьи потерь"
    assert dd.network_context, "ожидался контекст vs медиана сети"
    assert any("медиан" in x.lower() for x in dd.network_context)


def test_marked_filter_on_writeoff_and_inventory_sql():
    """Превентивный фильтр _Marked=0 во всех запросах списаний/инвентаризации."""
    blobs = [
        sql_extract._SQL_WRITEOFF,
        sql_extract._SQL_LOSSES,
    ]
    repo = (ROOT / "app/repositories/retail_inventory_repository.py").read_text(encoding="utf-8")
    for blob in blobs:
        assert "d._Marked = 0x00" in blob or "d._Marked=0x00" in blob.replace(" ", "")
    assert "DOC_WRITEOFF" in repo and "d._Marked = 0x00" in repo
    assert "DOC_INVENTORY" in repo
    # оба метода содержат фильтр
    assert repo.count("d._Marked = 0x00") >= 2


def test_missing_store_note_dynamic():
    grain = pd.DataFrame(
        {
            "Дата": pd.to_datetime(["2026-08-10"] * 5 + ["2026-08-11"] * 4),
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
    note = raw.get("_report_note") or ""
    assert "Данные за 11.08" in note
    assert "4 из 5" in note
    assert "Нет данных: M4" in note
    assert "последнее закрытие: 10.08" in note


def test_kpi_and_table_use_nedostachi_plural_and_dolia_sp():
    raw = _fixture_raw(with_plan=False)
    dash_m = MetricsService(raw, mode="sql").build_dashboard(period="month")
    labels = {k.label for k in dash_m.kpis}
    assert "Недостачи" in labels
    assert "Доля СП" in labels
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day")
    html = store_table_html([r.model_dump() for r in dash.store_table], ly_available=False)
    assert "Недостачи" in html
    assert "Доля СП" in html
    assert "Доступность СП" in html
    assert "СП %" not in html
