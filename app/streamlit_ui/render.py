"""HTML-рендер секций дашборда, повторяющий render-функции исходного фронтенда.

Каждая функция возвращает строку HTML, которая вставляется через
``st.markdown(..., unsafe_allow_html=True)`` и использует те же CSS-классы,
что и оригинальный ``index.html``.
"""
from __future__ import annotations

from typing import Optional

from app.streamlit_ui.formatting import escape, integer, money, pct

__all__ = [
    "hero_html",
    "kpis_html",
    "actions_html",
    "alerts_html",
    "store_table_html",
    "ranks_html",
    "drilldown_html",
]

_STATUS = {"green": "green", "yellow": "yellow", "red": "red", "blue": "blue", "neutral": ""}


def _status_class(status: Optional[str]) -> str:
    return _STATUS.get(status or "", "")


def _has(value) -> bool:
    return value is not None


def hero_html(data: dict) -> str:
    """Верхняя панель-герой с мета-плитками (период, контур, режим, обновление, сеть)."""
    selection = data.get("selection") or {}
    meta = data.get("meta") or {}
    scope_label = "Вся сеть" if data.get("scope") == "network" else (selection.get("store") or "Магазин")
    items = [
        ("Период", str(data.get("period", "")).upper()),
        ("Контур", scope_label),
        ("Режим", data.get("mode", "")),
        ("Обновление", data.get("last_update", "")),
        ("Сеть", meta.get("network", "")),
    ]
    boxes = "".join(
        f"<div class='meta-box'><div class='k'>{escape(k)}</div><div class='v'>{escape(v)}</div></div>"
        for k, v in items
    )
    return (
        "<div class='panel hero'>"
        "<div class='pill'>WAR ROOM V2</div>"
        "<h1>Operational Cockpit — drill-down + action layer</h1>"
        "<p>Версия для оценки визуального считывания в боевом режиме: сеть магазинов, "
        "сигналы риска, детализация магазина и слой управленческих действий по проблемным KPI.</p>"
        f"<div class='hero-meta'>{boxes}</div>"
        "</div>"
    )


def kpis_html(items: list[dict]) -> str:
    """Сетка из KPI-карточек."""
    cards = []
    for k in items:
        sub = escape(k.get("hint") or "")
        if _has(k.get("plan")):
            sub += f" · план {money(k['plan'])}"
        if _has(k.get("delta_pct")):
            sign = "+" if (k["delta_pct"] or 0) > 0 else ""
            sub += f" · {sign}{pct(k['delta_pct'])}%"
        cards.append(
            "<article class='card'>"
            f"<div class='metric-label'>{escape(k.get('label'))}</div>"
            f"<div class='metric-value {_status_class(k.get('status_color'))}'>{money(k.get('value'))}</div>"
            f"<div class='metric-sub'>{sub}</div>"
            "</article>"
        )
    return f"<div class='kpis'>{''.join(cards)}</div>"


def actions_html(items: list[dict]) -> str:
    """Список управленческих действий (action layer)."""
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
    """Список проблем и рисков."""
    if not items:
        return (
            "<div class='alert'><div><strong>Критичных сигналов нет</strong>"
            "<div class='subtle'>Контур работает в целевом диапазоне</div></div>"
            "<span class='badge green'>OK</span></div>"
        )
    rows = []
    for a in items:
        rows.append(
            "<div class='alert'><div>"
            f"<strong>{escape(a.get('title'))}</strong>"
            f"<div class='subtle'>{escape(a.get('store') or 'Сеть')} · {escape(a.get('comment') or '')}</div></div>"
            f"<span class='badge {_status_class(a.get('severity'))}'>{pct(a.get('value'))}</span></div>"
        )
    return "".join(rows)


def store_table_html(rows: list[dict]) -> str:
    """Таблица магазинов."""
    header = (
        "<thead><tr><th>Магазин</th><th>Выручка</th><th>% плана</th><th>YoY</th>"
        "<th>СП %</th><th>ТЗ %</th><th>СП avail %</th><th>Потери</th><th>Недостача</th><th>Риск</th></tr></thead>"
    )
    body_rows = []
    for r in rows:
        body_rows.append(
            "<tr>"
            f"<td>{escape(r.get('store'))}</td>"
            f"<td>{money(r.get('revenue'))}</td>"
            f"<td class='{_status_class(r.get('status_color'))}'>{pct(r.get('plan_pct') or 0)}%</td>"
            f"<td>{pct(r.get('yoy') or 0)}%</td>"
            f"<td>{pct(r.get('own_production_share_pct') or 0)}%</td>"
            f"<td>{pct(r.get('shop_availability') or 0)}%</td>"
            f"<td>{pct(r.get('production_availability') or 0)}%</td>"
            f"<td>{money(r.get('losses') or 0)}</td>"
            f"<td>{money(r.get('inventory_shortage') or 0)}</td>"
            f"<td><span class='badge {_status_class(r.get('status_color'))}'>{escape(r.get('risk_level'))}</span></td>"
            "</tr>"
        )
    if not body_rows:
        body_rows.append("<tr><td colspan='10' class='subtle'>Нет данных для отображения</td></tr>")
    return f"<div class='table-wrap'><table class='war'>{header}<tbody>{''.join(body_rows)}</tbody></table></div>"


def _rank_row(r: dict) -> str:
    return (
        "<div class='rank'><div>"
        f"<strong>{escape(r.get('store'))}</strong>"
        f"<div class='subtle'>Выручка {money(r.get('revenue'))} млн · Потери {money(r.get('losses') or 0)} млн</div></div>"
        f"<span class='badge {_status_class(r.get('status_color'))}'>{pct(r.get('plan_pct') or 0)}%</span></div>"
    )


def ranks_html(rows: list[dict]) -> str:
    """Список лидеров/аутсайдеров."""
    if not rows:
        return "<div class='subtle'>Нет данных</div>"
    return "".join(_rank_row(r) for r in rows)


def _mini_kpis(title: str, items: list[dict]) -> str:
    cells = "".join(
        "<div class='mini'>"
        f"<div class='subtle'>{escape(k.get('label'))}</div>"
        f"<div class='v {_status_class(k.get('status_color'))}'>{money(k.get('value'))}</div>"
        f"<div class='subtle'>{escape(k.get('hint') or '')}</div></div>"
        for k in items
    )
    return f"<div><div class='section-title' style='font-size:15px'>{escape(title)}</div><div class='mini-grid'>{cells}</div></div>"


def drilldown_html(d: Optional[dict]) -> str:
    """Карточка drill-down по одному магазину."""
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
        risks_html = "<div class='alert'><div><strong>Локальных рисков не выявлено</strong></div><span class='badge green'>OK</span></div>"

    actions = "".join(
        "<div class='action'><div>"
        f"<strong>{escape(a.get('priority'))} · {escape(a.get('title'))}</strong>"
        f"<div class='subtle'>{escape(a.get('owner'))} · {escape(a.get('eta'))}</div>"
        f"<div class='subtle'>{escape(a.get('rationale'))}</div></div>"
        f"<span class='badge {_status_class(a.get('status_color'))}'>{escape(a.get('priority'))}</span></div>"
        for a in d.get("actions", [])
    )

    header_card = (
        "<div class='card' style='padding:16px'>"
        f"<div class='section-title'>{escape(d.get('store'))}</div>"
        f"<div class='subtle'>Риск: {escape(summary.get('risk_level'))} · "
        f"Выполнение плана: {pct(summary.get('plan_pct') or 0)}% · "
        f"СП: {pct(summary.get('own_production_share_pct') or 0)}%</div></div>"
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
        "<div><div class='section-title'>Причины отклонений</div>"
        f"<div class='reasons'>{reasons}</div></div>"
        "<div><div class='section-title'>Локальные риски</div>"
        f"<div class='list'>{risks_html}</div></div>"
        "<div><div class='section-title'>Действия по магазину</div>"
        f"<div class='list'>{actions}</div></div>"
        "</div>"
    )
    return f"<div class='drill-top'>{left}{right}</div>"
