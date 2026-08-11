"""Централизованный словарь схемы исходного Excel War Room.

Источник истины по алиасам: ``War-Room_Katalog_Metrik_SQL.xlsx`` → лист
«Словарь_алиасов» (см. ``sheet_mapping`` / ``column_mapping``).

Канонические имена колонок совпадают с ожиданиями ``MetricsService``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.ingestion.column_mapping import COLUMN_ALIASES_BY_SHEET
from app.ingestion.sheet_mapping import SHEET_ALIASES, SHEET_CANONICAL_TO_SCHEMA

__all__ = ["ColumnSpec", "SheetSpec", "SCHEMA", "META_SHEET", "get_sheet_spec"]


@dataclass(frozen=True)
class ColumnSpec:
    """Описание одной канонической колонки листа."""

    canonical: str
    aliases: tuple[str, ...] = ()
    dtype: str = "float"  # 'float' | 'int' | 'str' | 'date'
    required: bool = False
    default: object = 0
    fill_default: bool = True


@dataclass(frozen=True)
class SheetSpec:
    """Описание одного канонического листа."""

    canonical: str
    aliases: tuple[str, ...]
    columns: tuple[ColumnSpec, ...]
    critical: bool = False
    key_column: Optional[str] = "Магазин"

    def required_columns(self) -> list[ColumnSpec]:
        return [c for c in self.columns if c.required]


def _cols_from_catalog(sheet_ru: str, *, skip: tuple[str, ...] = ()) -> tuple[ColumnSpec, ...]:
    specs = []
    skip_n = {s.casefold() for s in skip}
    for c in COLUMN_ALIASES_BY_SHEET.get(sheet_ru, ()):
        if c.canonical.casefold() in skip_n:
            continue
        dtype = c.dtype if c.dtype != "int" else "float"
        fill = c.dtype not in ("str", "date")
        default: object = 0 if fill else ("" if c.dtype in ("str", "date") else 0)
        specs.append(
            ColumnSpec(
                canonical=c.canonical,
                aliases=c.aliases,
                dtype=dtype if c.dtype != "date" else "str",
                required=c.required,
                default=default,
                fill_default=fill and c.dtype not in ("str", "date"),
            )
        )
    return tuple(specs)


def _sheet(schema_key: str, sheet_ru: str, *, critical: bool = False, key_column: Optional[str] = "Магазин") -> SheetSpec:
    aliases = SHEET_ALIASES.get(sheet_ru, (sheet_ru,))
    # Ensure SCHEMA english key is also an alias
    alias_set = list(dict.fromkeys([*aliases, schema_key, sheet_ru]))
    return SheetSpec(
        canonical=schema_key,
        aliases=tuple(alias_set),
        columns=_cols_from_catalog(sheet_ru),
        critical=critical,
        key_column=key_column,
    )


SCHEMA: dict[str, SheetSpec] = {
    SHEET_CANONICAL_TO_SCHEMA["продажи_месяц"]: _sheet("sales_month", "продажи_месяц", critical=True),
    SHEET_CANONICAL_TO_SCHEMA["доступность_неделя"]: _sheet("availability_week", "доступность_неделя"),
    SHEET_CANONICAL_TO_SCHEMA["сп_месяц"]: _sheet("sp_month", "сп_месяц"),
    SHEET_CANONICAL_TO_SCHEMA["остатки_месяц"]: _sheet("stock_month", "остатки_месяц"),
    SHEET_CANONICAL_TO_SCHEMA["потери_месяц"]: _sheet("losses_month", "потери_месяц"),
    SHEET_CANONICAL_TO_SCHEMA["продажи_день"]: _sheet("sales_day", "продажи_день"),
    SHEET_CANONICAL_TO_SCHEMA["продажи_неделя"]: _sheet("sales_week", "продажи_неделя"),
    SHEET_CANONICAL_TO_SCHEMA["пенетрация_неделя"]: _sheet("penetration_week", "пенетрация_неделя"),
    SHEET_CANONICAL_TO_SCHEMA["списания_неделя"]: _sheet("writeoff_week", "списания_неделя"),
    SHEET_CANONICAL_TO_SCHEMA["расходы_месяц"]: _sheet("expenses_month", "расходы_месяц"),
    SHEET_CANONICAL_TO_SCHEMA["прибыль_месяц"]: _sheet("profit_month", "прибыль_месяц"),
    SHEET_CANONICAL_TO_SCHEMA["цели"]: _sheet("targets", "цели", key_column=None),
}


@dataclass(frozen=True)
class MetaSheetSpec:
    """Лист ``meta`` устроен как key/value, а не как таблица магазинов."""

    canonical: str = "meta"
    aliases: tuple[str, ...] = SHEET_ALIASES["meta"]
    key_col: str = "ключ"
    key_col_aliases: tuple[str, ...] = COLUMN_ALIASES_BY_SHEET["meta"][0].aliases + ("ключ",)
    value_col: str = "значение"
    value_col_aliases: tuple[str, ...] = COLUMN_ALIASES_BY_SHEET["meta"][1].aliases + ("значение",)


META_SHEET = MetaSheetSpec()


def get_sheet_spec(canonical: str) -> Optional[SheetSpec]:
    return SCHEMA.get(canonical)
