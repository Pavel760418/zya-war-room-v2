"""Программная генерация Excel-шаблона War Room для ручного заполнения.

Шаблон строится из той же схемы (``app.ingestion.schema``), что использует
ingestion, поэтому он гарантированно совместим с загрузкой: канонические имена
листов и колонок, примеры строк и лист-инструкция с пометкой обязательных полей.
"""
from __future__ import annotations

import io

import pandas as pd

from app.ingestion.schema import META_SHEET, SCHEMA, SheetSpec

__all__ = ["build_excel_template", "template_filename"]

TEMPLATE_FILENAME = "war_room_template.xlsx"


def template_filename() -> str:
    return TEMPLATE_FILENAME


# Реалистичные примеры значений по каноническим колонкам (для понятного шаблона).
_EXAMPLE_STORES = ["Каспийск", "Махачкала"]
_EXAMPLE_VALUES: dict[str, list] = {
    "Месяц": ["2026-06", "2026-06"],
    "Неделя": ["2026-W24", "2026-W24"],
    "Дата": ["2026-06-15", "2026-06-15"],
    "Выручка факт": [124861755, 98250000],
    "Выручка план": [121000000, 101000000],
    "Количество чеков": [146500, 120300],
    "Топ ТЗ всего позиций": [120, 120],
    "Топ ТЗ доступно позиций": [114, 101],
    "Топ СП всего позиций": [45, 45],
    "Топ СП доступно позиций": [40, 34],
    "Выручка СП": [40500000, 27200000],
    "Валовая прибыль СП": [16200000, 10500000],
    "Остатки на конец месяца факт": [58200000, 61000000],
    "Остатки на конец месяца план": [55000000, 55000000],
    "Вид потерь": ["Списания", "Списания"],
    "Сумма": [740000, 1250000],
    "Чеков всего": [146500, 120300],
    "Чеков с СП": [52000, 39000],
    "Чеков с Паскуччи": [9800, 7100],
    "Итого": [185000, 240000],
    "Метрика": ["Выполнение плана продаж", "Валовая прибыль %"],
}


def _example_column(canonical: str, dtype: str) -> list:
    if canonical == "Магазин":
        return list(_EXAMPLE_STORES)
    if canonical in _EXAMPLE_VALUES:
        return list(_EXAMPLE_VALUES[canonical])
    if dtype in ("float", "int"):
        return [1000, 2000]
    if dtype == "date":
        return ["2026-06", "2026-06"]
    return ["Пример 1", "Пример 2"]


def _sheet_frame(spec: SheetSpec) -> pd.DataFrame:
    data = {col.canonical: _example_column(col.canonical, col.dtype) for col in spec.columns}
    return pd.DataFrame(data)


def _sheet_display_name(spec: SheetSpec) -> str:
    """Человеко-понятное имя листа (русский алиас, если есть)."""
    name = spec.aliases[0] if spec.aliases else spec.canonical
    return str(name)[:31]


def _meta_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            META_SHEET.key_col: [
                "Название сети",
                "Название дашборда",
                "Текущий день",
                "Текущая неделя",
                "Текущий месяц",
                "Валюта",
            ],
            META_SHEET.value_col: [
                "Зеленое Яблоко",
                "Операционный дашборд сети Зеленое Яблоко",
                "2026-06-15",
                "2026-W24",
                "2026-06",
                "RUB",
            ],
        }
    )


def _instructions_frame() -> pd.DataFrame:
    rows: list[tuple[str, str]] = [
        ("Назначение", "Шаблон исходных данных для дашборда War Room. Заполняйте листы вручную."),
        ("Как заполнять", "Не переименовывайте заголовки колонок. Данные — со второй строки каждого листа."),
        ("Пустые значения", "Пустые числовые ячейки трактуются как 0. Пустые строки игнорируются."),
        ("Магазины", "Колонка «Магазин» обязательна на всех листах данных — по ней связываются показатели."),
        ("Единицы", "Денежные суммы — в рублях (абсолютные значения), доли/проценты — как в примерах."),
        ("", ""),
        ("Лист", "Обязательные колонки"),
    ]
    for spec in SCHEMA.values():
        required = [c.canonical for c in spec.columns if c.required]
        rows.append((_sheet_display_name(spec), ", ".join(required) if required else "— (необязательный лист)"))
    return pd.DataFrame(rows, columns=["Раздел", "Описание"])


def build_excel_template() -> bytes:
    """Собрать .xlsx-шаблон и вернуть его как байты (для ``st.download_button``).

    Порядок листов: инструкция → meta → все листы данных из схемы.
    """
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        _instructions_frame().to_excel(writer, sheet_name="инструкция", index=False)
        _meta_frame().to_excel(writer, sheet_name=META_SHEET.canonical, index=False)
        for spec in SCHEMA.values():
            _sheet_frame(spec).to_excel(writer, sheet_name=_sheet_display_name(spec), index=False)
    return buffer.getvalue()
