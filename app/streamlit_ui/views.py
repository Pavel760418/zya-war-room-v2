"""Сборка экранов War Room в Streamlit из HTML-секций и графиков.

Повторяет композицию исходного ``index.html``:
hero + side → controls → KPI-сетка → (action/alerts/таблица | графики + рейтинги)
→ drill-down карточка.
"""
from __future__ import annotations

from typing import Optional

import streamlit as st

from app.streamlit_ui import render
from app.streamlit_ui.charts import losses_chart, plan_chart

__all__ = ["render_side_panel", "render_hero", "render_body", "render_dashboard"]

_CHART_CONFIG = {"displayModeBar": False, "responsive": True}


def render_side_panel() -> str:
    """Правая панель «Режимы» из шапки (текстовый блок, как в оригинале)."""
    return (
        "<div class='panel side'>"
        "<div style='display:flex;justify-content:space-between;align-items:center'><strong>Режимы</strong></div>"
        "<div class='subtle'>Источник данных — прямой SQL к 1С (MSSQL). "
        "Физические таблицы берутся из каталога метаданных хранения.</div>"
        "<div class='subtle'>Сейчас отдельными блоками реализованы: 1) drill-down карточка магазина, "
        "2) action layer с комментариями и действиями.</div>"
        "</div>"
    )


def _card(title: str, body_html: str, subtitle: str = "") -> str:
    sub = f"<div class='subtle' style='margin-bottom:12px'>{subtitle}</div>" if subtitle else ""
    return f"<article class='card'><div class='section-title'>{title}</div>{sub}<div class='list'>{body_html}</div></article>"


def render_hero(dashboard: Optional[dict]) -> None:
    """Верхняя шапка: hero-панель + панель «Режимы»."""
    hero_col, side_col = st.columns([1.45, 0.9])
    with hero_col:
        st.markdown(render.hero_html(dashboard or {}), unsafe_allow_html=True)
    with side_col:
        st.markdown(render_side_panel(), unsafe_allow_html=True)


def render_body(dashboard: Optional[dict]) -> None:
    """Тело дашборда: KPI, основной блок и drill-down."""
    if not dashboard:
        st.warning(
            "Дашборд не удалось собрать по текущим данным. Проверьте раздел «Диагностика SQL» "
            "и Secrets подключения к MSSQL."
        )
        return

    # --- KPI-сетка ---
    st.markdown(render.kpis_html(dashboard.get("kpis", [])), unsafe_allow_html=True)

    # --- Основной блок: слева списки/таблица, справа графики и рейтинги ---
    left, right = st.columns([1.15, 0.85])
    with left:
        st.markdown(
            _card(
                "Action layer",
                render.actions_html(dashboard.get("actions", [])),
                "Отдельно по второму пункту: рекомендации строятся автоматически на основе статусов KPI и порогов.",
            ),
            unsafe_allow_html=True,
        )
        st.markdown(
            _card("Проблемы и риски", render.alerts_html(dashboard.get("alerts", []))),
            unsafe_allow_html=True,
        )
        st.markdown(
            "<article class='card'><div class='section-title'>Таблица магазинов</div>"
            + render.store_table_html(dashboard.get("store_table", []))
            + "</article>",
            unsafe_allow_html=True,
        )

    with right:
        charts = dashboard.get("charts", {})
        with st.container(border=True):
            st.markdown("<div class='section-title'>Выполнение плана по магазинам</div>", unsafe_allow_html=True)
            st.plotly_chart(plan_chart(charts.get("plan_vs_store", [])), width="stretch", config=_CHART_CONFIG)
        with st.container(border=True):
            st.markdown("<div class='section-title'>Структура потерь</div>", unsafe_allow_html=True)
            st.plotly_chart(losses_chart(charts.get("losses_structure", [])), width="stretch", config=_CHART_CONFIG)
        st.markdown(
            "<div class='two'>"
            + _card("Лидеры", render.ranks_html(dashboard.get("top_stores", [])))
            + _card("Аутсайдеры", render.ranks_html(dashboard.get("bottom_stores", [])))
            + "</div>",
            unsafe_allow_html=True,
        )

    # --- Drill-down карточка магазина ---
    st.markdown(
        "<section class='card drilldown' style='margin-top:16px'>"
        "<div class='section-title'>Drill-down карточка магазина</div>"
        "<div class='subtle' style='margin-bottom:12px'>Отдельно по первому пункту: карточка всегда показывает "
        "один выбранный или самый проблемный магазин, чтобы увидеть причины отклонений и локальные зоны риска.</div>"
        + render.drilldown_html(dashboard.get("drilldown"))
        + "</section>",
        unsafe_allow_html=True,
    )


def render_dashboard(dashboard: Optional[dict]) -> None:
    """Полный экран: шапка + тело (для случаев без вынесенных контролов)."""
    render_hero(dashboard)
    render_body(dashboard)
