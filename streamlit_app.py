"""Streamlit-версия ZYA War Room v2 — операционный кокпит сети «Зеленое Яблоко».

Запуск::

    streamlit run streamlit_app.py

Это аккуратная Streamlit-обёртка над существующей бизнес-логикой (``MetricsService``)
и устойчивым слоем загрузки Excel (``app.ingestion``). Визуальный дизайн, состав
экранов, тексты и композиция максимально повторяют исходный веб-дашборд.
"""
from __future__ import annotations

import streamlit as st

from app.streamlit_ui.data_access import (
    available_filters,
    build_dashboard_safe,
    load_demo_raw,
    load_excel_result,
)
from app.streamlit_ui.diagnostics import render_full_diagnostics, render_summary_banner
from app.streamlit_ui.theme import inject_theme
from app.streamlit_ui.views import render_body, render_hero

st.set_page_config(page_title="War Room v2 — Operational Cockpit", page_icon="🍏", layout="wide")
inject_theme()

PERIOD_LABELS = {"day": "День", "week": "Неделя", "month": "Месяц"}
_ALL_STORES = "Все магазины"


def _period_label(code: str) -> str:
    return PERIOD_LABELS.get(code, code)


# --------------------------------------------------------------------------- #
# Sidebar: навигация + источник данных + загрузка файла
# --------------------------------------------------------------------------- #
ss = st.session_state
ss.setdefault("uploaded_bytes", None)
ss.setdefault("uploaded_name", None)

with st.sidebar:
    st.markdown("<div class='pill'>WAR ROOM V2</div>", unsafe_allow_html=True)
    st.caption("Операционный кокпит сети «Зеленое Яблоко»")

    nav = st.radio("Навигация", ["Дашборд", "Диагностика загрузки"], index=0)

    st.divider()
    mode_label = st.radio("Источник данных", ["Excel pilot", "Demo random"], index=0)
    mode = "excel" if mode_label == "Excel pilot" else "demo"

    if mode == "excel":
        uploaded = st.file_uploader("Загрузить исходный Excel (.xlsx)", type=["xlsx", "xls"])
        if uploaded is not None:
            ss.uploaded_bytes = uploaded.getvalue()
            ss.uploaded_name = uploaded.name
        if ss.uploaded_bytes is not None:
            st.caption(f"Активный файл: **{ss.uploaded_name}**")
            if st.button("Сбросить к эталонному файлу", use_container_width=True):
                ss.uploaded_bytes = None
                ss.uploaded_name = None
                st.rerun()
        else:
            st.caption("Файл не загружен — используется эталонный пилотный Excel.")

    st.divider()
    st.caption(
        "Excel pilot привязывает дашборд к реальным данным. Demo random генерирует сеть "
        "из 24 магазинов для стресс-теста визуального восприятия."
    )


# --------------------------------------------------------------------------- #
# Загрузка данных (никогда не роняем приложение)
# --------------------------------------------------------------------------- #
report = None
if mode == "demo":
    raw = load_demo_raw()
else:
    result = load_excel_result(ss.uploaded_bytes, ss.uploaded_name)
    raw = result.raw
    report = result.report


# --------------------------------------------------------------------------- #
# Страница: Диагностика загрузки
# --------------------------------------------------------------------------- #
if nav == "Диагностика загрузки":
    if mode == "demo":
        st.info("Диагностика доступна для режима Excel pilot. В demo-режиме данные генерируются программно.")
    elif report is not None:
        render_full_diagnostics(report)
    st.stop()


# --------------------------------------------------------------------------- #
# Страница: Дашборд
# --------------------------------------------------------------------------- #
# Шапка (hero) должна быть сверху, но зависит от собранного дашборда, поэтому
# резервируем контейнер и заполняем его после сборки данных.
hero_area = st.container()

# --- Панель контролов (мирроринг исходной controls-строки) ---
filters = available_filters(raw, mode)
store_options = [_ALL_STORES] + list(filters.get("stores", []))
region_options = [_ALL_STORES.replace("магазины", "регионы")] + list(filters.get("regions", []))
cluster_options = [_ALL_STORES.replace("магазины", "кластеры")] + list(filters.get("clusters", []))

c_period, c_scope, c_store, c_region, c_cluster, c_refresh = st.columns([1.5, 1.1, 1.3, 1.1, 1.1, 0.8])
with c_period:
    period = st.radio("Период", ["day", "week", "month"], format_func=_period_label,
                      horizontal=True, index=0, label_visibility="collapsed")
with c_scope:
    scope_label = st.radio("Контур", ["Сеть", "Магазин"], horizontal=True, index=0, label_visibility="collapsed")
with c_store:
    store_choice = st.selectbox("Магазин", store_options, index=0, label_visibility="collapsed")
with c_region:
    st.selectbox("Регион", region_options, index=0, label_visibility="collapsed")
with c_cluster:
    st.selectbox("Кластер", cluster_options, index=0, label_visibility="collapsed")
with c_refresh:
    if st.button("Обновить", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# Выбор магазина переводит контур в режим «Магазин» (как в оригинале).
selected_store = store_choice if store_choice != _ALL_STORES else None
if scope_label == "Магазин" and not selected_store and store_options[1:]:
    selected_store = None  # контур «Магазин» без выбора — показываем самый проблемный

# --- Плашка статуса загрузки (только для Excel) ---
if report is not None:
    render_summary_banner(report)

# --- Сборка и отрисовка дашборда ---
dashboard, derr = build_dashboard_safe(raw, mode, period, selected_store)
dash_dict = dashboard.model_dump() if dashboard is not None else None

with hero_area:
    render_hero(dash_dict)

if derr is not None:
    st.error(f"Не удалось собрать дашборд: {derr}. Показаны доступные части, приложение продолжает работу.")

render_body(dash_dict)
