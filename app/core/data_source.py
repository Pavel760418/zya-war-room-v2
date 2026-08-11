"""Data source mode resolution for War Room.

``DATA_SOURCE_MODE`` / ``WARROOM_DATA_SOURCE``:
  - ``excel`` (default) — production-safe path for Streamlit Cloud; no MSSQL needed
  - ``mssql`` / ``sql`` — optional live 1C SQL; silent fallback to excel on failure
  - ``demo`` — synthetic network

Never raise on missing secrets: callers must treat unresolved mssql as excel.
"""
from __future__ import annotations

import logging
import os
from typing import Literal

logger = logging.getLogger("warroom.data_source")

DataSourceMode = Literal["excel", "mssql", "demo"]

_ENV_KEYS = ("DATA_SOURCE_MODE", "WARROOM_DATA_SOURCE")


def configured_data_source_mode() -> DataSourceMode:
    """Read preferred mode from env / Streamlit secrets-compatible env.

    Default is **excel** so Cloud and local-without-DB always boot with data.
    """
    raw = ""
    for key in _ENV_KEYS:
        raw = (os.getenv(key) or "").strip().lower()
        if raw:
            break
    if raw in ("mssql", "sql"):
        return "mssql"
    if raw == "demo":
        return "demo"
    # excel | empty | anything else → excel
    return "excel"


def resolve_runtime_mode(
    ui_choice: str,
    *,
    mssql_reachable: bool,
) -> tuple[DataSourceMode, str | None]:
    """Map sidebar choice + connectivity → effective mode.

    Returns ``(mode, fallback_notice)``. Notice is set when mssql was requested
    but unavailable and excel is used instead.
    """
    choice = (ui_choice or "").strip().lower()
    if choice in ("demo",):
        return "demo", None
    if choice in ("mssql", "sql"):
        if mssql_reachable:
            return "mssql", None
        notice = "MSSQL источник недоступен, используется Excel"
        logger.warning(notice)
        return "excel", notice
    return "excel", None
