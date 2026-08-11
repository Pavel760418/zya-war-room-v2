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
    get_template_bytes,
    get_template_filename,
    load_demo_raw,
    load_excel_result,
    load_sql_result,
    sql_available,
    sql_connection_status,
)
from app.streamlit_ui.diagnostics import render_full_diagnostics, render_summary_banner
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


# --------------------------------------------------------------------------- #
# Sidebar: навигация + источник данных + загрузка файла
# --------------------------------------------------------------------------- #
ss = st.session_state
ss.setdefault("uploaded_bytes", None)
ss.setdefault("uploaded_name", None)
ss.setdefault("sql_refresh", 0)

with st.sidebar:
    st.markdown("<div class='pill'>WAR ROOM V2</div>", unsafe_allow_html=True)
    st.caption("Операционный кокпит сети «Зеленое Яблоко»")

    nav = st.radio("Навигация", ["Дашборд", "Диагностика загрузки"], index=0)

    st.divider()
    # Streamlit Cloud cannot reach private SQL — default to Excel there.
    _sql_ok = sql_available()
    _source_options = ["Источник данных: SQL", "Резервный источник: Excel", "Demo random"]
    _default_source = 0 if _sql_ok else 1
    mode_label = st.radio(
        "Источник данных",
        _source_options,
        index=_default_source,
    )
    if mode_label.startswith("Источник данных: SQL"):
        mode = "sql"
    elif mode_label == "Demo random":
        mode = "demo"
    else:
        mode = "excel"

    if mode == "sql":
        status = sql_connection_status()
        if status.ok:
            st.success("SQL: подключено")
            st.caption(f"База: {status.database or '—'} · сервер: {status.server or '—'}")
            if status.last_success_at:
                st.caption(f"Последний успех: {status.last_success_at}")
        else:
            st.warning("SQL временно недоступен — приложение работает в режиме деградации.")
            if status.error:
                st.caption(f"Ошибка: {status.error}")
        if st.button("Повторить обновление SQL", use_container_width=True):
            ss.sql_refresh = int(ss.sql_refresh) + 1
            st.cache_data.clear()
            st.rerun()

    if mode == "excel":
        uploaded = st.file_uploader("Загрузить исходный Excel (.xlsx)", type=["xlsx"])
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

    st.download_button(
        "⬇️ Скачать шаблон Excel",
        data=get_template_bytes(),
        file_name=get_template_filename(),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        help="Готовый .xlsx с нужными листами, заголовками и примерами строк.",
    )

    st.divider()
    st.caption(
        "SQL — основной источник. Excel — резерв и сверка цифр. Demo — синтетическая сеть "
        "из 24 магазинов для визуального стресс-теста."
    )


# --------------------------------------------------------------------------- #
# Загрузка данных (никогда не роняем приложение)
# --------------------------------------------------------------------------- #
report = None
sql_result = None
if mode == "demo":
    raw = load_demo_raw()
    metrics_mode = "demo"
elif mode == "sql":
    sql_result = load_sql_result(ss.sql_refresh)
    raw = sql_result.raw
    metrics_mode = "excel"
else:
    result = load_excel_result(ss.uploaded_bytes, ss.uploaded_name)
    raw = result.raw
    report = result.report
    metrics_mode = "excel"


# --------------------------------------------------------------------------- #
# Страница: Диагностика загрузки
# --------------------------------------------------------------------------- #
if nav == "Диагностика загрузки":
    if mode == "demo":
        st.info("Диагностика доступна для SQL и Excel. В demo-режиме данные генерируются программно.")
    elif mode == "sql":
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
            st.markdown("**Кандидаты (высокий / средний / низкий):**")
            for n in sql_result.confidence_notes:
                st.caption(f"• {n}")
        if sql_result and sql_result.warnings:
            for w in sql_result.warnings:
                if w:
                    st.warning(w)
        st.info(
            "Сейчас включён режим SQL-кандидатов по результатам discovery. "
            "IT-подтверждённый маппинг ещё не закрыт — сверяйте с Excel."
        )
    elif report is not None:
        render_full_diagnostics(report)
        st.divider()
        st.caption("Нужен корректный формат? Скачайте готовый шаблон и заполните его.")
        st.download_button(
            "⬇️ Скачать шаблон Excel",
            data=get_template_bytes(),
            file_name=get_template_filename(),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    st.stop()


# --------------------------------------------------------------------------- #
# Страница: Дашборд
# --------------------------------------------------------------------------- #
hero_area = st.container()

filters = available_filters(raw, metrics_mode)
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
        ss.sql_refresh = int(ss.sql_refresh) + 1
        st.cache_data.clear()
        st.rerun()

selected_store = store_choice if store_choice != _ALL_STORES else None
if scope_label == "Магазин" and not selected_store and store_options[1:]:
    selected_store = None

if report is not None:
    render_summary_banner(report)

if mode == "sql" and sql_result is not None:
    if sql_result.status.ok and sql_result.mapping_complete:
        st.caption("SQL: чеки и выручка из _Document156. План/ТЗ/СП/остатки в карточках — 0, пока нет SQL-маппинга.")
    elif sql_result.status.ok and not sql_result.mapping_complete:
        st.warning(
            "SQL в режиме кандидатов/fallback. Сверяйте цифры с Excel. "
            "Детали — во вкладке «Диагностика загрузки»."
        )
    elif not sql_result.status.ok:
        st.warning(
            "SQL недоступен — показан пустой каркас. Переключитесь на Excel или нажмите "
            "«Повторить обновление SQL»."
        )
    if sql_result.warnings:
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
