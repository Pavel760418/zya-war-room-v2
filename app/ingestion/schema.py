"""Централизованный словарь схемы исходного Excel War Room.

Здесь в одном месте собраны:
- канонические имена листов и их алиасы;
- канонические имена колонок, их алиасы, типы, обязательность и значения по умолчанию;
- правила приведения (coercion) и запасные значения (fallback).

Канонические имена листов/колонок специально совпадают с теми, которые ожидает
существующий ``MetricsService`` (excel-режим), чтобы бизнес-логику не переписывать.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

__all__ = ["ColumnSpec", "SheetSpec", "SCHEMA", "META_SHEET", "get_sheet_spec"]


@dataclass(frozen=True)
class ColumnSpec:
    """Описание одной канонической колонки листа."""

    canonical: str
    aliases: tuple[str, ...] = ()
    dtype: str = "float"  # 'float' | 'int' | 'str' | 'date'
    required: bool = False
    default: object = 0
    # Заполнять ли пропуски (NaN) значением ``default`` после приведения типа.
    fill_default: bool = True


@dataclass(frozen=True)
class SheetSpec:
    """Описание одного канонического листа."""

    canonical: str
    aliases: tuple[str, ...]
    columns: tuple[ColumnSpec, ...]
    # Лист критичен для сборки дашборда (без него отчёт сильно неполон).
    critical: bool = False
    key_column: Optional[str] = "Магазин"

    def required_columns(self) -> list[ColumnSpec]:
        return [c for c in self.columns if c.required]


# ---------------------------------------------------------------------------
# Определения листов
# ---------------------------------------------------------------------------

_STORE_ALIASES = ("магазин", "store", "точка", "тт", "объект", "shop", "название магазина")

SCHEMA: dict[str, SheetSpec] = {
    "sales_month": SheetSpec(
        canonical="sales_month",
        aliases=("продажи_месяц", "продажи месяц", "sales_month", "продажимесяц", "выручка_месяц", "продажи (месяц)"),
        critical=True,
        columns=(
            ColumnSpec("Магазин", _STORE_ALIASES, dtype="str", required=True, default=""),
            ColumnSpec("Месяц", ("месяц", "period", "период", "month"), dtype="str", required=False, default="", fill_default=False),
            ColumnSpec("Выручка факт", ("выручка факт", "выручка", "revenue", "факт выручка", "rto факт", "оборот факт"), dtype="float", required=True, default=0),
            ColumnSpec("Выручка план", ("выручка план", "план выручки", "plan", "план", "rto план", "оборот план"), dtype="float", required=False, default=0),
            ColumnSpec("Количество чеков", ("количество чеков", "чеки", "checks", "кол-во чеков", "число чеков", "чеков"), dtype="float", required=False, default=0),
        ),
    ),
    "availability_week": SheetSpec(
        canonical="availability_week",
        aliases=("доступность_неделя", "доступность неделя", "availability_week", "availability", "доступность"),
        columns=(
            ColumnSpec("Магазин", _STORE_ALIASES, dtype="str", required=True, default=""),
            ColumnSpec("Топ ТЗ всего позиций", ("топ тз всего позиций", "тз всего", "top tz total", "тз всего позиций"), dtype="float", default=0),
            ColumnSpec("Топ ТЗ доступно позиций", ("топ тз доступно позиций", "тз доступно", "top tz available", "тз доступно позиций"), dtype="float", default=0),
            ColumnSpec("Топ СП всего позиций", ("топ сп всего позиций", "сп всего", "top sp total", "сп всего позиций"), dtype="float", default=0),
            ColumnSpec("Топ СП доступно позиций", ("топ сп доступно позиций", "сп доступно", "top sp available", "сп доступно позиций"), dtype="float", default=0),
        ),
    ),
    "sp_month": SheetSpec(
        canonical="sp_month",
        aliases=("сп_месяц", "сп месяц", "sp_month", "собственное производство месяц", "спмесяц"),
        columns=(
            ColumnSpec("Магазин", _STORE_ALIASES, dtype="str", required=True, default=""),
            ColumnSpec("Выручка СП", ("выручка сп", "revenue sp", "выручка собственного производства", "сп выручка"), dtype="float", default=0),
            ColumnSpec("Валовая прибыль СП", ("валовая прибыль сп", "gross profit sp", "вп сп"), dtype="float", default=0),
        ),
    ),
    "stock_month": SheetSpec(
        canonical="stock_month",
        aliases=("остатки_месяц", "остатки месяц", "stock_month", "запасы месяц", "остаткимесяц"),
        columns=(
            ColumnSpec("Магазин", _STORE_ALIASES, dtype="str", required=True, default=""),
            ColumnSpec("Остатки на конец месяца факт", ("остатки на конец месяца факт", "остатки факт", "stock fact", "остатки конец месяца факт"), dtype="float", default=0),
            ColumnSpec("Остатки на конец месяца план", ("остатки на конец месяца план", "остатки план", "stock plan", "остатки конец месяца план"), dtype="float", default=0),
        ),
    ),
    "losses_month": SheetSpec(
        canonical="losses_month",
        aliases=("потери_месяц", "потери месяц", "losses_month", "потеримесяц", "списания месяц"),
        columns=(
            ColumnSpec("Магазин", _STORE_ALIASES, dtype="str", required=True, default=""),
            ColumnSpec("Вид потерь", ("вид потерь", "тип потерь", "loss type", "категория потерь"), dtype="str", default="", fill_default=False),
            ColumnSpec("Сумма", ("сумма", "amount", "потери", "сумма потерь", "итого"), dtype="float", default=0),
        ),
    ),
    # --- Ниже листы, которые сейчас читаются, но напрямую в KPI не участвуют. ---
    "sales_day": SheetSpec(
        canonical="sales_day",
        aliases=("продажи_день", "продажи день", "sales_day"),
        columns=(
            ColumnSpec("Магазин", _STORE_ALIASES, dtype="str", required=True, default=""),
            ColumnSpec("Дата", ("дата", "date", "день"), dtype="str", default="", fill_default=False),
            ColumnSpec("Выручка факт", ("выручка факт", "выручка", "revenue"), dtype="float", default=0),
            ColumnSpec("Выручка план", ("выручка план", "план"), dtype="float", default=0),
            ColumnSpec("Количество чеков", ("количество чеков", "чеки"), dtype="float", default=0),
        ),
    ),
    "sales_week": SheetSpec(
        canonical="sales_week",
        aliases=("продажи_неделя", "продажи неделя", "sales_week"),
        columns=(
            ColumnSpec("Магазин", _STORE_ALIASES, dtype="str", required=True, default=""),
            ColumnSpec("Неделя", ("неделя", "week"), dtype="str", default="", fill_default=False),
            ColumnSpec("Выручка факт", ("выручка факт", "выручка"), dtype="float", default=0),
            ColumnSpec("Выручка план", ("выручка план", "план"), dtype="float", default=0),
            ColumnSpec("Количество чеков", ("количество чеков", "чеки"), dtype="float", default=0),
        ),
    ),
    "penetration_week": SheetSpec(
        canonical="penetration_week",
        aliases=("пенетрация_неделя", "пенетрация неделя", "penetration_week"),
        columns=(
            ColumnSpec("Магазин", _STORE_ALIASES, dtype="str", required=True, default=""),
            ColumnSpec("Чеков всего", ("чеков всего", "всего чеков"), dtype="float", default=0),
            ColumnSpec("Чеков с СП", ("чеков с сп", "чеки сп"), dtype="float", default=0),
            ColumnSpec("Чеков с Паскуччи", ("чеков с паскуччи", "чеки паскуччи"), dtype="float", default=0),
        ),
    ),
    "writeoff_week": SheetSpec(
        canonical="writeoff_week",
        aliases=("списания_неделя", "списания неделя", "writeoff_week"),
        columns=(
            ColumnSpec("Магазин", _STORE_ALIASES, dtype="str", required=True, default=""),
            ColumnSpec("Итого", ("итого", "всего", "total"), dtype="float", default=0),
        ),
    ),
    "expenses_month": SheetSpec(
        canonical="expenses_month",
        aliases=("расходы_месяц", "расходы месяц", "expenses_month"),
        columns=(ColumnSpec("Магазин", _STORE_ALIASES, dtype="str", required=True, default=""),),
    ),
    "profit_month": SheetSpec(
        canonical="profit_month",
        aliases=("прибыль_месяц", "прибыль месяц", "profit_month"),
        columns=(ColumnSpec("Магазин", _STORE_ALIASES, dtype="str", required=True, default=""),),
    ),
    "targets": SheetSpec(
        canonical="targets",
        aliases=("цели", "targets", "пороги", "нормативы"),
        key_column=None,
        columns=(ColumnSpec("Метрика", ("метрика", "metric", "показатель"), dtype="str", required=False, default="", fill_default=False),),
    ),
}


@dataclass(frozen=True)
class MetaSheetSpec:
    """Лист ``meta`` устроен как key/value, а не как таблица магазинов."""

    canonical: str = "meta"
    aliases: tuple[str, ...] = ("meta", "мета", "параметры", "настройки")
    key_col: str = "ключ"
    key_col_aliases: tuple[str, ...] = ("ключ", "key", "параметр", "name")
    value_col: str = "значение"
    value_col_aliases: tuple[str, ...] = ("значение", "value", "val", "данные")


META_SHEET = MetaSheetSpec()


def get_sheet_spec(canonical: str) -> Optional[SheetSpec]:
    return SCHEMA.get(canonical)
