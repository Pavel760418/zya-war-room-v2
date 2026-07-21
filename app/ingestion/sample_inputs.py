"""sample_inputs: генерация тестовых и намеренно «битых» Excel-файлов.

Используется в unit-тестах и как fallback-данные, чтобы проверять устойчивость
ingestion к реальным способам «испортить» файл менеджером.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.config import DEFAULT_EXCEL_FILE

__all__ = [
    "default_excel_path",
    "build_clean_workbook",
    "build_broken_workbook",
    "build_unreadable_bytes",
]


def default_excel_path() -> Path:
    """Путь к эталонному исходному Excel, для которого проект и создан."""
    return DEFAULT_EXCEL_FILE


def _base_sheets() -> dict[str, pd.DataFrame]:
    return {
        "meta": pd.DataFrame(
            {"ключ": ["Название сети", "Текущий день", "Валюта"],
             "значение": ["Зеленое Яблоко", "2026-06-15", "RUB"]}
        ),
        "продажи_месяц": pd.DataFrame(
            {"Месяц": ["2026-06", "2026-06"], "Магазин": ["Каспийск", "Махачкала"],
             "Выручка факт": [124861755, 98000000], "Выручка план": [121000000, 101000000],
             "Количество чеков": [146500, 120300]}
        ),
        "доступность_неделя": pd.DataFrame(
            {"Неделя": ["2026-W24", "2026-W24"], "Магазин": ["Каспийск", "Махачкала"],
             "Топ ТЗ всего позиций": [120, 120], "Топ ТЗ доступно позиций": [114, 100],
             "Топ СП всего позиций": [45, 45], "Топ СП доступно позиций": [40, 33]}
        ),
        "сп_месяц": pd.DataFrame(
            {"Месяц": ["2026-06", "2026-06"], "Магазин": ["Каспийск", "Махачкала"],
             "Выручка СП": [40500000, 27000000], "Валовая прибыль СП": [16200000, 10500000]}
        ),
        "остатки_месяц": pd.DataFrame(
            {"Месяц": ["2026-06", "2026-06"], "Магазин": ["Каспийск", "Махачкала"],
             "Остатки на конец месяца факт": [58200000, 61000000],
             "Остатки на конец месяца план": [55000000, 55000000]}
        ),
        "потери_месяц": pd.DataFrame(
            {"Месяц": ["2026-06", "2026-06"], "Магазин": ["Каспийск", "Махачкала"],
             "Вид потерь": ["Списания", "Списания"], "Сумма": [740000, 1250000]}
        ),
    }


def _write(sheets: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
    return buffer.getvalue()


def build_clean_workbook() -> bytes:
    """Корректный минимальный workbook с двумя магазинами."""
    return _write(_base_sheets())


def build_broken_workbook() -> bytes:
    """Workbook со множеством типовых поломок, которые ingestion должен пережить.

    Поломки:
    - лист продаж переименован (алиас) и с двумя пустыми строками над шапкой;
    - переставлен порядок колонок и переименованы колонки (алиасы);
    - текст вместо числа, отрицательные/пустые ячейки, NaN;
    - лишняя мусорная колонка;
    - лист доступности удалён целиком;
    - в остатках колонка переименована близким именем (fuzzy).
    """
    sheets = _base_sheets()

    # Лист продаж: алиас имени + сдвиг заголовка на 2 строки + мусорная колонка + грязь.
    sales = pd.DataFrame(
        {
            "Мусор": [np.nan, np.nan, "заголовки ниже", "магазин", "Каспийск", "Махачкала", np.nan],
            "b": [np.nan, np.nan, np.nan, "выручка", "1 250 000", "плохое_число", np.nan],
            "c": [np.nan, np.nan, np.nan, "план выручки", 1200000, 1000000, np.nan],
            "d": [np.nan, np.nan, np.nan, "чеки", 5000, np.nan, np.nan],
        }
    )
    del sheets["продажи_месяц"]
    del sheets["доступность_неделя"]  # лист полностью отсутствует

    # Переименуем колонку остатков в близкое (fuzzy) имя.
    sheets["остатки_месяц"] = sheets["остатки_месяц"].rename(
        columns={"Остатки на конец месяца факт": "Остатки конец месяца, факт"}
    )

    out = _write(sheets)
    # Дозапишем «съехавший» лист продаж с алиасным именем без заголовка в первой строке.
    buffer = io.BytesIO(out)
    with pd.ExcelWriter(buffer, engine="openpyxl", mode="a") as writer:
        sales.to_excel(writer, sheet_name="Продажи Месяц", index=False, header=False)
    return buffer.getvalue()


def build_unreadable_bytes() -> bytes:
    """Не-Excel байты (например, случайный текст), которые нельзя открыть как xlsx."""
    return b"this is definitely not an excel file \x00\x01\x02"
