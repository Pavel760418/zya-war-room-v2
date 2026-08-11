"""Sheet name mapping from War-Room_Katalog_Metrik_SQL.xlsx → Словарь_алиасов.

Canonical Russian sheet names (Excel template) map to SCHEMA keys used by
``MetricsService``. Aliases accept spelling variants without ingestion crashes.
"""
from __future__ import annotations

from typing import Optional

from app.ingestion.text_utils import normalize

__all__ = [
    "SHEET_CANONICAL_TO_SCHEMA",
    "SHEET_ALIASES",
    "resolve_sheet_name",
    "all_sheet_alias_norms",
]

# Catalog «Каноническое имя (лист)» → SCHEMA key in app/ingestion/schema.py
SHEET_CANONICAL_TO_SCHEMA: dict[str, str] = {
    "meta": "meta",
    "продажи_день": "sales_day",
    "продажи_неделя": "sales_week",
    "продажи_месяц": "sales_month",
    "доступность_неделя": "availability_week",
    "пенетрация_неделя": "penetration_week",
    "списания_неделя": "writeoff_week",
    "сп_месяц": "sp_month",
    "остатки_месяц": "stock_month",
    "расходы_месяц": "expenses_month",
    "прибыль_месяц": "profit_month",
    "потери_месяц": "losses_month",
    "цели": "targets",
}

# Catalog aliases (semicolon-separated in XLSX) + extras already used in the app.
SHEET_ALIASES: dict[str, tuple[str, ...]] = {
    "meta": ("meta", "Мета", "Параметры", "Настройки", "мета", "параметры", "настройки"),
    "продажи_день": (
        "продажи_день",
        "продажи день",
        "sales_day",
        "Продажи (день)",
        "продажидень",
    ),
    "продажи_неделя": (
        "продажи_неделя",
        "продажи неделя",
        "продажи по неделям",
        "sales_week",
        "продажинеделя",
    ),
    "продажи_месяц": (
        "продажи_месяц",
        "продажи месяц",
        "sales_month",
        "Продажи (месяц)",
        "продажимесяц",
        "выручка_месяц",
    ),
    "доступность_неделя": (
        "доступность_неделя",
        "доступность неделя",
        "доступность",
        "availability_week",
        "availability",
    ),
    "пенетрация_неделя": (
        "пенетрация_неделя",
        "пенетрация неделя",
        "penetration_week",
        "пенетрация",
    ),
    "списания_неделя": (
        "списания_неделя",
        "списания неделя",
        "write_offs_week",
        "writeoff_week",
        "списания",
    ),
    "сп_месяц": (
        "сп_месяц",
        "сп месяц",
        "own_production_month",
        "sp_month",
        "собственное производство месяц",
        "спмесяц",
    ),
    "остатки_месяц": (
        "остатки_месяц",
        "остатки месяц",
        "stock_month",
        "запасы месяц",
        "остаткимесяц",
    ),
    "расходы_месяц": (
        "расходы_месяц",
        "расходы месяц",
        "opex_month",
        "expenses_month",
    ),
    "прибыль_месяц": (
        "прибыль_месяц",
        "прибыль месяц",
        "profit_month",
    ),
    "потери_месяц": (
        "потери_месяц",
        "потери месяц",
        "losses_month",
        "потеримесяц",
        "списания месяц",
    ),
    "цели": ("цели", "targets", "goals", "пороги", "нормативы"),
}


def resolve_sheet_name(source_name: str) -> Optional[tuple[str, str]]:
    """Map a file sheet name → ``(russian_canonical, schema_key)``.

    Returns ``None`` if unknown (caller may fall back to fuzzy match in
    ``data_mapping.match_sheet``).
    """
    norm = normalize(source_name)
    if not norm:
        return None
    for canonical, aliases in SHEET_ALIASES.items():
        candidates = {normalize(canonical), *(normalize(a) for a in aliases)}
        if norm in candidates:
            schema_key = SHEET_CANONICAL_TO_SCHEMA.get(canonical, canonical)
            return canonical, schema_key
    # Direct SCHEMA english key
    for rus, schema_key in SHEET_CANONICAL_TO_SCHEMA.items():
        if norm == normalize(schema_key):
            return rus, schema_key
    return None


def all_sheet_alias_norms(canonical_ru: str) -> set[str]:
    aliases = SHEET_ALIASES.get(canonical_ru, ())
    norms = {normalize(canonical_ru), *(normalize(a) for a in aliases)}
    norms.discard("")
    return norms
