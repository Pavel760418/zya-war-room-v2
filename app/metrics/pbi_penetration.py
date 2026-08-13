"""PBI-parity penetration measures (ТКПТ_пенетрация).

Mirrors DAX from ``KPI и LFL`` in ``ТКПТ_пенетрация.pbix`` / ``ТКПТ_обзор.pbix``:

- ``Трафик`` = COUNTROWS(SUMMARIZE('ДЧ Продажи', id1, id3, id4, Период))
- ``Пенетрация`` = DIVIDE([Трафик], CALCULATE([Трафик], REMOVEFILTERS('СТ Номенклатура')), 0)

War Room needs *explicit* category measures (PBI applies category via visual filter):

- SP: ``'СТ Номенклатура'[1 уровень] = "Производство Зеленого яблока"``
- Pascucci: ``'СТ Марки'[Марка] = "Паскуччи"`` via nomen ``_Fld808RRef`` → ``_Reference93``

Not wired into UI/sync until explicit implement command.
"""
from __future__ import annotations

from typing import Optional

SP_LEVEL1_NAME = "Производство Зеленого яблока"
PASCUCCI_BRAND_NAME = "Паскуччи"


def dax_divide(numerator: float, denominator: float, if_zero: float = 0.0) -> float:
    """DAX DIVIDE(n, d, alternate) — default alternate 0 for [Пенетрация]."""
    if denominator is None or denominator == 0 or denominator != denominator:
        return if_zero
    return float(numerator) / float(denominator)


def measure_traffic(checks_all: float) -> float:
    """Implements DAX [Трафик] on an already-aggregated distinct-check count."""
    return float(checks_all or 0)


def measure_penetration(
    checks_with_filter: float,
    checks_all: float,
    *,
    if_zero: float = 0.0,
) -> float:
    """Implements DAX [Пенетрация] given pre-filtered vs unfiltered traffic.

    Source: KPI и LFL[Пенетрация] in ТКПТ_пенетрация.pbix
    """
    return dax_divide(float(checks_with_filter or 0), float(checks_all or 0), if_zero)


def measure_penetration_sp(checks_with_sp: float, checks_all: float) -> float:
    """CALCULATE([Пенетрация], 'СТ Номенклатура'[1 уровень] = SP_LEVEL1_NAME)."""
    return measure_penetration(checks_with_sp, checks_all)


def measure_penetration_pascucci(checks_with_brand: float, checks_all: float) -> float:
    """CALCULATE([Пенетрация], 'СТ Марки'[Марка] = PASCUCCI_BRAND_NAME)."""
    return measure_penetration(checks_with_brand, checks_all)


def penetration_pct_points(share_0_1: float) -> Optional[float]:
    """UI helper: PBI matrix often shows share; War Room KPIs historically use % points."""
    if share_0_1 is None:
        return None
    return round(float(share_0_1) * 100.0, 4)
