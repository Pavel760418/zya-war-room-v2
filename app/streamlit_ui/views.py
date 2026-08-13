"""Сборка экранов МегаМетрики: критичный текст — через native Streamlit.

Постоянное решение «поехавшей» кириллицы: не рендерить Период/Магазин/риски/таблицу
кастомным HTML+flex. HTML оставляем только для KPI-карточек с числами.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from app.streamlit_ui import render
from app.streamlit_ui.charts import losses_pct_chart, plan_chart
from app.streamlit_ui.formatting import format_money, pct
from app.streamlit_ui.render import risk_label_display
from app.streamlit_ui.roles import is_admin, show_risks_block

__all__ = ["render_side_panel", "render_hero", "render_body", "render_dashboard", "SHOW_ACTION_LAYER"]

_CHART_CONFIG = {"displayModeBar": False, "responsive": True}

import os

SHOW_ACTION_LAYER = os.environ.get("SHOW_ACTION_LAYER", "0").strip().lower() in {"1", "true", "yes"}

_PERIOD_RU = {"day": "День", "week": "Неделя", "month": "Месяц"}
_SEV_TITLE = {"blue": "Инфо", "yellow": "Внимание", "red": "Критично", "green": "Норма"}


def render_side_panel(status_text: str = "") -> None:
    st.markdown("**Статус данных**")
    st.caption(status_text or "Данные обновлены из 1С.")


def render_hero(dashboard: Optional[dict], status_text: str = "") -> None:
    data = dashboard or {}
    selection = data.get("selection") or {}
    meta = data.get("meta") or {}
    scope_label = "Вся сеть" if data.get("scope") == "network" else (selection.get("store") or "Магазин")
    period_code = str(data.get("period", "") or "")
    period_label = meta.get("period_label") or _PERIOD_RU.get(period_code, period_code) or "—"
    coverage = meta.get("coverage_label") or (
        "неполный охват" if meta.get("report_incomplete") else "полный охват"
    )
    last_upd = str(data.get("last_update") or "—")
    if len(last_upd) >= 10 and last_upd[4] == "-" and last_upd[7] == "-":
        last_upd = f"{last_upd[8:10]}.{last_upd[5:7]}.{last_upd[:4]}"

    st.markdown("<div class='wr-brand'>AI Агент МегаМетрики</div>", unsafe_allow_html=True)
    st.markdown("## Панель управления сетью")
    st.caption("Сеть магазинов, операционные метрики и детализация по магазину. Источник — учётные данные 1С.")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Период", period_label)
    m2.metric("Магазин", scope_label)
    m3.metric("Обновление", last_upd)
    m4.metric("Сеть", str(meta.get("network") or "—"))
    m5.metric("Охват данных", coverage)
    focus = meta.get("focus_text") or ""
    if focus:
        st.info(f"**Главный фокус периода**\n\n{focus}")
    if is_admin() and meta.get("tech_report_note"):
        st.caption(meta["tech_report_note"])
    note = meta.get("report_note") or ""
    if note and "PBI-parity" not in note:
        st.caption(note)
    if status_text:
        render_side_panel(status_text)


def _render_alerts_native(alerts: list[dict]) -> None:
    if not show_risks_block():
        return
    st.markdown("### Проблемы и риски")
    st.caption("Сначала смотрите этот блок: сигналы по сети и магазинам.")
    if not alerts:
        st.success("Активных сигналов нет")
        return
    for a in alerts:
        sev = str(a.get("severity") or "blue")
        label = _SEV_TITLE.get(sev, "Инфо")
        store = (a.get("store") or "").strip()
        title = a.get("title") or "Сигнал"
        comment = a.get("comment") or ""
        head = f"**[{label}] {title}**"
        body = f"{store} — {comment}" if store else comment
        text = f"{head}\n\n{body}" if body else head
        if sev == "red":
            st.error(text)
        elif sev == "yellow":
            st.warning(text)
        elif sev == "green":
            st.success(text)
        else:
            st.info(text)


def _store_table_df(rows: list[dict], *, ly_available: bool, plan_available: bool, money_unit: str = "th_rub") -> pd.DataFrame:
    out = []
    for r in rows:
        plan_cell = "не задан" if not plan_available or r.get("plan_pct") is None else f"{pct(r.get('plan_pct'))}%"
        yoy_cell = "нет данных за прошлый год" if r.get("yoy") is None else f"{pct(r.get('yoy'))}%"
        out.append(
            {
                "Магазин": r.get("store") or "—",
                "Выручка": format_money(r.get("revenue"), unit=money_unit),
                "План": plan_cell,
                "г/г": yoy_cell,
                "Доля СП": f"{pct(r.get('own_production_share_pct') or 0)}%",
                "Доступность ТЗ": f"{pct(r.get('shop_availability') or 0)}%",
                "Доступность СП": f"{pct(r.get('production_availability') or 0)}%",
                "Списания": format_money(r.get("losses") or 0, unit=money_unit),
                "Недостачи": format_money(r.get("inventory_shortage") or 0, unit=money_unit),
                "Риск": risk_label_display(r.get("risk_level")),
            }
        )
    return pd.DataFrame(out)


def _render_ranks_native(title: str, rows: list[dict], help_text: str = "", money_unit: str = "th_rub") -> None:
    st.markdown(f"### {title}")
    if help_text:
        st.caption(help_text)
    if not rows:
        st.caption("Нет данных")
        return
    for r in rows:
        rev = r.get("revenue") or 0
        losses = r.get("losses") or 0
        loss_pct = round(float(losses) / max(float(rev), 0.01) * 100.0, 2)
        store = r.get("store") or "—"
        st.markdown(
            f"**{store}**  \n"
            f"Выручка {format_money(rev, unit=money_unit)} · "
            f"Списания {format_money(losses, unit=money_unit)} ({pct(loss_pct)}%)"
        )


def _losses_structure_rows(items: list[dict], money_unit: str) -> list[dict]:
    """Строки таблицы структуры + «Итого»."""
    rows = []
    total_amt = sum(float(x.get("amount") or 0) for x in items)
    denom = total_amt or 1.0
    rto_weight = 0.0
    for x in items:
        amt = float(x.get("amount") or 0)
        rto = float(x.get("pct_rto") or 0)
        rto_weight += rto
        rows.append(
            {
                "Статья": x.get("group") or "—",
                "Сумма": format_money(amt, unit=money_unit),
                "% вклада": f"{pct(100.0 * amt / denom)}%",
                "% к РТО": f"{pct(rto)}%",
            }
        )
    if rows:
        rows.append(
            {
                "Статья": "Итого",
                "Сумма": format_money(total_amt, unit=money_unit),
                "% вклада": f"{pct(100.0)}%",
                "% к РТО": f"{pct(rto_weight)}%",
            }
        )
    return rows


def _losses_structure_table(items: list[dict], money_unit: str, *, store: str | None = None) -> None:
    st.markdown("### Структура списаний и расходов")
    scope = f"магазин {store}" if store else "вся сеть"
    st.caption(
        f"Статьи 1С: товарные списания, расходы (Обед/Представительские), недостачи (инвентаризация). "
        f"Срез: {scope}."
    )
    if not items:
        st.caption("Нет данных по статьям за период")
        return
    st.dataframe(pd.DataFrame(_losses_structure_rows(items, money_unit)), width="stretch", hide_index=True)


def _availability_detail(meta: dict, dashboard: dict) -> None:
    detail = meta.get("availability_detail") or dashboard.get("availability_detail") or []
    check = meta.get("availability_check") or []
    verify = meta.get("availability_verify")
    sku_store = meta.get("availability_sku_store") or ""
    formula = meta.get("availability_formula") or (
        "Доступность ТЗ — от остатка на конец периода; доступность СП — от продаж за выбранный период."
    )
    with st.expander("Показать детализацию по товарам", expanded=False):
        st.caption(formula)
        st.caption(
            "KPI сети — среднее % по магазинам. Проверка расчёта без SKU: "
            "доступно / всего по каждому магазину (тот же снимок, что KPI)."
        )
        if check:
            st.dataframe(pd.DataFrame(check), width="stretch", hide_index=True)
        else:
            st.caption("Агрегат доступности по магазинам пока пуст — проверьте синхронизацию.")
        if detail:
            st.markdown(
                f"**SKU целевого ассортимента — {sku_store or 'магазин карточки'}**"
            )
            if verify:
                tz = verify.get("tz") or {}
                sp = verify.get("sp") or {}
                tz_ok = "совпадает с KPI" if verify.get("tz_match") else "расхождение с KPI"
                sp_ok = "совпадает с KPI" if verify.get("sp_match") else "расхождение с KPI"
                st.caption(
                    f"Пересчёт ТЗ: {tz.get('available', 0)} / {tz.get('total', 0)} = {pct(tz.get('pct') or 0)}% "
                    f"({tz_ok}"
                    + (
                        f", KPI {pct(verify.get('tz_kpi') or 0)}%"
                        if verify.get("tz_kpi") is not None
                        else ""
                    )
                    + f"). СП: {sp.get('available', 0)} / {sp.get('total', 0)} = {pct(sp.get('pct') or 0)}% "
                    f"({sp_ok}). Позиции без остатка сверху."
                )
            st.dataframe(pd.DataFrame(detail), width="stretch", hide_index=True, height=360)
        else:
            st.caption(
                "Построчный список SKU появится после ближайшей синхронизации остатков топ-корзины. "
                "До этого проверка — таблица «доступно / всего» выше: она даёт тот же % что KPI."
            )


def render_body(dashboard: Optional[dict]) -> None:
    if not dashboard:
        st.warning(
            "Дашборд не удалось собрать по текущим данным. "
            "Проверьте раздел «Диагностика данных» и подключение к базе."
        )
        return

    meta = dashboard.get("meta") or {}
    if meta.get("empty"):
        st.info("Нет данных за выбранный период. Измените магазин или период либо обновите данные.")
        return

    charts = dashboard.get("charts", {})
    kpi_col, chart_col = st.columns([1.25, 1.0])
    with kpi_col:
        st.markdown(render.kpis_html(dashboard.get("kpis", [])), unsafe_allow_html=True)
        if meta.get("risk_legend") and is_admin():
            st.caption(meta["risk_legend"])
    with chart_col:
        with st.container(border=True):
            if charts.get("show_plan_chart") and charts.get("plan_vs_store"):
                st.markdown("### Выполнение плана по магазинам")
                st.plotly_chart(plan_chart(charts.get("plan_vs_store", [])), width="stretch", config=_CHART_CONFIG)
            else:
                st.markdown("### Списания, % к выручке по магазинам")
                st.caption("План не задан в 1С — рядом с основными KPI показаны списания к выручке.")
                st.plotly_chart(
                    losses_pct_chart(charts.get("losses_pct_vs_store", [])),
                    width="stretch",
                    config=_CHART_CONFIG,
                )

    if SHOW_ACTION_LAYER and is_admin():
        st.markdown("### Слой действий")
        for a in dashboard.get("actions") or []:
            st.markdown(
                f"**{a.get('priority')} · {a.get('title')}**  \n"
                f"{a.get('owner')} · {a.get('eta')}  \n"
                f"{a.get('rationale')}"
            )

    _render_alerts_native(dashboard.get("alerts") or [])

    st.markdown("### Таблица магазинов")
    st.caption("г/г — сравнение с тем же периодом прошлого года. На узком экране прокрутите таблицу вправо.")
    money_unit = str(meta.get("money_unit") or "th_rub")
    df = _store_table_df(
        dashboard.get("store_table") or [],
        ly_available=bool(meta.get("ly_available")),
        plan_available=bool(meta.get("plan_available")),
        money_unit=money_unit,
    )
    if df.empty:
        st.caption("Нет данных для отображения")
    else:
        st.dataframe(df, width="stretch", hide_index=True, height=min(520, 48 + 36 * max(len(df), 1)))

    with st.container(border=True):
        _losses_structure_table(
            dashboard.get("losses") or charts.get("losses_structure") or [],
            money_unit,
            store=(dashboard.get("selection") or {}).get("store"),
        )

    # Availability aggregate + optional SKU detail
    av_tz = None
    for k in dashboard.get("kpis") or []:
        if k.get("code") == "shop_availability":
            av_tz = k.get("value")
    if av_tz is not None:
        st.markdown(f"**Доступность ТЗ (итог):** {pct(av_tz)}%")
    _availability_detail(meta, dashboard)

    # Penetration status
    for k in dashboard.get("kpis") or []:
        if k.get("code") == "pascucci_penetration":
            st.caption("Пенетрация Паскуччи: методология PBI / NEEDS_REVIEW — приближённая оценка по марке.")

    rank_metric = meta.get("ranking_metric") or "Списания, % к выручке"
    rank_help = meta.get("ranking_help") or f"Ранжирование по: {rank_metric}"
    c_top, c_bot = st.columns(2)
    with c_top:
        _render_ranks_native("Лидеры", dashboard.get("top_stores") or [], rank_help, money_unit=money_unit)
    with c_bot:
        _render_ranks_native("Аутсайдеры", dashboard.get("bottom_stores") or [], rank_help, money_unit=money_unit)

    insuff_names = meta.get("insufficient_stores") or []
    if insuff_names:
        floor_pct = meta.get("rank_median_floor_pct", 40)
        st.markdown("### Недостаточно данных для рейтинга")
        st.caption(
            f"Выручка ниже {floor_pct}% медианы сети за период — "
            "не включаются в «Лидеры» / «Аутсайдеры»."
        )
        for n in insuff_names:
            st.markdown(f"- {n}")

    dd = dashboard.get("drilldown") or {}
    drill_store = (dd.get("store") or "").strip() or "—"
    st.markdown("### Карточка магазина")
    period_caption = meta.get("period_label") or "выбранный период"
    st.caption(
        f"Показан магазин: **{drill_store}** "
        "(выбранный фильтром или самый проблемный по сети). "
        f"Показатели за {period_caption}."
    )
    if dd:
        summary = dd.get("summary") or {}
        yoy_s = summary.get("yoy")
        yoy_txt = "нет данных за прошлый год" if yoy_s is None else f"{pct(yoy_s)}%"
        st.markdown(
            f"**Магазин: {drill_store}**  \n"
            f"Риск: {risk_label_display(summary.get('risk_level'))} · "
            f"План: {'не задан' if summary.get('plan_pct') is None else pct(summary.get('plan_pct')) + '%'} · "
            f"Доля СП: {pct(summary.get('own_production_share_pct') or 0)}% · "
            f"г/г (LFL): {yoy_txt}"
        )
        period_kpis = dd.get("month_kpis") or dd.get("day_kpis") or []
        if meta.get("custom_from"):
            with st.container(border=True):
                st.markdown(f"#### {period_caption}")
                st.markdown(
                    render.kpis_html(period_kpis, stacked=True),
                    unsafe_allow_html=True,
                )
        else:
            d1, d2, d3 = st.columns(3, gap="small")
            with d1:
                with st.container(border=True):
                    st.markdown("#### День")
                    st.markdown(
                        render.kpis_html(dd.get("day_kpis") or [], stacked=True),
                        unsafe_allow_html=True,
                    )
            with d2:
                with st.container(border=True):
                    st.markdown("#### Неделя")
                    st.markdown(
                        render.kpis_html(dd.get("week_kpis") or [], stacked=True),
                        unsafe_allow_html=True,
                    )
            with d3:
                with st.container(border=True):
                    st.markdown("#### Месяц")
                    st.markdown(
                    render.kpis_html(dd.get("month_kpis") or [], stacked=True),
                    unsafe_allow_html=True,
                )
        st.caption("Пенетрация Паскуччи: методология PBI / NEEDS_REVIEW — фильтр марки «Паскуччи».")

        st.markdown("#### Причины отклонений")
        reasons = dd.get("reasons") or []
        if reasons:
            for x in reasons:
                st.markdown(f"- {x}")
        else:
            st.caption("Нет сформулированных причин")

        drivers = dd.get("loss_drivers") or []
        if drivers:
            st.markdown("#### Основные причины списаний / расходов")
            total = sum(float(x.get("amount") or 0) for x in drivers) or 1.0
            for x in drivers:
                share = 100.0 * float(x.get("amount") or 0) / total
                st.markdown(
                    f"- **{x.get('group')}** — {format_money(x.get('amount'), unit=money_unit)} "
                    f"({pct(share)}% вклада в top-статьи)"
                )

        net_ctx = dd.get("network_context") or []
        if net_ctx:
            st.markdown("#### Сравнение с сетью")
            for x in net_ctx:
                st.markdown(f"- {x}")

        if is_admin():
            local_risks = dd.get("local_risks") or []
            st.markdown("#### Локальные риски")
            if local_risks:
                for a in local_risks:
                    st.warning(f"**{a.get('title')}** — {a.get('comment') or ''} ({pct(a.get('value'))})")
            else:
                st.success("Локальных рисков не выявлено")
    else:
        st.caption("Выберите магазин или загрузите данные для детализации.")

    abbr = meta.get("abbreviations") or {}
    if abbr:
        with st.expander("Сокращения"):
            for k, v in abbr.items():
                st.markdown(f"- **{k}** — {v}")


def render_dashboard(dashboard: Optional[dict], status_text: str = "") -> None:
    render_hero(dashboard, status_text=status_text)
    render_body(dashboard)
