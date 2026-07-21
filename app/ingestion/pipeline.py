"""Оркестратор ingestion: файл -> (raw dict для MetricsService, IngestionReport).

``raw`` намеренно повторяет контракт, который ожидает существующий
``MetricsService`` в excel-режиме (те же ключи листов и канонические колонки),
поэтому бизнес-логику расчётов переписывать не нужно.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from app.ingestion.data_mapping import match_sheet, resolve_columns
from app.ingestion.data_validation import build_canonical_frame
from app.ingestion.error_handling import (
    ColumnResolution,
    IngestionReport,
    Severity,
    SheetReport,
    safe_call,
)
from app.ingestion.excel_loader import (
    clean_frame,
    detect_header_row,
    open_workbook,
    promote_header,
    read_raw_sheet,
)
from app.ingestion.schema import META_SHEET, SCHEMA, SheetSpec
from app.ingestion.text_utils import normalize

__all__ = ["ingest_excel", "IngestionResult"]


@dataclass
class IngestionResult:
    """Результат загрузки: данные для расчётов + отчёт диагностики."""

    raw: dict
    report: IngestionReport
    ok: bool = True

    @property
    def has_store_data(self) -> bool:
        """Есть ли хотя бы один магазин в основном листе продаж."""
        sales = self.raw.get("sales_month")
        return isinstance(sales, pd.DataFrame) and not sales.empty


def _empty_canonical_frame(spec: SheetSpec) -> pd.DataFrame:
    return pd.DataFrame({c.canonical: pd.Series(dtype=object) for c in spec.columns})


def _expected_norms(spec: SheetSpec) -> set[str]:
    norms: set[str] = set()
    for col in spec.columns:
        norms.add(normalize(col.canonical))
        norms.update(normalize(a) for a in col.aliases)
    norms.discard("")
    return norms


def _ingest_sheet(workbook, sheets: list[str], spec: SheetSpec) -> tuple[pd.DataFrame, SheetReport]:
    """Загрузить и нормализовать один лист по его спецификации."""
    report = SheetReport(canonical=spec.canonical)
    source, method, score = match_sheet(spec, sheets)
    report.matched_source = source
    report.match_method = method
    report.match_score = score

    if source is None:
        severity = Severity.ERROR if spec.critical else Severity.WARNING
        report.add(severity, f"Лист «{spec.canonical}» не найден в файле.")
        report.columns = [
            ColumnResolution(canonical=c.canonical, method="missing") for c in spec.columns
        ]
        return _empty_canonical_frame(spec), report

    if method == "fuzzy":
        report.add(Severity.INFO, f"Лист распознан по похожему имени: «{source}» (score {score}).")
    elif method == "alias":
        report.add(Severity.INFO, f"Лист распознан по алиасу: «{source}».")

    raw_sheet, err = safe_call(read_raw_sheet, workbook, source)
    if raw_sheet is None:
        report.add(Severity.ERROR, f"Не удалось прочитать лист «{source}»: {err}.")
        report.columns = [
            ColumnResolution(canonical=c.canonical, method="missing") for c in spec.columns
        ]
        return _empty_canonical_frame(spec), report

    header_row = detect_header_row(raw_sheet, _expected_norms(spec))
    report.header_row = header_row
    if header_row > 0:
        report.add(Severity.INFO, f"Строка заголовков найдена со сдвигом (строка {header_row + 1}).")

    promoted, err = safe_call(promote_header, raw_sheet, header_row, default=pd.DataFrame())
    cleaned, err2 = safe_call(clean_frame, promoted, default=promoted)
    if cleaned is None:
        cleaned = pd.DataFrame()

    mapping, resolutions = resolve_columns(cleaned, spec)
    report.columns = resolutions

    canonical_df, err3 = safe_call(
        build_canonical_frame, cleaned, spec, mapping, resolutions, report,
        default=_empty_canonical_frame(spec),
    )
    if err3 is not None:
        report.add(Severity.ERROR, f"Ошибка нормализации листа «{source}»: {err3}.")
        canonical_df = _empty_canonical_frame(spec)

    # Диагностика по колонкам.
    recovered = report.recovered_columns
    if recovered:
        names = ", ".join(f"«{c.canonical}» ← «{c.matched_source}»" for c in recovered)
        report.add(Severity.INFO, f"Колонки восстановлены по алиасам: {names}.")
    missing = [c for c in report.missing_columns]
    if missing:
        names = ", ".join(f"«{c.canonical}»" for c in missing)
        report.add(Severity.WARNING, f"Колонки не найдены (подставлены значения по умолчанию): {names}.")

    return canonical_df, report


def _ingest_meta(workbook, sheets: list[str], report: IngestionReport) -> dict:
    """Загрузить лист ``meta`` в виде словаря key->value."""
    meta_report = SheetReport(canonical="meta")

    # Матчинг листа meta по алиасам.
    norm_to_source = {normalize(s): s for s in sheets}
    source = None
    for alias in (META_SHEET.canonical, *META_SHEET.aliases):
        if normalize(alias) in norm_to_source:
            source = norm_to_source[normalize(alias)]
            break

    meta: dict[str, object] = {}
    if source is None:
        meta_report.add(Severity.WARNING, "Лист «meta» не найден — используются значения по умолчанию.")
        report.sheets.append(meta_report)
        return meta

    meta_report.matched_source = source
    meta_report.match_method = "alias"
    raw_sheet, err = safe_call(read_raw_sheet, workbook, source)
    if raw_sheet is None or raw_sheet.empty:
        meta_report.add(Severity.WARNING, "Лист «meta» пуст или нечитаем.")
        report.sheets.append(meta_report)
        return meta

    expected = {normalize(META_SHEET.key_col), normalize(META_SHEET.value_col)}
    expected.update(normalize(a) for a in (*META_SHEET.key_col_aliases, *META_SHEET.value_col_aliases))
    header_row = detect_header_row(raw_sheet, expected)
    promoted = promote_header(raw_sheet, header_row)
    cleaned = clean_frame(promoted)

    # Определяем колонки ключа и значения.
    norm_cols = {normalize(c): c for c in cleaned.columns}
    key_col = next((norm_cols[normalize(a)] for a in (META_SHEET.key_col, *META_SHEET.key_col_aliases) if normalize(a) in norm_cols), None)
    val_col = next((norm_cols[normalize(a)] for a in (META_SHEET.value_col, *META_SHEET.value_col_aliases) if normalize(a) in norm_cols), None)

    if key_col is None or val_col is None:
        # Fallback: первые две колонки.
        if len(cleaned.columns) >= 2:
            key_col, val_col = cleaned.columns[0], cleaned.columns[1]
            meta_report.add(Severity.INFO, "Колонки meta определены по позиции (ключ/значение).")
        else:
            meta_report.add(Severity.WARNING, "Не удалось определить структуру листа «meta».")
            report.sheets.append(meta_report)
            return meta

    for _, row in cleaned.iterrows():
        key = row.get(key_col)
        if key is None or (isinstance(key, float) and pd.isna(key)):
            continue
        meta[str(key).strip()] = row.get(val_col)

    meta_report.rows_out = len(meta)
    meta_report.add(Severity.SUCCESS, f"Прочитано параметров: {len(meta)}.")
    report.sheets.append(meta_report)
    return meta


def ingest_excel(source, filename: Optional[str] = None) -> IngestionResult:
    """Главная точка входа ingestion.

    Никогда не бросает исключение наружу: любые проблемы фиксируются в отчёте,
    а результат содержит максимально полный набор данных, который удалось собрать.
    """
    report = IngestionReport(filename=filename)

    workbook, err = safe_call(open_workbook, source)
    if workbook is None:
        report.fatal = True
        report.add(Severity.ERROR, f"Не удалось открыть Excel-файл: {err}.")
        empty_raw = {"meta": {}}
        for canonical, spec in SCHEMA.items():
            empty_raw[canonical] = _empty_canonical_frame(spec)
        return IngestionResult(raw=empty_raw, report=report, ok=False)

    sheets, err = safe_call(lambda wb: list(wb.sheet_names), workbook, default=[])
    sheets = sheets or []
    report.sheets_found = sheets
    report.add(Severity.INFO, f"Найдено листов: {len(sheets)}.")

    raw: dict = {}
    raw["meta"] = _ingest_meta(workbook, sheets, report)

    for canonical, spec in SCHEMA.items():
        df, sheet_report = _ingest_sheet(workbook, sheets, spec)
        raw[canonical] = df
        report.sheets.append(sheet_report)

    # Итоговые сообщения верхнего уровня.
    sales_report = report.sheet("sales_month")
    if sales_report is None or not sales_report.found or raw["sales_month"].empty:
        report.add(
            Severity.WARNING,
            "Основной лист продаж отсутствует или пуст — часть дашборда будет недоступна.",
        )
    else:
        report.add(
            Severity.SUCCESS,
            f"Основной лист продаж загружен: магазинов {raw['sales_month']['Магазин'].nunique()}.",
        )

    return IngestionResult(raw=raw, report=report, ok=not report.fatal)
