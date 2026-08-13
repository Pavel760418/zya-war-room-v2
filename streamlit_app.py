"""Streamlit entrypoint: МегаМетрики — панель управления сетью «Зеленое Яблоко».

Пользовательский путь данных — локальный SQLite-кэш на сервере приложения.
Прямой MSSQL 1С используется только sync-скриптом и режимом диагностики.
"""
from __future__ import annotations

import os
from datetime import date

import streamlit as st

from app.ingestion.sql_extract import NON_STORE_NAMES
from app.streamlit_ui.data_access import (
    available_filters,
    build_dashboard_safe,
    load_sql_result,
    render_sql_connection_error,
    sql_connection_status,
)
from app.streamlit_ui.maintenance import gate_or_continue
from app.streamlit_ui.roles import (
    activate_admin_from_query,
    is_admin,
    render_admin_unlock_sidebar,
    show_tech_sidebar,
)
from app.streamlit_ui.period_range import HISTORY_MIN, default_yesterday, format_period_label, format_sync_caption
from app.streamlit_ui.theme import inject_theme, render_theme_toggle
from app.streamlit_ui.views import render_body, render_hero

st.set_page_config(
    page_title="AI Агент МегаМетрики — панель управления сетью",
    page_icon="🍏",
    layout="wide",
    initial_sidebar_state="collapsed",
)

if not gate_or_continue():
    st.stop()

activate_admin_from_query()
st.session_state.setdefault("ui_theme", "dark")
inject_theme()

PERIOD_LABELS = {"day": "День", "week": "Неделя", "month": "Месяц"}
PERIOD_BY_LABEL = {v: k for k, v in PERIOD_LABELS.items()}
_ALL_STORES = "Все магазины"
_SHOW_SQL_DIAG = os.environ.get("SHOW_SQL_DIAGNOSTICS", "0").strip().lower() in {"1", "true", "yes"}
_HISTORY_MIN = HISTORY_MIN


def _is_operational_store(name: str) -> bool:
    n = (name or "").strip()
    if not n or n in NON_STORE_NAMES:
        return False
    if n.startswith("РЦ") or n.startswith("не исп"):
        return False
    if n.lower() in {"все товары", "ритейл"}:
        return False
    return True


def _format_sync_caption(raw: dict, sql_result) -> str:
    return format_sync_caption(raw, sql_result)


ss = st.session_state
ss.setdefault("sql_refresh", 0)

# Sidebar: полный техблок только для admin; обычным — минимум
if show_tech_sidebar():
    with st.sidebar:
        st.markdown("##### AI Агент МегаМетрики · admin")
        render_theme_toggle(location="sidebar")
        render_admin_unlock_sidebar()
        nav = st.radio("Навигация", ["Дашборд", "Диагностика данных"], index=0, key="nav_main")
        st.divider()
        status = sql_connection_status()
        if status.ok:
            st.success("Данные: доступны")
            st.caption(f"Хранилище: {status.database or '—'} · источник: {status.server or '—'}")
        else:
            st.error("Данные недоступны")
        if st.button("Обновить отображение", width="stretch", key="btn_refresh_all"):
            ss.sql_refresh = int(ss.sql_refresh) + 1
            st.cache_data.clear()
            st.rerun()
        st.caption("Техническая панель видна только администратору.")
else:
    nav = "Дашборд"
    # Hidden admin entry via query already handled; tiny caption
    with st.sidebar:
        st.markdown("##### AI Агент МегаМетрики")
        render_theme_toggle(location="sidebar")
        render_admin_unlock_sidebar()
        st.caption("Панель управления сетью «Зеленое Яблоко»")


with st.spinner("AI Агент работает!"):
    sql_result = load_sql_result(ss.sql_refresh)

raw = sql_result.raw
metrics_mode = "sql"


if nav == "Диагностика данных" and is_admin():
    st.subheader("Диагностика данных")
    status = sql_result.status if sql_result else sql_connection_status()
    c1, c2, c3 = st.columns(3)
    c1.metric("Подключение", "ОК" if status.ok else "Нет")
    c2.metric("Отчётный день", str(raw.get("_report_day") or "—"))
    c3.metric(
        "Охват магазинов",
        f"{raw.get('_report_stores', '—')} / {raw.get('_report_stores_max', '—')}",
    )
    st.caption(_format_sync_caption(raw, sql_result))
    if raw.get("_tech_report_note"):
        st.info(raw["_tech_report_note"])
    if raw.get("_report_note"):
        st.caption(raw["_report_note"])
    if sql_result and getattr(sql_result, "confidence_notes", None):
        for n in sql_result.confidence_notes:
            st.write(f"• {n}")
    if _SHOW_SQL_DIAG or st.checkbox("Техподдержка", value=False):
        st.json(
            {
                "ok": bool(status.ok),
                "report_day": raw.get("_report_day"),
                "plan_available": raw.get("_plan_available"),
                "ly_available": raw.get("_ly_available"),
                "pbi_parity": raw.get("_pbi_parity"),
            }
        )
        for n in raw.get("_tech_confidence_notes") or []:
            st.caption(f"• {n}")
    st.stop()


if not sql_result.status.ok:
    render_sql_connection_error(sql_result.status)
    if st.button("Повторить подключение", key="btn_retry_main"):
        ss.sql_refresh = int(ss.sql_refresh) + 1
        st.cache_data.clear()
        st.rerun()
    st.stop()


hero_area = st.container()

# Только начало/конец периода. По умолчанию при входе — вчерашний день.
max_day = date.today()
yesterday = default_yesterday(today=date.today(), max_day=max_day)
if ss.get("_period_mode") != "from_to_v1":
    ss["range_from_ui"] = yesterday
    ss["range_to_ui"] = yesterday
    ss["_period_mode"] = "from_to_v1"

c_theme, c_from, c_to, c_store, c_refresh = st.columns([1.0, 1.2, 1.2, 1.8, 0.9])
with c_theme:
    render_theme_toggle(location="main")
with c_from:
    range_from = st.date_input(
        "Начало периода",
        min_value=_HISTORY_MIN,
        max_value=max_day,
        key="range_from_ui",
    )
with c_to:
    range_to = st.date_input(
        "Конец периода",
        min_value=_HISTORY_MIN,
        max_value=max_day,
        key="range_to_ui",
    )
if range_from > range_to:
    range_from, range_to = range_to, range_from

filters = available_filters(raw, metrics_mode)
store_options = [_ALL_STORES] + [s for s in filters.get("stores", []) if _is_operational_store(s)]
with c_store:
    store_choice = st.selectbox("Магазин", store_options, index=0, key="store_select")
with c_refresh:
    st.write("")
    if st.button("Обновить данные", width="stretch", key="btn_refresh"):
        ss.sql_refresh = int(ss.sql_refresh) + 1
        st.cache_data.clear()
        st.rerun()

selected_store = store_choice if store_choice != _ALL_STORES else None

# Re-anchor: полная история RTO, не короткое traffic-окно
from app.services.pbi_parity_loader import (
    build_pbi_losses_day,
    build_pbi_penetration_day,
    build_pbi_sales_day,
    build_pbi_sp_day,
)
from app.services.sql_data_service import SqlDataService

raw_view = dict(raw)
if raw.get("pbi_rto_day") is not None:
    raw_view["sales_day"] = build_pbi_sales_day(
        raw.get("pbi_rto_day"),
        raw.get("pbi_traffic_pen_day"),
        clip_to_traffic=False,
    )
    raw_view["penetration_week"] = build_pbi_penetration_day(raw.get("pbi_traffic_pen_day"))
    raw_view["losses_month"] = build_pbi_losses_day(
        raw.get("pbi_writeoff_day"),
        raw.get("pbi_inventory_day"),
        writeoff_all=raw.get("pbi_writeoff_all_day"),
        expenses=raw.get("pbi_expense_day"),
        surplus=raw.get("pbi_surplus_day"),
    )
    raw_view["sp_month"] = build_pbi_sp_day(raw.get("pbi_rto_day"))
    if raw.get("pbi_writeoff_all_day") is not None:
        raw_view["writeoff_week"] = raw.get("pbi_writeoff_all_day")
elif raw.get("_sales_day_grain") is not None and getattr(raw.get("_sales_day_grain"), "empty", True) is False:
    raw_view["sales_day"] = raw["_sales_day_grain"].copy()
raw_view["_custom_from"] = range_from.isoformat()
raw_view["_custom_to"] = range_to.isoformat()
raw_view["_ui_period"] = "range"
try:
    raw_view = SqlDataService(use_env_db=False)._normalize_period_sheets(raw_view)
except Exception:  # noqa: BLE001
    pass

sales = raw_view.get("sales_month")
if sales is None or getattr(sales, "empty", True):
    sales = raw_view.get("sales_day")
if sales is None or getattr(sales, "empty", True):
    st.warning("Нет данных за выбранный период")
    st.stop()

note = raw_view.get("_report_note") or ""
if raw_view.get("_report_incomplete") and note and "PBI-parity" not in note:
    st.warning(note)

with st.spinner("AI Агент работает!"):
    dashboard, derr = build_dashboard_safe(raw_view, metrics_mode, "month", selected_store)
dash_dict = dashboard.model_dump() if dashboard is not None else None
if dash_dict is not None:
    dash_dict["mode"] = "SQL"
    meta = dash_dict.setdefault("meta", {})
    meta["report_incomplete"] = bool(raw_view.get("_report_incomplete"))
    meta["period_label"] = format_period_label(range_from, range_to)
    meta["custom_from"] = range_from.isoformat()
    meta["custom_to"] = range_to.isoformat()
    if raw_view.get("_report_note") and "PBI-parity" not in str(raw_view.get("_report_note")):
        meta["report_note"] = raw_view["_report_note"]
    if raw_view.get("_tech_report_note"):
        meta["tech_report_note"] = raw_view["_tech_report_note"]
    if raw_view.get("_cache_synced_at"):
        meta["cache_synced_at"] = raw_view["_cache_synced_at"]

status_text = _format_sync_caption(raw_view, sql_result)

with hero_area:
    render_hero(dash_dict, status_text=status_text)

if derr is not None:
    st.error(f"Не удалось собрать дашборд: {derr}. Показаны доступные части, приложение продолжает работу.")

render_body(dash_dict)
