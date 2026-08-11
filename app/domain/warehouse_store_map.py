"""Mapping склад (_Reference76) → магазин War Room (кандидат, не IT-подпись)."""

from __future__ import annotations

import re
from typing import Optional

# Heuristic: названия складов из SQL содержат «Склад <имя>».
_WAREHOUSE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"акушин", re.I), "Акушинка"),
    (re.compile(r"каспий", re.I), "Каспийский"),
    (re.compile(r"\bбкк\b", re.I), "БКК"),
    (re.compile(r"ленинград", re.I), "Ленинград"),
    (re.compile(r"молоток", re.I), "Молоток"),
    (re.compile(r"пят", re.I), "Пятерочка"),
    (re.compile(r"север", re.I), "Северный"),
    (re.compile(r"\bсити\b", re.I), "Сити"),
    (re.compile(r"шамил|шахан", re.I), "Шахан 10"),
    (re.compile(r"\b107\b|склад\s*107", re.I), "Склад 107"),
    (re.compile(r"экспресс", re.I), "Экспресса"),
    (re.compile(r"\bрц\b", re.I), "РЦ"),
]


def warehouse_to_store(warehouse_name: Optional[str]) -> str:
    if not warehouse_name:
        return "Неизвестный склад / требуется mapping"
    text = str(warehouse_name).strip()
    for pat, store in _WAREHOUSE_PATTERNS:
        if pat.search(text):
            return store
    return "Неизвестный склад / требуется mapping"
