"""data_validation: приведение типов, безопасные значения по умолчанию и quality-report.

Здесь «грязные» колонки превращаются в предсказуемые: числа становятся числами,
текст-мусор и Infinity/NaN заменяются безопасными значениями, строки-ключи
(«Магазин») чистятся, пустые строки отбрасываются. Всё под защитой try/except.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from app.ingestion.error_handling import ColumnResolution, SheetReport, Severity
from app.ingestion.schema import ColumnSpec, SheetSpec

__all__ = ["build_canonical_frame", "coerce_numeric_series", "coerce_string_series"]


def _clean_numeric_token(value: object) -> object:
    """Подготовить одиночное значение к числовому приведению.

    Обрабатывает строки вида ``"1 234,56"``, ``"12%"``, ``"1\\u00a0000"``.
    """
    if value is None:
        return np.nan
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if text == "":
        return np.nan
    text = (
        text.replace("\u00a0", "")
        .replace(" ", "")
        .replace("%", "")
        .replace("\u2212", "-")  # unicode minus
    )
    # Десятичная запятая -> точка, только если нет точки как разделителя.
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    return text


def coerce_numeric_series(series: pd.Series, default: float, fill_default: bool) -> tuple[pd.Series, int, int]:
    """Привести серию к числу.

    Возвращает ``(series, coerced_count, filled_default_count)``.
    ``coerced_count`` — сколько значений не были нативными числами.
    ``filled_default_count`` — сколько NaN/inf заменено на ``default``.
    """
    was_native = series.map(lambda v: isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)))
    cleaned = series.map(_clean_numeric_token)
    numeric = pd.to_numeric(cleaned, errors="coerce")

    # inf/-inf трактуем как отсутствующие значения.
    numeric = numeric.replace([np.inf, -np.inf], np.nan)

    coerced_count = int((~was_native).sum())

    filled_default_count = 0
    if fill_default:
        missing_mask = numeric.isna()
        filled_default_count = int(missing_mask.sum())
        numeric = numeric.fillna(default)
    return numeric, coerced_count, filled_default_count


def coerce_string_series(series: pd.Series, default: str, fill_default: bool) -> tuple[pd.Series, int, int]:
    """Привести серию к строке, схлопывая пробелы/переносы."""
    def _to_str(v: object) -> Optional[str]:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        text = str(v).strip()
        text = " ".join(text.split())
        return text or None

    converted = series.map(_to_str)
    coerced_count = int(series.map(lambda v: not isinstance(v, str)).sum())
    filled_default_count = 0
    if fill_default:
        missing_mask = converted.isna()
        filled_default_count = int(missing_mask.sum())
        converted = converted.fillna(default)
    return converted, coerced_count, filled_default_count


def _coerce_date_series(series: pd.Series, default: str, fill_default: bool) -> tuple[pd.Series, int, int]:
    parsed = pd.to_datetime(series, errors="coerce")
    coerced = int(series.map(lambda v: not hasattr(v, "year")).sum())
    as_text = parsed.dt.strftime("%Y-%m-%d")
    filled = 0
    if fill_default:
        missing = as_text.isna()
        filled = int(missing.sum())
        as_text = as_text.fillna(default)
    return as_text, coerced, filled


def build_canonical_frame(
    df: pd.DataFrame,
    spec: SheetSpec,
    mapping: dict[str, Optional[str]],
    resolutions: list[ColumnResolution],
    report: SheetReport,
) -> pd.DataFrame:
    """Собрать датафрейм с каноническими колонками и приведёнными типами.

    - Каждая каноническая колонка гарантированно присутствует в результате.
    - Отсутствующие колонки создаются со значениями по умолчанию.
    - Строки с пустым ключом (``key_column``) отбрасываются как мусорные.
    """
    resolution_by_canon = {r.canonical: r for r in resolutions}
    n_rows = len(df)
    result = pd.DataFrame(index=range(n_rows))

    for col_spec in spec.columns:
        source = mapping.get(col_spec.canonical)
        resolution = resolution_by_canon.get(col_spec.canonical)
        if source is not None and source in df.columns:
            raw_series = df[source].reset_index(drop=True)
        else:
            # Колонка не найдена — создаём заполнитель нужной длины.
            raw_series = pd.Series([np.nan] * n_rows)

        coerced_series, coerced_count, filled = _coerce_by_dtype(raw_series, col_spec)
        result[col_spec.canonical] = coerced_series

        if resolution is not None:
            resolution.coerced = coerced_count
            resolution.filled_default = filled
            if source is None and col_spec.required:
                report.add(
                    Severity.WARNING,
                    f"Обязательная колонка «{col_spec.canonical}» не найдена — подставлены значения по умолчанию.",
                )
            elif source is None and col_spec.fill_default:
                resolution.method = "default"

    # Чистка строк по ключевой колонке (обычно «Магазин»).
    dropped = 0
    if spec.key_column and spec.key_column in result.columns:
        before = len(result)
        mask_valid = result[spec.key_column].astype(str).str.strip().replace("nan", "") != ""
        result = result[mask_valid].reset_index(drop=True)
        dropped = before - len(result)

    report.rows_in = n_rows
    report.rows_out = len(result)
    report.dropped_rows = dropped
    if dropped:
        report.add(Severity.INFO, f"Отброшено пустых/мусорных строк: {dropped}.")

    return result


def _coerce_by_dtype(series: pd.Series, col_spec: ColumnSpec) -> tuple[pd.Series, int, int]:
    if col_spec.dtype in ("float", "int"):
        out, coerced, filled = coerce_numeric_series(series, float(col_spec.default or 0), col_spec.fill_default)
        if col_spec.dtype == "int":
            out = out.round().astype("Int64") if not col_spec.fill_default else out.round().astype("int64")
        return out, coerced, filled
    if col_spec.dtype == "date":
        return _coerce_date_series(series, str(col_spec.default or ""), col_spec.fill_default)
    return coerce_string_series(series, str(col_spec.default or ""), col_spec.fill_default)
