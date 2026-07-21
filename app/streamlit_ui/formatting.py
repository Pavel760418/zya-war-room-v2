"""Форматирование чисел в стиле ``ru-RU`` (как в исходном фронтенде).

Повторяет поведение ``Intl.NumberFormat('ru-RU', …)``: пробел как разделитель
разрядов и запятая как десятичный разделитель.
"""
from __future__ import annotations

import math
from html import escape as _html_escape

__all__ = ["money", "pct", "integer", "num", "escape"]


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
    # 1,234,567.8 -> 1 234 567,8 (пробел разряды, запятая дробная часть)
    formatted = formatted.replace(",", "\u2009").replace(".", ",").replace("\u2009", " ")
    return formatted


def money(value: object) -> str:
    """Денежный формат с одним знаком после запятой."""
    return _format(value, 1)


def pct(value: object) -> str:
    """Процентный формат с одним знаком после запятой (без символа %)."""
    return _format(value, 1)


def integer(value: object) -> str:
    """Целочисленный формат с разделителями разрядов."""
    return _format(value, 0)


def num(value: object, decimals: int = 1) -> str:
    return _format(value, decimals)


def escape(value: object) -> str:
    """Безопасно экранировать текст для вставки в HTML."""
    return _html_escape(str(value if value is not None else ""))
