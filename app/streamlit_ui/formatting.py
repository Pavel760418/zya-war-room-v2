"""Форматирование чисел в стиле ``ru-RU`` для МегаМетрики.

Крупные суммы и проценты — два знака после запятой («29,57 млн руб.», «4,87%»).
Чеки (счётчики) — целые.
"""
from __future__ import annotations

import math
from html import escape as _html_escape

__all__ = [
    "money",
    "pct",
    "integer",
    "num",
    "escape",
    "format_currency_thousands",
    "format_currency_rub",
    "format_currency_mln",
    "format_money",
    "format_checks",
    "format_kpi_value",
]


def _safe_float(value: object) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(f) or math.isinf(f):
        return 0.0
    return f


def _format(value: object, decimals: int) -> str:
    f = _safe_float(value)
    formatted = f"{f:,.{decimals}f}"
    formatted = formatted.replace(",", "\u2009").replace(".", ",").replace("\u2009", " ")
    return formatted


def money(value: object) -> str:
    return _format(value, 2)


def format_currency_mln(value_rub: object) -> str:
    """Крупные суммы: ``29566049`` → ``29,57 млн руб.``."""
    f = _safe_float(value_rub)
    return f"{_format(f / 1_000_000.0, 2)} млн руб."


def format_currency_thousands(value_thousands: object) -> str:
    """Legacy: тысячи → млн (единый UI-формат Часть 2).

    Вход в тысячах: ``29424`` → ``29,42 млн руб.``.
    Если передали сырые рубли (≥1e6) — тоже корректно.
    """
    f = _safe_float(value_thousands)
    if abs(f) >= 1_000_000:
        return format_currency_mln(f)
    return format_currency_mln(f * 1000.0)


def format_currency_rub(value_rub: object) -> str:
    """Суммы в рублях → млн (единый формат). Для чека используйте unit=ticket."""
    return format_currency_mln(value_rub)


def format_money(value: object, *, unit: str = "th_rub") -> str:
    u = (unit or "th_rub").lower()
    if u in {"rub", "ruble", "rubles", "руб", "mln_rub"}:
        return format_currency_mln(value)
    if u in {"th_rub", "thousand_rub", "revenue", "money"}:
        return format_currency_thousands(value)
    return format_currency_mln(value)


def format_checks(value: object) -> str:
    return _format(round(_safe_float(value)), 0)


def format_kpi_value(value: object, unit: str | None = None) -> str:
    u = (unit or "").lower()
    if u in {"rub", "ruble", "rubles", "mln_rub", "th_rub", "thousand_rub", "revenue", "money"}:
        if u in {"th_rub", "thousand_rub"}:
            return format_currency_thousands(value)
        if u == "mln_rub":
            # legacy: value already in millions
            return f"{_format(value, 2)} млн руб."
        return format_currency_mln(value)
    if u in {"checks", "check", "count"}:
        return format_checks(value)
    if u in {"pct", "percent", "%"}:
        return f"{pct(value)}%"
    if u in {"ticket"}:
        return f"{_format(value, 2)} руб."
    return money(value)


def pct(value: object) -> str:
    return _format(value, 2)


def integer(value: object) -> str:
    return _format(value, 0)


def num(value: object, decimals: int = 2) -> str:
    return _format(value, decimals)


def escape(value: object) -> str:
    return _html_escape(str(value if value is not None else ""))
