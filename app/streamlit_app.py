"""Streamlit entrypoint: МегаМетрики — панель управления сетью «Зеленое Яблоко».

Пользовательский путь данных — локальный SQLite-кэш на сервере приложения.
Прямой MSSQL 1С используется только sync-скриптом и режимом диагностики.
"""
from __future__ import annotations

import os

import streamlit as st

from app.ingestion.sql_extract import NON_STORE_NAMES
from app.streamlit_ui.data_access import (
    available_filters,
    build_dashboard_safe,
    load_sql_result,
    render_sql_connection_error,
    sql_connection_status,
)
from app.streamlit_ui.theme import inject_theme, render_theme_toggle
from app.streamlit_ui.views import render_body, render_hero

st.set_page_config(
    page_title="МегаМетрики — панель управления сетью",
    page_icon="🍏",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.session_state.setdefault("ui_theme", "dark")
inject_theme()

PERIOD_LABELS = {"day": "День", "week": "Неделя", "month": "Месяц"}
PERIOD_BY_LABEL = {v: k for k, v in PERIOD_LABELS.items()}
_ALL_STORES = "Все магазины"
_SHOW_SQL_DIAG = os.environ.get("SHOW_SQL_DIAGNOSTICS", "0").strip().lower() in {"1", "true", "yes"}


def _period_label(code: str) -> str:
    return PERIOD_LABELS.get(code, code)


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
    synced = (
        (getattr(sql_result, "last_success_at", None) if sql_result else None)
        or raw.get("_cache_synced_at")
        or "—"
    )
    # Человекочитаемое время без «рваного» ISO
    display = synced
    try:
        from datetime import datetime

        s = str(synced).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        display = dt.strftime("%d.%m.%Y %H:%M")
    except Exception:  # noqa: BLE001
        display = str(synced)
    src = raw.get("_data_source") or "—"
    if src == "local_cache":
        return (
            f"Данные обновлены из 1С: {display}. "
            "Снимок на сервере приложения; экран обновляется раз в минуту из локального кэша."
        )
    return f"Источник: {src}. Данные обновлены из 1С: {display}."


ss = st.session_state
ss.setdefault("sql_refresh", 0)

with st.sidebar:
    st.markdown("##### МегаМетрики")
    st.caption("Панель управления сетью «Зеленое Яблоко»")
    render_theme_toggle(location="sidebar")

    nav_options = ["Дашборд", "Диагностика данных"]
    nav = st.radio("Навигация", nav_options, index=0, key="nav_main")

    st.divider()
    st.markdown("**Источник данных:** локальный снимок с сервера (синхронизация с 1С по расписанию)")
    status = sql_connection_status()
    if status.ok:
        st.success("Данные: доступны")
        st.caption(f"Хранилище: {status.database or '—'} · источник: {status.server or '—'}")
        if status.last_success_at:
            st.caption(f"Синхронизация с 1С: {status.last_success_at}")
    else:
        st.error("Данные недоступны")
        if status.error:
            st.caption(f"Ошибка: {status.error}")

    if st.button(
        "Обновить отображение",
        width="stretch",
        key="btn_refresh_all",
        help="Очистить кэш экрана и перечитать локальный снимок (без обращения к 1С)",
    ):
        ss.sql_refresh = int(ss.sql_refresh) + 1
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.caption(
        "Расписание синхронизации с 1С: 08:00 и 12:00 МСК. "
        "Кнопка выше обновляет только экран из уже загруженного снимка."
    )
    with st.expander("Сокращения"):
        st.markdown(
            "- **СП** — собственное производство\n"
            "- **ТЗ** — торговый зал\n"
            "- **РТО** — розничный товарооборот\n"
            "- **г/г** — год к году\n"
            "- **ФРОВ** — фрукты и овощи"
        )


with st.spinner("Загружаем данные из локального снимка..."):
    sql_result = load_sql_result(ss.sql_refresh)

raw = sql_result.raw
metrics_mode = "sql"


if nav == "Диагностика данных":
    st.subheader("Диагностика данных")
    status = sql_result.status if sql_result else sql_connection_status()
    st.markdown("### Состояние для руководства")
    c1, c2, c3 = st.columns(3)
    c1.metric("Подключение", "ОК" if status.ok else "Нет")
    c2.metric("Отчётный день", str(raw.get("_report_day") or "—"))
    c3.metric(
        "Охват магазинов",
        f"{raw.get('_report_stores', '—')} / {raw.get('_report_stores_max', '—')}",
    )
    st.caption(_format_sync_caption(raw, sql_result))
    st.info(
        f"Режим UI: локальный кэш. Прямой доступ к 1С отключён для пользовательского трафика "
        f"(источник raw: {raw.get('_data_source', '—')})."
    )
    if raw.get("_report_note"):
        st.info(raw["_report_note"])
    if not raw.get("_plan_available", True):
        st.warning("Плановые показатели не заданы в 1С — панель работает без плана.")
    if not raw.get("_ly_available", True):
        st.warning("Нет данных за прошлый год — колонка г/г скрыта.")
    if sql_result and getattr(sql_result, "confidence_notes", None):
        st.markdown("**Источники метрик (бизнес-описание):**")
        for n in sql_result.confidence_notes:
            st.write(f"• {n}")
    if sql_result and sql_result.warnings:
        for w in sql_result.warnings:
            if w:
                st.warning(w)
    if not status.ok:
        render_sql_connection_error(status)
        if st.button("Повторить подключение", key="btn_retry_sql"):
            ss.sql_refresh = int(ss.sql_refresh) + 1
            st.cache_data.clear()
            st.rerun()
        st.stop()

    if _SHOW_SQL_DIAG or st.checkbox("Показать подробности для технической поддержки", value=False):
        st.json(
            {
                "ok": bool(status.ok),
                "message": status.message,
                "server": status.server,
                "database": status.database,
                "data_source": raw.get("_data_source"),
                "last_success_at": (sql_result.last_success_at if sql_result else None),
                "mapping_complete": (sql_result.mapping_complete if sql_result else False),
                "error": status.error,
                "report_day": raw.get("_report_day"),
                "plan_available": raw.get("_plan_available"),
                "ly_available": raw.get("_ly_available"),
            }
        )
        tech = raw.get("_tech_confidence_notes") or []
        for n in tech:
            st.caption(f"• {n}")
        if st.button("Проверить прямое подключение к 1С (только диагностика)", key="btn_live_sql_probe"):
            prev = os.environ.get("WARROOM_DATA_SOURCE")
            try:
                os.environ["WARROOM_DATA_SOURCE"] = "sql"
                from app.services.sql_data_service import SqlDataService

                live_st = SqlDataService(use_env_db=True).status()
                st.write(
                    {
                        "live_ok": live_st.ok,
                        "live_server": live_st.server,
                        "live_database": live_st.database,
                        "live_error": live_st.error,
                        "live_message": live_st.message,
                    }
                )
            finally:
                if prev is None:
                    os.environ.pop("WARROOM_DATA_SOURCE", None)
                else:
                    os.environ["WARROOM_DATA_SOURCE"] = prev
    st.stop()


if not sql_result.status.ok:
    render_sql_connection_error(sql_result.status)
    if st.button("Повторить подключение", key="btn_retry_main"):
        ss.sql_refresh = int(ss.sql_refresh) + 1
        st.cache_data.clear()
        st.rerun()
    st.stop()


hero_area = st.container()

# Переключатель темы + фильтры — только native Streamlit (без HTML-кнопок)
c_theme, c_period, c_store, c_refresh = st.columns([1.2, 1.8, 1.8, 0.9])
with c_theme:
    render_theme_toggle(location="main")

filters = available_filters(raw, metrics_mode)
store_options = [_ALL_STORES] + [s for s in filters.get("stores", []) if _is_operational_store(s)]

with c_period:
    period_ui = st.radio(
        "Период",
        ["День", "Неделя", "Месяц"],
        horizontal=True,
        index=0,
        key="period_radio_ui",
        help="День / Неделя / Месяц относительно отчётного дня",
    )
    period = PERIOD_BY_LABEL[period_ui]
with c_store:
    store_choice = st.selectbox(
        "Магазин",
        store_options,
        index=0,
        key="store_select",
    )
with c_refresh:
    st.write("")
    if st.button("Обновить данные", width="stretch", key="btn_refresh"):
        ss.sql_refresh = int(ss.sql_refresh) + 1
        st.cache_data.clear()
        st.rerun()

selected_store = store_choice if store_choice != _ALL_STORES else None

st.caption(_format_sync_caption(raw, sql_result))
if raw.get("_report_note") and raw.get("_data_source") != "local_cache":
    st.caption(raw["_report_note"])
elif not sql_result.mapping_complete and sql_result.warnings:
    st.warning("Данные загружены частично. Подробности — во вкладке «Диагностика данных».")
    for w in sql_result.warnings[:3]:
        if w:
            st.caption(f"⚠ {w}")

dashboard, derr = build_dashboard_safe(raw, metrics_mode, period, selected_store)
dash_dict = dashboard.model_dump() if dashboard is not None else None
if dash_dict is not None:
    dash_dict["mode"] = "SQL"
    meta = dash_dict.setdefault("meta", {})
    meta["report_incomplete"] = bool(raw.get("_report_incomplete"))
    if raw.get("_report_note"):
        meta["report_note"] = raw["_report_note"]
    if raw.get("_cache_synced_at"):
        meta["cache_synced_at"] = raw["_cache_synced_at"]

status_text = (
    f"Отчётный день: {raw.get('_report_day', '—')}. "
    f"{_format_sync_caption(raw, sql_result)}"
)

with hero_area:
    render_hero(dash_dict, status_text=status_text)

if derr is not None:
    st.error(f"Не удалось собрать дашборд: {derr}. Показаны доступные части, приложение продолжает работу.")

render_body(dash_dict)
