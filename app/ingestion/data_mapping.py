"""data_mapping: сопоставление листов и колонок из файла с канонической схемой.

Best-effort mapping: сначала точное совпадение по нормализованному имени,
затем по словарю алиасов, затем нечёткое (fuzzy) сопоставление. Ничего не
роняем — если совпадения нет, сообщаем об этом через отчёт.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from app.ingestion.error_handling import ColumnResolution
from app.ingestion.schema import ColumnSpec, SheetSpec
from app.ingestion.sheet_mapping import resolve_sheet_name
from app.ingestion.text_utils import normalize, similarity

__all__ = ["match_sheet", "resolve_columns"]

_FUZZY_SHEET_THRESHOLD = 0.80
_FUZZY_COLUMN_THRESHOLD = 0.84


def _candidate_norms(canonical: str, aliases: tuple[str, ...]) -> set[str]:
    norms = {normalize(canonical)}
    norms.update(normalize(a) for a in aliases)
    norms.discard("")
    return norms


def match_sheet(spec: SheetSpec, available_sheets: list[str]) -> tuple[Optional[str], str, float]:
    """Найти в файле лист, соответствующий ``spec``.

    Возвращает ``(source_sheet_name, method, score)`` где method ∈
    ``{'exact', 'alias', 'fuzzy', 'missing'}``.
    """
    norm_to_source = {normalize(s): s for s in available_sheets}
    canonical_norm = normalize(spec.canonical)

    # 0. Каталог Словарь_алиасов → sheet_mapping (русские имена + синонимы).
    for src in available_sheets:
        resolved = resolve_sheet_name(src)
        if resolved and resolved[1] == spec.canonical:
            method = "exact" if normalize(src) == canonical_norm else "alias"
            return src, method, 1.0

    # 1. Точное совпадение с каноническим именем.
    if canonical_norm in norm_to_source:
        return norm_to_source[canonical_norm], "exact", 1.0

    # 2. Совпадение по алиасам.
    for alias in spec.aliases:
        alias_norm = normalize(alias)
        if alias_norm in norm_to_source:
            return norm_to_source[alias_norm], "alias", 1.0

    # 3. Fuzzy: сравниваем каждый лист файла со всеми алиасами/каноникой.
    targets = _candidate_norms(spec.canonical, spec.aliases)
    best_source, best_score = None, 0.0
    for src_norm, src_original in norm_to_source.items():
        score = max((similarity(src_norm, t) for t in targets), default=0.0)
        if score > best_score:
            best_source, best_score = src_original, score
    if best_source is not None and best_score >= _FUZZY_SHEET_THRESHOLD:
        return best_source, "fuzzy", round(best_score, 3)

    return None, "missing", 0.0


def _match_one_column(
    col_spec: ColumnSpec, available_norm_map: dict[str, str]
) -> tuple[Optional[str], str, float]:
    """Сопоставить одну каноническую колонку с колонкой файла."""
    canonical_norm = normalize(col_spec.canonical)
    if canonical_norm in available_norm_map:
        return available_norm_map[canonical_norm], "exact", 1.0

    for alias in col_spec.aliases:
        alias_norm = normalize(alias)
        if alias_norm in available_norm_map:
            return available_norm_map[alias_norm], "alias", 1.0

    targets = _candidate_norms(col_spec.canonical, col_spec.aliases)
    best_col, best_score = None, 0.0
    for col_norm, col_original in available_norm_map.items():
        score = max((similarity(col_norm, t) for t in targets), default=0.0)
        if score > best_score:
            best_col, best_score = col_original, score
    if best_col is not None and best_score >= _FUZZY_COLUMN_THRESHOLD:
        return best_col, "fuzzy", round(best_score, 3)

    return None, "missing", 0.0


def resolve_columns(
    df: pd.DataFrame, spec: SheetSpec
) -> tuple[dict[str, Optional[str]], list[ColumnResolution]]:
    """Сопоставить канонические колонки листа с фактическими колонками ``df``.

    Возвращает:
    - ``mapping``: canonical -> source column name (или ``None``, если не найдено);
    - ``resolutions``: список ``ColumnResolution`` для диагностики.

    Одна и та же колонка файла не переиспользуется для двух канонических полей.
    """
    available_norm_map: dict[str, str] = {}
    for col in df.columns:
        norm = normalize(col)
        # Первое вхождение нормализованного имени выигрывает.
        available_norm_map.setdefault(norm, col)

    used_sources: set[str] = set()
    mapping: dict[str, Optional[str]] = {}
    resolutions: list[ColumnResolution] = []

    for col_spec in spec.columns:
        # Исключаем уже занятые колонки, чтобы не мапить два поля на одну.
        free_map = {n: o for n, o in available_norm_map.items() if o not in used_sources}
        source, method, score = _match_one_column(col_spec, free_map)
        if source is not None:
            used_sources.add(source)
        mapping[col_spec.canonical] = source
        resolutions.append(
            ColumnResolution(
                canonical=col_spec.canonical,
                matched_source=source,
                method=method if source is not None else "missing",
                score=score,
            )
        )

    return mapping, resolutions
