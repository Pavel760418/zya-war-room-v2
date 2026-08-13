"""HTML-рендер секций дашборда МегаМетрики."""
from __future__ import annotations

from typing import Optional

from app.streamlit_ui.formatting import (
    escape,
    format_checks,
    format_currency_thousands,
    format_kpi_value,
    pct,
)

__all__ = [
    "hero_html",
    "kpis_html",
    "actions_html",
    "alerts_html",
    "store_table_html",
    "ranks_html",
    "drilldown_html",
    "abbr_legend_html",
    "risk_label_display",
]

_STATUS = {"green": "green", "yellow": "yellow", "red": "red", "blue": "blue", "neutral": ""}

_PERIOD_RU = {"day": "День", "week": "Неделя", "month": "Месяц"}


def _status_class(status: Optional[str]) -> str:
    return _STATUS.get(status or "", "")


def _has(value) -> bool:
    return value is not None


def _fmt_plan_pct(value) -> str:
    if value is None:
        return "не задан"
    return f"{pct(value)}%"


def _fmt_yoy(value) -> str:
    if value is None:
        return "нет данных"
    return f"{pct(value)}%"


def _risk_badge_class(risk_level: Optional[str], status_color: Optional[str] = None) -> str:
    """Цвет бейджа строго по уровню риска (высокий=red)."""
    mapped = {"низкий": "green", "средний": "yellow", "высокий": "red",
              "Низкий": "green", "Средний": "yellow", "Высокий": "red"}
    if risk_level in mapped:
        return mapped[risk_level]
    return _status_class(status_color)


def risk_label_display(risk_level: Optional[str]) -> str:
    raw = (risk_level or "средний").strip().lower()
    return {"низкий": "Низкий", "средний": "Средний", "высокий": "Высокий"}.get(raw, "Средний")


def _risk_label_display(risk_level: Optional[str]) -> str:
    return risk_label_display(risk_level)


_SEV_RU = {"blue": "Инфо", "yellow": "Внимание", "red": "Критично", "green": "Норма"}


def hero_html(data: dict) -> str:
    """Верхняя панель-герой с мета-плитками."""
    selection = data.get("selection") or {}
    meta = data.get("meta") or {}
    scope_label = "Вся сеть" if data.get("scope") == "network" else (selection.get("store") or "Магазин")
    period_code = str(data.get("period", "") or "")
    period_label = meta.get("period_label") or _PERIOD_RU.get(period_code, period_code)
    report_note = meta.get("report_note") or ""
    focus = meta.get("focus_text") or ""
    coverage = meta.get("coverage_label") or (
        "неполный охват" if meta.get("report_incomplete") else "полный охват"
    )
    items = [
        ("Период", period_label),
        ("Магазин", scope_label),
        ("Обновление", data.get("last_update", "")),
        ("Сеть", meta.get("network", "")),
        ("Охват данных", coverage),
    ]
    boxes = "".join(
        f"<div class='meta-box'><div class='k'>{escape(k)}</div><div class='v'>{escape(v)}</div></div>"
        for k, v in items
    )
    note = f"<p class='subtle' style='margin-top:12px'>{escape(report_note)}</p>" if report_note else ""
    focus_html = (
        f"<div class='meta-box focus-box' style='margin-top:12px;border-color:rgba(241,184,74,.45)'>"
        f"<div class='k'>Главный фокус периода</div>"
        f"<div class='v' style='font-size:16px'>{escape(focus)}</div></div>"
        if focus
        else ""
    )
    cache = meta.get("cache_note") or ""
    cache_html = f"<p class='subtle'>{escape(cache)}</p>" if cache else ""
    return (
        "<div class='panel hero'>"
        "<div class='pill'>МегаМетрики</div>"
        "<h1>Панель управления сетью</h1>"
        "<p>Сеть магазинов, сигналы риска и детализация по магазину. "
        "Источник — учётные данные 1С (только чтение).</p>"
        f"<div class='hero-meta'>{boxes}</div>"
        f"{focus_html}{note}{cache_html}"
        "</div>"
    )


def kpis_html(items: list[dict], *, stacked: bool = False) -> str:
    cards = []
    for k in items:
        sub = escape(k.get("hint") or "")
        if _has(k.get("delta_pct")):
            sign = "+" if (k["delta_pct"] or 0) > 0 else ""
            sub += f" · {sign}{pct(k['delta_pct'])}%"
        if k.get("yoy") is None and "г/г" in (k.get("hint") or "").lower():
            pass
        elif k.get("code", "").startswith("revenue") and k.get("yoy") is None and "прошлый год" in (k.get("hint") or ""):
            pass
        unit = k.get("unit") or ""
        if _has(k.get("plan")) and unit in {"th_rub", "mln_rub", "revenue", "money"}:
            sub += f" · план {format_kpi_value(k['plan'], unit)}"
        cards.append(
            "<article class='card'>"
            f"<div class='metric-label'>{escape(k.get('label'))}</div>"
            f"<div class='metric-value {_status_class(k.get('status_color'))}'>"
            f"{format_kpi_value(k.get('value'), unit)}</div>"
            f"<div class='metric-sub'>{sub}</div>"
            "</article>"
        )
    cls = "kpis kpis-stack" if stacked else "kpis"
    return f"<div class='{cls}'>{''.join(cards)}</div>"


def actions_html(items: list[dict]) -> str:
    if not items:
        return (
            "<div class='action'><div><strong>P3 · Поддерживать текущий операционный режим</strong>"
            "<div class='subtle'>Нет критичных действий</div></div>"
            "<span class='badge green'>P3</span></div>"
        )
    rows = []
    for a in items:
        rows.append(
            "<div class='action'><div>"
            f"<strong>{escape(a.get('priority'))} · {escape(a.get('title'))}</strong>"
            f"<div class='subtle'>{escape(a.get('owner'))} · {escape(a.get('eta'))}</div>"
            f"<div class='subtle'>{escape(a.get('rationale'))}</div></div>"
            f"<span class='badge {_status_class(a.get('status_color'))}'>{escape(a.get('priority'))}</span></div>"
        )
    return "".join(rows)


def alerts_html(items: list[dict]) -> str:
    if not items:
        return "<div class='subtle'>Активных сигналов нет</div>"
    rows = []
    for a in items:
        sev = str(a.get("severity") or "blue")
        sev_label = _SEV_RU.get(sev, "инфо")
        store = (a.get("store") or "").strip()
        store_bit = f"{escape(store)} · " if store else ""
        rows.append(
            "<div class='alert'><div>"
            f"<strong>{escape(a.get('title'))}</strong>"
            f"<div class='subtle'>{store_bit}{escape(a.get('comment') or '')}</div></div>"
            f"<span class='badge {_status_class(sev)}'>{escape(sev_label)}</span></div>"
        )
    return "".join(rows)


def store_table_html(rows: list[dict], *, ly_available: bool = False, plan_available: bool = False) -> str:
    plan_h = "% плана" if plan_available else "План"
    yoy_h = "г/г" if ly_available else "г/г"
    header = (
        "<thead><tr>"
        f"<th>Магазин</th><th>Выручка</th><th>{plan_h}</th><th>{yoy_h}</th>"
        "<th>Доля СП</th><th>Доступность ТЗ</th><th>Доступность СП</th>"
        "<th>Потери</th><th>Недостачи</th><th>Риск</th>"
        "</tr></thead>"
    )
    body_rows = []
    for r in rows:
        plan_cell = _fmt_plan_pct(r.get("plan_pct")) if plan_available else "не задан"
        yoy_cell = _fmt_yoy(r.get("yoy"))
        risk_label = _risk_label_display(r.get("risk_level"))
        body_rows.append(
            "<tr>"
            f"<td class='col-store'>{escape(r.get('store'))}</td>"
            f"<td>{format_currency_thousands(r.get('revenue'))}</td>"
            f"<td class='col-plan {_status_class(r.get('status_color'))}'>{escape(plan_cell)}</td>"
            f"<td class='col-yoy'>{escape(yoy_cell)}</td>"
            f"<td>{pct(r.get('own_production_share_pct') or 0)}%</td>"
            f"<td>{pct(r.get('shop_availability') or 0)}%</td>"
            f"<td>{pct(r.get('production_availability') or 0)}%</td>"
            f"<td>{format_currency_thousands(r.get('losses') or 0)}</td>"
            f"<td>{format_currency_thousands(r.get('inventory_shortage') or 0)}</td>"
            f"<td class='col-risk'><span class='badge {_risk_badge_class(risk_label, r.get('status_color'))}'>"
            f"{escape(risk_label)}</span></td>"
            "</tr>"
        )
    if not body_rows:
        body_rows.append("<tr><td colspan='10' class='subtle'>Нет данных для отображения</td></tr>")
    hint = (
        "<div class='subtle table-scroll-hint'>На узком экране прокрутите таблицу вправо → "
        "показаны ключевые колонки; остальные доступны скроллом.</div>"
    )
    return (
        f"{hint}<div class='table-wrap table-full'><table class='war'>{header}"
        f"<tbody>{''.join(body_rows)}</tbody></table></div>"
    )


def _rank_row(r: dict, *, metric_label: str) -> str:
    rev = r.get("revenue") or 0
    losses = r.get("losses") or 0
    loss_pct = round(float(losses) / max(float(rev), 0.01) * 100.0, 2)
    return (
        "<div class='rank'><div>"
        f"<strong class='store-name'>{escape(r.get('store'))}</strong>"
        f"<div class='subtle'>Выручка {format_currency_thousands(rev)}"
        f" · Потери {format_currency_thousands(losses)} ({pct(loss_pct)}%)</div></div>"
        f"<span class='badge {_status_class(r.get('status_color'))}'>{pct(loss_pct)}%</span></div>"
    )


def ranks_html(rows: list[dict], *, metric_label: str = "Потери, % к выручке") -> str:
    if not rows:
        return "<div class='subtle'>Нет данных</div>"
    head = f"<div class='subtle' style='margin-bottom:8px'>Ранжирование по: {escape(metric_label)}</div>"
    return head + "".join(_rank_row(r, metric_label=metric_label) for r in rows)


def _mini_kpis(title: str, items: list[dict]) -> str:
    cells = "".join(
        "<div class='mini'>"
        f"<div class='subtle'>{escape(k.get('label'))}</div>"
        f"<div class='v {_status_class(k.get('status_color'))}'>"
        f"{format_kpi_value(k.get('value'), k.get('unit'))}</div>"
        f"<div class='subtle'>{escape(k.get('hint') or '')}</div></div>"
        for k in items
    )
    return (
        f"<div><div class='section-title' style='font-size:17px;overflow:visible'>{escape(title)}</div>"
        f"<div class='mini-grid'>{cells}</div></div>"
    )


def drilldown_html(d: Optional[dict]) -> str:
    if not d:
        return "<div class='subtle'>Выберите магазин или загрузите данные для детализации.</div>"

    summary = d.get("summary") or {}
    reasons = "".join(f"<div class='reason'>{escape(x)}</div>" for x in d.get("reasons", []))

    local_risks = d.get("local_risks") or []
    if local_risks:
        risks_html = "".join(
            "<div class='alert'><div>"
            f"<strong>{escape(a.get('title'))}</strong>"
            f"<div class='subtle'>{escape(a.get('comment') or '')}</div></div>"
            f"<span class='badge {_status_class(a.get('severity'))}'>{pct(a.get('value'))}</span></div>"
            for a in local_risks
        )
    else:
        risks_html = (
            "<div class='alert'><div><strong>Локальных рисков не выявлено</strong></div>"
            "<span class='badge green'>OK</span></div>"
        )

    plan_txt = _fmt_plan_pct(summary.get("plan_pct"))
    store_name = (d.get("store") or summary.get("store") or "—").strip() or "—"
    header_card = (
        "<div class='card' style='padding:16px'>"
        f"<div class='store-heading'>Магазин: {escape(store_name)}</div>"
        f"<div class='subtle'>Риск: {escape(_risk_label_display(summary.get('risk_level')))} · "
        f"План: {escape(plan_txt)} · "
        f"Доля СП: {pct(summary.get('own_production_share_pct') or 0)}%</div></div>"
    )

    drivers = d.get("loss_drivers") or []
    if drivers:
        total = sum(float(x.get("amount") or 0) for x in drivers) or 1.0
        driver_rows = "".join(
            f"<div class='reason'><strong>{escape(x.get('group'))}</strong> — "
            f"{format_currency_thousands(x.get('amount'))} "
            f"({pct(100.0 * float(x.get('amount') or 0) / total)}% вклада в top-статьи)</div>"
            for x in drivers
        )
        drivers_block = (
            "<div><div class='section-title'>Основные причины потерь</div>"
            f"<div class='reasons'>{driver_rows}</div></div>"
        )
    else:
        drivers_block = ""

    net_ctx = d.get("network_context") or []
    ctx_html = "".join(f"<div class='reason'>{escape(x)}</div>" for x in net_ctx)
    ctx_block = (
        f"<div><div class='section-title'>Сравнение с сетью</div><div class='reasons'>{ctx_html}</div></div>"
        if ctx_html
        else ""
    )

    left = (
        "<div class='stack'>"
        f"{header_card}"
        f"{_mini_kpis('День', d.get('day_kpis', []))}"
        f"{_mini_kpis('Неделя', d.get('week_kpis', []))}"
        f"{_mini_kpis('Месяц', d.get('month_kpis', []))}"
        "</div>"
    )
    right = (
        "<div class='stack'>"
        "<article class='card focus-reasons' style='padding:16px'>"
        "<div class='section-title'>Причины отклонений</div>"
        f"<div class='reasons'>{reasons}</div></article>"
        f"{drivers_block}{ctx_block}"
        "<div><div class='section-title'>Локальные риски</div>"
        f"<div class='list'>{risks_html}</div></div>"
        "</div>"
    )
    return f"<div class='drill-top'>{left}{right}</div>"


def abbr_legend_html(abbreviations: dict) -> str:
    if not abbreviations:
        return ""
    items = "".join(
        f"<div class='subtle'><strong>{escape(k)}</strong> — {escape(v)}</div>" for k, v in abbreviations.items()
    )
    return (
        "<article class='card' style='margin-top:12px'>"
        "<div class='section-title'>Сокращения</div>"
        f"{items}</article>"
    )
