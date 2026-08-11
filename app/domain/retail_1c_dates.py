"""1C retail date decoding for War Room SQL layer."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Union

# Confirmed for dbo._Document156._Date_Time and accumulation _Period in this database.
YEAR_OFFSET = 2000


def to_1c_datetime(d: Union[date, datetime]) -> datetime:
    """Map calendar date to 1C-stored datetime (calendar year + YEAR_OFFSET)."""
    if isinstance(d, datetime):
        base = d.date()
    else:
        base = d
    return datetime(base.year + YEAR_OFFSET, base.month, base.day)


def sql_date_from_doc(alias: str = "d") -> str:
    """SQL expression: calendar sale date from document _Date_Time."""
    return f"CAST(DATEADD(year, -{YEAR_OFFSET}, {alias}._Date_Time) AS date)"


def sql_period_from_accum(alias: str = "t") -> str:
    """SQL expression: calendar date from accumulation register _Period."""
    return f"CAST(DATEADD(year, -{YEAR_OFFSET}, {alias}._Period) AS date)"


def inclusive_date_to_exclusive(end: date) -> date:
    """Upper bound for half-open [from, to+1) filters."""
    return end + timedelta(days=1)
