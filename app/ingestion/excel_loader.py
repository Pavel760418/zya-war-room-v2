"""data_loading: устойчивое открытие Excel-workbook и подготовка «сырых» листов.

Отвечает за:
- безопасное открытие файла из пути или из байтов (Streamlit upload);
- получение списка листов;
- чтение конкретного листа без предположений о заголовках (``header=None``);
- поиск реальной строки заголовков, если она сдвинута;
- удаление полностью пустых строк и столбцов;
- нормализацию имён колонок (обрезка пробелов/переносов, удаление ``Unnamed``).

Все функции спроектированы так, чтобы не бросать исключения наружу без нужды —
проблемы либо чинятся, либо сигнализируются через возвращаемые значения.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from app.ingestion.text_utils import normalize

__all__ = [
    "open_workbook",
    "read_raw_sheet",
    "detect_header_row",
    "clean_frame",
    "promote_header",
]

ExcelSource = Union[str, Path, bytes, bytearray, io.BytesIO]

# Максимум строк, среди которых ищем строку заголовков (защита от «съезда» шапки).
_MAX_HEADER_SCAN = 15


def _to_buffer(source: ExcelSource) -> io.BytesIO:
    """Привести любой поддерживаемый источник к seekable BytesIO."""
    if isinstance(source, (bytes, bytearray)):
        return io.BytesIO(bytes(source))
    if isinstance(source, io.BytesIO):
        source.seek(0)
        return source
    if hasattr(source, "read"):  # file-like (например, Streamlit UploadedFile)
        data = source.read()
        return io.BytesIO(data)
    # str / Path
    return io.BytesIO(Path(source).read_bytes())


def open_workbook(source: ExcelSource) -> pd.ExcelFile:
    """Открыть workbook через движок ``openpyxl`` (для ``.xlsx``).

    Бросает исключение только если файл фатально нечитаем — вызывающий код
    оборачивает это в try/except и помечает загрузку как fatal.
    """
    buffer = _to_buffer(source)
    return pd.ExcelFile(buffer, engine="openpyxl")


def read_raw_sheet(workbook: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
    """Прочитать лист «как есть», без интерпретации заголовков."""
    return workbook.parse(sheet_name=sheet_name, header=None, dtype=object)


def _row_score(row: pd.Series, expected_norms: set[str]) -> tuple[int, int]:
    """Оценить строку как кандидата в заголовки.

    Возвращает ``(совпадения_с_ожидаемыми, количество_непустых_текстовых_ячеек)``.
    """
    matches = 0
    non_empty_text = 0
    for cell in row.tolist():
        if cell is None or (isinstance(cell, float) and pd.isna(cell)):
            continue
        norm = normalize(cell)
        if not norm:
            continue
        # Заголовки почти всегда текст, а не чистое число.
        if isinstance(cell, str) or not _looks_numeric(cell):
            non_empty_text += 1
        if norm in expected_norms:
            matches += 1
    return matches, non_empty_text


def _looks_numeric(value: object) -> bool:
    if isinstance(value, (int, float)):
        return True
    try:
        float(str(value).replace(",", ".").replace(" ", ""))
        return True
    except (TypeError, ValueError):
        return False


def detect_header_row(raw: pd.DataFrame, expected_norms: set[str]) -> int:
    """Найти индекс строки с заголовками.

    Сначала ищем строку с максимальным числом совпадений с ожидаемыми
    (нормализованными) именами колонок. Если совпадений нет вовсе — берём
    первую строку, где больше всего непустых текстовых ячеек. Fallback — 0.
    """
    if raw.empty:
        return 0

    best_idx = 0
    best_matches = -1
    best_text = -1
    scan_limit = min(_MAX_HEADER_SCAN, len(raw))
    for idx in range(scan_limit):
        matches, non_empty_text = _row_score(raw.iloc[idx], expected_norms)
        if matches > best_matches or (matches == best_matches and non_empty_text > best_text):
            best_idx, best_matches, best_text = idx, matches, non_empty_text

    # Если ни одного совпадения с ожидаемыми колонками — заголовок ненадёжен,
    # но всё равно берём лучшую текстовую строку (best_idx уже её содержит).
    return best_idx


def _dedupe(names: list[str]) -> list[str]:
    """Сделать имена колонок уникальными, добавляя суффиксы ``.1``, ``.2`` ..."""
    seen: dict[str, int] = {}
    result: list[str] = []
    for name in names:
        if name in seen:
            seen[name] += 1
            result.append(f"{name}.{seen[name]}")
        else:
            seen[name] = 0
            result.append(name)
    return result


def promote_header(raw: pd.DataFrame, header_row: int) -> pd.DataFrame:
    """Превратить строку ``header_row`` в заголовки, а строки ниже — в данные."""
    if raw.empty:
        return pd.DataFrame()

    header_values = raw.iloc[header_row].tolist()
    columns: list[str] = []
    for pos, value in enumerate(header_values):
        if value is None or (isinstance(value, float) and pd.isna(value)):
            columns.append(f"col_{pos}")
        else:
            text = str(value).strip()
            columns.append(text if text else f"col_{pos}")
    columns = _dedupe(columns)

    body = raw.iloc[header_row + 1:].copy()
    body.columns = columns
    body.reset_index(drop=True, inplace=True)
    return body


def clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Убрать полностью пустые строки/столбцы и служебные ``Unnamed``/``col_`` колонки."""
    if df.empty:
        return df

    df = df.dropna(axis=0, how="all")
    df = df.dropna(axis=1, how="all")

    # Отбрасываем технические/безымянные колонки (например, лишний 'Столбец1' без данных).
    keep_cols = []
    for col in df.columns:
        col_norm = normalize(col)
        is_placeholder = (
            col_norm == ""
            or str(col).startswith("col_")
            or str(col).lower().startswith("unnamed")
            or col_norm.startswith("столбец")
        )
        if is_placeholder and df[col].dropna().empty:
            continue
        keep_cols.append(col)
    df = df[keep_cols]

    df.reset_index(drop=True, inplace=True)
    return df
