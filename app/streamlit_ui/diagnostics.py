"""Отрисовка блока диагностики загрузки Excel в Streamlit.

Показывает пользователю понятным языком: что за файл, какие листы найдены и
распознаны, какие колонки восстановлены по алиасам, что приведено к числу/дате,
какие строки отброшены и какие предупреждения критичны.
"""
from __future__ import annotations

import streamlit as st

from app.ingestion.error_handling import IngestionReport, Severity, SheetReport

__all__ = ["render_summary_banner", "render_full_diagnostics"]

_SEVERITY_ICON = {
    Severity.SUCCESS: "✅",
    Severity.INFO: "ℹ️",
    Severity.WARNING: "⚠️",
    Severity.ERROR: "⛔",
}


def render_summary_banner(report: IngestionReport) -> None:
    """Короткая плашка «прочитано успешно / частично / ошибка» под контролами."""
    status = report.status
    headline = report.headline
    name = report.filename or "эталонный файл"
    if report.fatal:
        st.error(f"⛔ {headline}: «{name}». Загрузите корректный .xlsx.")
        return
    if status == Severity.SUCCESS:
        st.success(f"✅ {headline}: «{name}».")
    else:
        st.warning(
            f"⚠️ {headline}: «{name}». Некоторые листы/колонки восстановлены автоматически, "
            "часть данных могла быть пропущена — приложение продолжило работу. "
            "Подробности в разделе «Диагностика загрузки»."
        )


def _sheet_status_row(sheet: SheetReport) -> str:
    icon = _SEVERITY_ICON.get(sheet.status, "•")
    src = sheet.matched_source or "—"
    method = {
        "exact": "точно",
        "alias": "по алиасу",
        "fuzzy": f"похоже ({sheet.match_score})",
        "missing": "не найден",
    }.get(sheet.match_method, sheet.match_method)
    return f"{icon} **{sheet.canonical}** ← `{src}` ({method}) · строк: {sheet.rows_out}"


def render_full_diagnostics(report: IngestionReport) -> None:
    """Полный раздел диагностики (для отдельной страницы/вкладки)."""
    st.markdown("<div class='diag-head'>Диагностика загрузки</div>", unsafe_allow_html=True)
    render_summary_banner(report)

    if report.sheets_found:
        st.caption("Листы в файле: " + ", ".join(f"`{s}`" for s in report.sheets_found))

    # Сообщения верхнего уровня.
    for msg in report.messages:
        icon = _SEVERITY_ICON.get(msg.severity, "•")
        st.write(f"{icon} {msg.text}")

    st.divider()

    for sheet in report.sheets:
        with st.expander(_sheet_status_row(sheet), expanded=(sheet.status == Severity.ERROR)):
            meta_line = []
            if sheet.header_row is not None:
                meta_line.append(f"строка заголовков: {sheet.header_row + 1}")
            if sheet.rows_in:
                meta_line.append(f"строк прочитано: {sheet.rows_in}")
            if sheet.dropped_rows:
                meta_line.append(f"отброшено строк: {sheet.dropped_rows}")
            if meta_line:
                st.caption(" · ".join(meta_line))

            if sheet.columns:
                table_rows = []
                for col in sheet.columns:
                    method = {
                        "exact": "точно",
                        "alias": "алиас",
                        "fuzzy": f"похоже ({col.score})",
                        "missing": "не найдена",
                        "default": "по умолчанию",
                    }.get(col.method, col.method)
                    table_rows.append(
                        {
                            "Каноническая колонка": col.canonical,
                            "Источник": col.matched_source or "—",
                            "Сопоставление": method,
                            "Приведено значений": col.coerced,
                            "Заполнено по умолч.": col.filled_default,
                        }
                    )
                st.dataframe(table_rows, width="stretch", hide_index=True)

            for msg in sheet.messages:
                icon = _SEVERITY_ICON.get(msg.severity, "•")
                st.write(f"{icon} {msg.text}")
