"""Календарное окно UI и короткие служебные подписи (без Streamlit)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

HISTORY_MIN = date(2025, 1, 1)


def default_yesterday(today: Optional[date] = None, max_day: Optional[date] = None) -> date:
    """Стартовое окно UI: вчерашний день (не позже max_day, не раньше HISTORY_MIN)."""
    today = today or date.today()
    y = today - timedelta(days=1)
    if max_day is not None:
        y = min(y, max_day)
    return max(y, HISTORY_MIN)


def format_period_label(start: date | datetime | str, end: date | datetime | str) -> str:
    """Подпись периода: 12.08.2026 или 01.08.2026 – 12.08.2026."""

    def _as_date(v: date | datetime | str) -> Optional[date]:
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            return None

    a, b = _as_date(start), _as_date(end)
    if a is None and b is None:
        return "—"
    if a is None:
        a = b
    if b is None:
        b = a
    if a > b:
        a, b = b, a
    if a == b:
        return a.strftime("%d.%m.%Y")
    return f"{a.strftime('%d.%m.%Y')} – {b.strftime('%d.%m.%Y')}"


def default_period_range(anchor: date, period: str, max_day: date) -> tuple[date, date]:
    """Совместимость тестов: окно день/неделя/месяц относительно якоря."""
    if period == "day":
        d = min(max(anchor, HISTORY_MIN), max_day)
        return d, d
    if period == "week":
        start = anchor - timedelta(days=anchor.weekday())
        end = start + timedelta(days=6)
        return max(start, HISTORY_MIN), min(end, max_day)
    start = anchor.replace(day=1)
    if start.month == 12:
        end = date(start.year, 12, 31)
    else:
        end = date(start.year, start.month + 1, 1) - timedelta(days=1)
    return max(start, HISTORY_MIN), min(end, max_day)


def format_sync_caption(raw: dict[str, Any], sql_result: Any = None) -> str:
    synced = (
        (getattr(sql_result, "last_success_at", None) if sql_result else None)
        or raw.get("_cache_synced_at")
        or "—"
    )
    display = synced
    try:
        s = str(synced).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        display = dt.strftime("%d.%m.%Y %H:%M")
    except Exception:  # noqa: BLE001
        display = str(synced)
    src = raw.get("_data_source") or "—"
    if src == "local_cache":
        return f"Данные обновлены из 1С: {display}."
    return f"Источник: {src}. Данные обновлены из 1С: {display}."
