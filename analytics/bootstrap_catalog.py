"""Optional bootstrap of storage map from SQL INFORMATION_SCHEMA when official XLSX is absent.

Marked as non-authoritative probe — replace by official GetСтруктуруХраненияБазыДанных() export.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from analytics.db import apply_migrations, get_engine
from analytics.metadata_import import import_structure_map
from app.repositories.sql_database import SqlDatabase


def bootstrap_probe_xlsx(out_path: Path) -> Path:
    db = SqlDatabase.from_env(connect_timeout=60)
    if db is None:
        raise RuntimeError("DATABASE_URL not configured")
    tables = db.fetch_df(
        """
        SELECT TABLE_NAME AS physical_table_name
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = 'dbo'
          AND (
            TABLE_NAME LIKE '\\_Document%' ESCAPE '\\'
            OR TABLE_NAME LIKE '\\_Reference%' ESCAPE '\\'
            OR TABLE_NAME LIKE '\\_AccumRg%' ESCAPE '\\'
            OR TABLE_NAME LIKE '\\_InfoRg%' ESCAPE '\\'
          )
        ORDER BY TABLE_NAME
        """
    )
    rows = []
    for name in tables["physical_table_name"].astype(str):
        rows.append(
            {
                "Метаданные": name,
                "Имя таблицы хранения": name,
                "Имя таблицы": name,
                "Назначение": "SQL INFORMATION_SCHEMA probe (не официальная карта 1С)",
            }
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_excel(out_path, index=False, engine="openpyxl")
    return out_path


def ensure_catalog() -> dict:
    apply_migrations(get_engine())
    # Prefer official file import
    result = import_structure_map(actor="bootstrap")
    if result.get("import_status") == "ok":
        return {"mode": "official_xlsx", **result}
    # Fallback probe into var/data/1c
    probe = Path(__file__).resolve().parents[1] / "var" / "data" / "1c" / "СтруктураХраненияБазыДанных.xlsx"
    # Only create probe if no official file exists and probe missing or empty catalog
    from analytics.metadata_import import catalog_status

    st = catalog_status()
    if st["active_rows"] > 0:
        return {"mode": "existing_catalog", **st, "last_attempt": result}
    bootstrap_probe_xlsx(probe)
    result2 = import_structure_map(xlsx_path=str(probe), actor="sql_catalog_probe")
    return {"mode": "sql_catalog_probe", "warning": "Official 1C XLSX missing; probe used", **result2}
