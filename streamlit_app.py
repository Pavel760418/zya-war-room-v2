"""Streamlit-версия ZYA War Room v2 — операционный кокпит сети «Зеленое Яблоко».

Единственный пользовательский путь данных — MSSQL (1С). Excel используется
только во внутренних тестах ingestion/метрик.
"""
from __future__ import annotations

import streamlit as st

from app.streamlit_ui.data_access import (
    available_filters,
    build_dashboard_safe,
    load_sql_result,
    render_sql_connection_error,
    sql_connection_status,
)
from app.streamlit_ui.theme import inject_theme
from app.streamlit_ui.views import render_body, render_hero

st.set_page_config(
    page_title="War Room v2 — Operational Cockpit",
    page_icon="🍏",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_theme()

PERIOD_LABELS = {"day": "День", "week": "Неделя", "month": "Месяц"}
_ALL_STORES = "Все магазины"


def _period_label(code: str) -> str:
    return PERIOD_LABELS.get(code, code)


ss = st.session_state
ss.setdefault("sql_refresh", 0)

with st.sidebar:
    st.markdown("<div class='pill'>WAR ROOM V2</div>", unsafe_allow_html=True)
    st.caption("Операционный кокпит сети «Зеленое Яблоко»")

    nav = st.radio("Навигация", ["Дашборд", "Диагностика SQL"], index=0)

    st.divider()
    st.markdown("**Источник данных:** MSSQL (1С)")
    status = sql_connection_status()
    if status.ok:
        st.success("SQL: подключено")
        st.caption(f"База: {status.database or '—'} · сервер: {status.server or '—'}")
        if status.last_success_at:
            st.caption(f"Последний успех: {status.last_success_at}")
    else:
        st.error("SQL недоступен")
        if status.error:
            st.caption(f"Ошибка: {status.error}")
    if st.button("Обновить SQL", width="stretch"):
        ss.sql_refresh = int(ss.sql_refresh) + 1
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.caption(
        "Данные читаются только из MSSQL по физическим таблицам 1С "
        "(`_AccumRg*`, `_Document*`). Excel-загрузка в UI отключена."
    )


sql_result = load_sql_result(ss.sql_refresh)
raw = sql_result.raw
metrics_mode = "excel"  # MetricsService sheet layout (canonical columns)


if nav == "Диагностика SQL":
    st.subheader("Диагностика SQL")
    status = sql_result.status if sql_result else sql_connection_status()
    st.write(
        {
            "ok": status.ok,
            "message": status.message,
            "server": status.server,
            "database": status.database,
            "last_success_at": (sql_result.last_success_at if sql_result else None),
            "mapping_complete": (sql_result.mapping_complete if sql_result else False),
            "error": status.error,
        }
    )
    if sql_result and getattr(sql_result, "confidence_notes", None):
        st.markdown("**Физический маппинг (каталог метаданных):**")
        for n in sql_result.confidence_notes:
            st.caption(f"• {n}")
    if sql_result and sql_result.warnings:
        for w in sql_result.warnings:
            if w:
                st.warning(w)
    if not status.ok:
        render_sql_connection_error(status)
    st.stop()


if not sql_result.status.ok:
    render_sql_connection_error(sql_result.status)
    st.stop()


hero_area = st.container()

filters = available_filters(raw, metrics_mode)
store_options = [_ALL_STORES] + list(filters.get("stores", []))
region_options = [_ALL_STORES.replace("магазины", "регионы")] + list(filters.get("regions", []))
cluster_options = [_ALL_STORES.replace("магазины", "кластеры")] + list(filters.get("clusters", []))

c_period, c_scope, c_store, c_region, c_cluster, c_refresh = st.columns([1.5, 1.1, 1.3, 1.1, 1.1, 0.8])
with c_period:
    period = st.radio(
        "Период",
        ["day", "week", "month"],
        format_func=_period_label,
        horizontal=True,
        index=0,
        label_visibility="collapsed",
    )
with c_scope:
    scope_label = st.radio("Контур", ["Сеть", "Магазин"], horizontal=True, index=0, label_visibility="collapsed")
with c_store:
    store_choice = st.selectbox("Магазин", store_options, index=0, label_visibility="collapsed")
with c_region:
    st.selectbox("Регион", region_options, index=0, label_visibility="collapsed")
with c_cluster:
    st.selectbox("Кластер", cluster_options, index=0, label_visibility="collapsed")
with c_refresh:
    if st.button("Обновить", width="stretch"):
        ss.sql_refresh = int(ss.sql_refresh) + 1
        st.cache_data.clear()
        st.rerun()

selected_store = store_choice if store_choice != _ALL_STORES else None
if scope_label == "Магазин" and not selected_store and store_options[1:]:
    selected_store = None

if sql_result.mapping_complete:
    st.caption(
        "SQL: физические таблицы из StrukturaKhraneniiaBazyDannykh.xlsx "
        "(`_AccumRg6691`, `_Document172`, `_Document124`, `_AccumRg6601`, …)."
    )
elif sql_result.warnings:
    st.warning("SQL частично загружен. Детали — во вкладке «Диагностика SQL».")
    for w in sql_result.warnings[:3]:
        if w:
            st.caption(f"⚠ {w}")

dashboard, derr = build_dashboard_safe(raw, metrics_mode, period, selected_store)
dash_dict = dashboard.model_dump() if dashboard is not None else None

with hero_area:
    render_hero(dash_dict)

if derr is not None:
    st.error(f"Не удалось собрать дашборд: {derr}. Показаны доступные части, приложение продолжает работу.")

render_body(dash_dict)
