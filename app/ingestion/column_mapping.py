"""Column alias dictionary from War-Room_Katalog_Metrik_SQL.xlsx → Словарь_алиасов.

Used by SCHEMA enrichment and by ``data_mapping.resolve_columns``.
Canonical column names match what ``MetricsService`` already expects
(spaces, Russian labels) — not the underscored SQL aliases from catalog SELECT.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.ingestion.text_utils import normalize

__all__ = [
    "ColumnAliasSpec",
    "COLUMN_ALIASES_BY_SHEET",
    "aliases_for",
    "resolve_column_name",
]


@dataclass(frozen=True)
class ColumnAliasSpec:
    canonical: str
    aliases: tuple[str, ...]
    required: bool = False
    dtype: str = "float"  # float | int | str | date


# Per catalog sheet (Russian canonical). Shared store aliases applied in schema.
_STORE = ("магазин", "店", "store", "Точка", "Филиал", "тт", "объект", "shop", "название магазина")

COLUMN_ALIASES_BY_SHEET: dict[str, tuple[ColumnAliasSpec, ...]] = {
    "meta": (
        ColumnAliasSpec("ключ", ("key", "Ключ", "параметр", "name"), required=True, dtype="str"),
        ColumnAliasSpec("значение", ("value", "Значение", "val", "данные"), required=True, dtype="str"),
    ),
    "продажи_день": (
        ColumnAliasSpec("Дата", ("дата", "date", "День"), required=True, dtype="date"),
        ColumnAliasSpec("Магазин", _STORE, required=True, dtype="str"),
        ColumnAliasSpec(
            "Выручка факт",
            ("выручка_факт", "revenue_fact", "Факт выручки", "Выручка,факт", "выручка факт", "выручка", "revenue", "rto факт"),
            required=True,
        ),
        ColumnAliasSpec(
            "Выручка план",
            ("выручка_план", "revenue_plan", "План выручки", "выручка план", "план", "rto план"),
            required=False,
        ),
        ColumnAliasSpec(
            "Количество чеков",
            ("чеки", "receipts", "Кол-во чеков", "Число чеков", "количество чеков", "checks", "чеков"),
            required=False,
            dtype="int",
        ),
    ),
    "продажи_неделя": (
        ColumnAliasSpec("Неделя", ("week", "Нед", "ISO-неделя", "неделя"), required=True, dtype="str"),
        ColumnAliasSpec("Магазин", _STORE, required=True, dtype="str"),
        ColumnAliasSpec("Выручка факт", ("выручка_факт", "revenue_fact", "выручка факт", "выручка"), required=True),
        ColumnAliasSpec("Выручка план", ("выручка_план", "revenue_plan", "выручка план", "план"), required=False),
        ColumnAliasSpec("Количество чеков", ("чеки", "receipts", "количество чеков", "checks"), required=False, dtype="int"),
    ),
    "продажи_месяц": (
        ColumnAliasSpec("Месяц", ("month", "Мес", "месяц", "period", "период"), required=True, dtype="str"),
        ColumnAliasSpec("Магазин", _STORE, required=True, dtype="str"),
        ColumnAliasSpec("Выручка факт", ("выручка_факт", "revenue_fact", "выручка факт", "выручка", "оборот факт"), required=True),
        ColumnAliasSpec("Выручка план", ("выручка_план", "revenue_plan", "выручка план", "план", "оборот план"), required=False),
        ColumnAliasSpec("Количество чеков", ("чеки", "receipts", "количество чеков", "checks", "кол-во чеков"), required=False, dtype="int"),
    ),
    "доступность_неделя": (
        ColumnAliasSpec("Магазин", _STORE, required=True, dtype="str"),
        ColumnAliasSpec("Неделя", ("week", "неделя"), required=False, dtype="str"),
        ColumnAliasSpec(
            "Топ ТЗ всего позиций",
            ("tz_total", "ТЗ всего", "топ тз всего позиций", "тз всего позиций", "Топ_ТЗ_всего_позиций"),
            required=False,
            dtype="int",
        ),
        ColumnAliasSpec(
            "Топ ТЗ доступно позиций",
            ("tz_available", "ТЗ доступно", "топ тз доступно позиций", "Топ_ТЗ_доступно_позиций"),
            required=False,
            dtype="int",
        ),
        ColumnAliasSpec(
            "Топ СП всего позиций",
            ("sp_total", "СП всего", "топ сп всего позиций", "Топ_СП_всего_позиций"),
            required=False,
            dtype="int",
        ),
        ColumnAliasSpec(
            "Топ СП доступно позиций",
            ("sp_available", "СП доступно", "топ сп доступно позиций", "Топ_СП_доступно_позиций"),
            required=False,
            dtype="int",
        ),
    ),
    "пенетрация_неделя": (
        ColumnAliasSpec("Магазин", _STORE, required=True, dtype="str"),
        ColumnAliasSpec("Неделя", ("week", "неделя"), required=False, dtype="str"),
        ColumnAliasSpec(
            "Чеков всего",
            ("total_receipts", "Чеков, всего", "чеков всего", "всего чеков", "Чеков_всего"),
            required=True,
            dtype="int",
        ),
        ColumnAliasSpec(
            "Чеков с СП",
            ("sp_receipts", "Чеков с собств. производством", "чеков с сп", "чеки сп", "Чеков_с_СП"),
            required=False,
            dtype="int",
        ),
        ColumnAliasSpec(
            "Чеков с Паскуччи",
            ("pasqucci_receipts", "Чеков с Pasqucci", "чеков с паскуччи", "Чеков_с_Паскуччи"),
            required=False,
            dtype="int",
        ),
        ColumnAliasSpec("Дата", ("date", "день", "дата"), required=False, dtype="date"),
    ),
    "списания_неделя": (
        ColumnAliasSpec("Магазин", _STORE, required=True, dtype="str"),
        ColumnAliasSpec("Дата", ("date", "день", "дата"), required=False, dtype="date"),
        ColumnAliasSpec("Неделя", ("week", "неделя"), required=False, dtype="str"),
        ColumnAliasSpec(
            "Статья списания",
            ("writeoff_article", "статья", "статья списания тмц", "Статья_списания"),
            required=False,
            dtype="str",
        ),
        ColumnAliasSpec("Сумма", ("amount", "сумма", "сумма списания"), required=False),
        ColumnAliasSpec("ФРОФ", ("frof", "фроф", "ФРОВ"), required=False),
        ColumnAliasSpec("Пасскучи", ("паскуччи", "pasqucci", "Паскуччи"), required=False),
        ColumnAliasSpec("Производство", ("production", "произв-во", "производство"), required=False),
        ColumnAliasSpec(
            "Потеря потребительских свойств",
            ("loss_of_quality", "порча", "Потеря_потребительских_свойств"),
            required=False,
        ),
        ColumnAliasSpec("Итого", ("total", "всего списано", "итого", "всего"), required=False),
    ),
    "сп_месяц": (
        ColumnAliasSpec("Магазин", _STORE, required=True, dtype="str"),
        ColumnAliasSpec("Месяц", ("month", "месяц"), required=False, dtype="str"),
        ColumnAliasSpec("Выручка СП", ("sp_revenue", "выручка сп", "Выручка_СП"), required=True),
        ColumnAliasSpec("Валовая прибыль СП", ("sp_gross_profit", "валовая прибыль сп", "Валовая_прибыль_СП", "вп сп"), required=True),
    ),
    "остатки_месяц": (
        ColumnAliasSpec("Магазин", _STORE, required=True, dtype="str"),
        ColumnAliasSpec("Месяц", ("month", "месяц"), required=False, dtype="str"),
        ColumnAliasSpec(
            "Остатки на конец месяца факт",
            ("stock_fact", "остатки факт", "Остатки_на_конец_месяца_факт"),
            required=True,
        ),
        ColumnAliasSpec(
            "Остатки на конец месяца план",
            ("stock_plan", "остатки план", "Остатки_на_конец_месяца_план"),
            required=False,
        ),
    ),
    "расходы_месяц": (
        ColumnAliasSpec("Магазин", _STORE, required=True, dtype="str"),
        ColumnAliasSpec("Месяц", ("month", "месяц"), required=False, dtype="str"),
        ColumnAliasSpec("ФОТ", ("payroll", "фот"), required=False),
        ColumnAliasSpec("Коммунальные", ("utilities", "ком.услуги", "коммунальные"), required=False),
        ColumnAliasSpec("Маркетинг", ("marketing", "маркетинг"), required=False),
        ColumnAliasSpec("Логистика", ("logistics", "логистика"), required=False),
        ColumnAliasSpec("Прочие OPEX", ("other_opex", "прочие расходы", "Прочие_OPEX"), required=False),
    ),
    "прибыль_месяц": (
        ColumnAliasSpec("Магазин", _STORE, required=True, dtype="str"),
        ColumnAliasSpec("Месяц", ("month", "месяц"), required=False, dtype="str"),
        ColumnAliasSpec(
            "Валовая прибыль общая",
            ("gross_profit_total", "Валовая_прибыль_общая", "валовая прибыль общая"),
            required=True,
        ),
        ColumnAliasSpec(
            "Валовая прибыль ТЗ",
            ("gross_profit_tz", "Валовая_прибыль_ТЗ", "валовая прибыль тз"),
            required=False,
        ),
        ColumnAliasSpec(
            "Валовая прибыль СП",
            ("gross_profit_sp", "Валовая_прибыль_СП", "валовая прибыль сп"),
            required=False,
        ),
    ),
    "потери_месяц": (
        ColumnAliasSpec("Магазин", _STORE, required=True, dtype="str"),
        ColumnAliasSpec("Дата", ("date", "день", "дата"), required=False, dtype="date"),
        ColumnAliasSpec("Месяц", ("month", "месяц"), required=False, dtype="str"),
        ColumnAliasSpec("Вид потерь", ("loss_type", "вид_потери", "Вид_потерь", "тип потерь"), required=True, dtype="str"),
        ColumnAliasSpec("Сумма", ("amount", "сумма_потерь", "сумма", "потери"), required=True),
    ),
    "цели": (
        ColumnAliasSpec("Метрика", ("metric_name", "metric", "показатель", "метрика"), required=True, dtype="str"),
        ColumnAliasSpec("Зеленая зона от", ("green_from", "зеленая зона от"), required=False),
        ColumnAliasSpec("Желтая зона от", ("yellow_from", "желтая зона от"), required=False),
        ColumnAliasSpec("Красная зона ниже", ("red_below", "красная зона ниже"), required=False),
        ColumnAliasSpec("Целевое значение", ("target_value", "цель", "целевое значение"), required=False),
    ),
}


def aliases_for(sheet_ru: str, canonical_col: str) -> tuple[str, ...]:
    for spec in COLUMN_ALIASES_BY_SHEET.get(sheet_ru, ()):
        if normalize(spec.canonical) == normalize(canonical_col):
            return spec.aliases
    return ()


def resolve_column_name(sheet_ru: str, source_col: str) -> Optional[str]:
    """Return canonical column for ``source_col`` on catalog sheet, or None."""
    norm = normalize(source_col)
    for spec in COLUMN_ALIASES_BY_SHEET.get(sheet_ru, ()):
        cands = {normalize(spec.canonical), *(normalize(a) for a in spec.aliases)}
        if norm in cands:
            return spec.canonical
    return None
