"""Регрессии по скрин-замечаниям UI (термины, фокус, лидеры≠аутсайдеры)."""
from __future__ import annotations

from pathlib import Path

from app.services.metrics_service import ABBREVIATIONS, MetricsService
from app.streamlit_ui.render import abbr_legend_html, drilldown_html, hero_html, store_table_html
from tests.test_uat_regressions import _fixture_raw

ROOT = Path(__file__).resolve().parents[1]
UI_PATHS = [
    ROOT / "streamlit_app.py",
    ROOT / "app" / "streamlit_app.py",
    ROOT / "app" / "streamlit_ui" / "render.py",
    ROOT / "app" / "streamlit_ui" / "views.py",
    ROOT / "app" / "services" / "metrics_service.py",
]


def test_no_forbidden_ui_strings_from_screenshots():
    forbidden = [
        "левый",
        "Акванина",
        "Ак ванина",
        "Аутсиеры",
        "Аутсиры",
        "не задание",
        "глюкоза",
        "Как читать руку",
        "истекающим сроком",
        "неполные",
        ">моб<",
        "киски",
        "дешево",
        "почта опоса",
    ]
    hits = []
    for path in UI_PATHS:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                hits.append(f"{path.name}: {token}")
    assert hits == [], "запрещённые строки:\n" + "\n".join(hits)


def test_alert_severity_labels_are_readable():
    from app.streamlit_ui.render import alerts_html

    html = alerts_html(
        [
            {"title": "План — не задан", "severity": "blue", "comment": "тест", "store": None},
            {"title": "Высокие потери", "severity": "yellow", "comment": "тест", "store": "Акушинка"},
            {"title": "Просадка СП", "severity": "red", "comment": "тест", "store": "Шамиля 10"},
        ]
    )
    assert "Инфо" in html
    assert "Внимание" in html
    assert "Критично" in html
    for bad in ("киски", "дешево", "инфо</span>", "внимание</span>"):
        assert bad not in html


def test_frov_means_fruits_vegetables():
    assert ABBREVIATIONS["ФРОВ"].lower().startswith("фрукт")
    html = abbr_legend_html(ABBREVIATIONS)
    assert "Сокращения" in html
    assert "руку" not in html
    assert "истекающ" not in html
    assert "Фрукты и овощи" in html


def test_hero_labels_store_and_coverage():
    raw = _fixture_raw(with_plan=False)
    raw["_report_incomplete"] = True
    raw["_report_stores"] = 14
    raw["_report_stores_max"] = 15
    dash = MetricsService(raw, mode="sql").build_dashboard(period="month", store="Акушинка").model_dump()
    # Hero теперь native Streamlit; проверяем данные дашборда и HTML-фолбэк
    assert dash["selection"]["store"] == "Акушинка" or dash.get("scope") == "store"
    html = hero_html(dash)
    assert "Магазин" in html
    assert "левый" not in html
    assert "Акванина" not in html
    assert "Охват данных" in html
    assert "неполные" not in html
    assert "14 из 15" in html or "охват" in html.lower()


def test_native_store_table_labels():
    from app.streamlit_ui.views import _store_table_df

    raw = _fixture_raw(with_plan=False)
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day")
    df = _store_table_df(
        [r.model_dump() for r in dash.store_table],
        ly_available=False,
        plan_available=False,
    )
    assert list(df.columns)[0] == "Магазин"
    assert "левый" not in df.columns
    assert (df["План"] == "не задан").all()
    assert "не задание" not in " ".join(df["План"].astype(str))
    assert set(df["Риск"]).issubset({"Низкий", "Средний", "Высокий"})


def test_focus_not_equal_to_median_when_network_has_outliers():
    raw = _fixture_raw(with_plan=False)
    # Даже при фильтре одного магазина фокус и медиана считаются по сети
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day", store="Акушинка")
    text = dash.meta["focus_text"]
    assert "Главный фокус:" in text
    # Сити — явный аутсайдер по потерям в фикстуре
    assert "Сити" in text
    assert "Акушинка" not in text or "отклонение" in text
    # потери фокуса и медиана не должны совпадать на 2 знака в этой фикстуре
    assert "отклонение +0.00" not in text.replace(",", ".")


def test_same_store_cannot_be_leader_and_outsider():
    raw = _fixture_raw(with_plan=False)
    for period in ("day", "week", "month"):
        for store in (None, "Акушинка"):
            dash = MetricsService(raw, mode="sql").build_dashboard(period=period, store=store)
            top = {r.store for r in dash.top_stores}
            bottom = {r.store for r in dash.bottom_stores}
            assert top.isdisjoint(bottom), f"пересечение при period={period} store={store}: {top & bottom}"


def test_single_store_rank_source_uses_network():
    raw = _fixture_raw(with_plan=False)
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day", store="Акушинка")
    # Таблица — один магазин, рейтинг — по сети
    assert len(dash.store_table) == 1
    assert dash.store_table[0].store == "Акушинка"
    assert len(dash.top_stores) >= 1
    assert len(dash.bottom_stores) >= 1
    assert {r.store for r in dash.top_stores}.isdisjoint({r.store for r in dash.bottom_stores})


def test_plan_and_risk_labels_in_table():
    raw = _fixture_raw(with_plan=False)
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day")
    html = store_table_html(
        [r.model_dump() for r in dash.store_table],
        ly_available=False,
        plan_available=False,
    )
    assert "Магазин" in html
    assert "не задан" in html
    assert "не задание" not in html
    for r in dash.store_table:
        assert r.risk_level in {"низкий", "средний", "высокий"}
    assert "Низкий" in html or "Средний" in html or "Высокий" in html
    assert "глюкоза" not in html
    for bad in ("га</span>", "глюкоза", "левый", "blue</span>", "yellow</span>"):
        assert bad not in html


def test_drilldown_names_store_explicitly():
    raw = _fixture_raw(with_plan=False)
    dash = MetricsService(raw, mode="sql").build_dashboard(period="day")
    html = drilldown_html(dash.drilldown.model_dump())
    assert "Магазин:" in html
    assert dash.drilldown.store in html
    assert ">op<" not in html
    assert "моб" not in html


def test_period_labels_include_day():
    from streamlit_app import PERIOD_LABELS, PERIOD_BY_LABEL

    assert PERIOD_LABELS["day"] == "День"
    assert PERIOD_BY_LABEL["День"] == "day"
    assert "моб" not in PERIOD_LABELS.values()
