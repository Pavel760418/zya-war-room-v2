"""Data source mode: SQL is the only user-facing path.

``DATA_SOURCE_MODE`` / ``WARROOM_DATA_SOURCE``:
  - ``mssql`` / ``sql`` (default) — live 1C SQL
  - ``demo`` — synthetic network (sidebar optional / diagnostics)
  - ``excel`` — **test fixtures only**; never selected automatically for users
"""
from __future__ import annotations

import logging
import os
from typing import Literal

logger = logging.getLogger("warroom.data_source")

DataSourceMode = Literal["excel", "mssql", "demo"]

_ENV_KEYS = ("DATA_SOURCE_MODE", "WARROOM_DATA_SOURCE")


def configured_data_source_mode() -> DataSourceMode:
    raw = ""
    try:
        from app.core.settings import _secret_get

        raw = (_secret_get("DATA_SOURCE_MODE") or _secret_get("WARROOM_DATA_SOURCE") or "").strip().lower()
    except Exception:  # noqa: BLE001
        for key in _ENV_KEYS:
            raw = (os.getenv(key) or "").strip().lower()
            if raw:
                break
    if raw == "demo":
        return "demo"
    # excel / empty / mssql / sql → product default is always MSSQL
    return "mssql"


def resolve_runtime_mode(
    ui_choice: str,
    *,
    mssql_reachable: bool,
) -> tuple[DataSourceMode, str | None]:
    """Map UI choice → mode. Never silently falls back to Excel."""
    choice = (ui_choice or "").strip().lower()
    if choice in ("demo",):
        return "demo", None
    if not mssql_reachable:
        notice = "MSSQL недоступен — задайте Secrets (DATABASE_URL или DB_*)"
        logger.error(notice)
        return "mssql", notice
    return "mssql", None
