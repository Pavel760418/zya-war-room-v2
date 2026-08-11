"""Idempotent import of 1C storage structure map XLSX into service DB."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from analytics.db import apply_migrations, get_engine

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = (
    Path("/opt/war_rom/data/1c/СтруктураХраненияБазыДанных.xlsx"),
    ROOT / "var" / "data" / "1c" / "СтруктураХраненияБазыДанных.xlsx",
)

REQUIRED_COLS = ("Метаданные", "Имя таблицы хранения", "Имя таблицы", "Назначение")


def resolve_structure_xlsx(path: Optional[str] = None) -> Path:
    if path:
        return Path(path)
    env = (os.getenv("WARROM_1C_STRUCTURE_XLSX") or "").strip()
    if env:
        return Path(env)
    for p in DEFAULT_PATHS:
        if p.is_file():
            return p
    return DEFAULT_PATHS[0]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    text_v = str(val).replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(text_v.split()).strip()


def _row_hash(meta: str, storage: str, physical: str, purpose: str) -> str:
    payload = "|".join([meta, storage, physical, purpose])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def import_structure_map(
    xlsx_path: Optional[str] = None,
    actor: str = "system",
    engine: Engine | None = None,
) -> dict[str, Any]:
    eng = engine or get_engine()
    apply_migrations(eng)
    path = resolve_structure_xlsx(xlsx_path)
    now = datetime.now(timezone.utc).isoformat()

    if not path.is_file():
        with eng.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO analytics_1c_storage_map_imports
                    (source_file_name, source_file_hash, imported_at, actor, total_rows,
                     inserted_rows, updated_rows, deactivated_rows, skipped_rows, import_status, error_summary)
                    VALUES (:fn, :fh, :at, :actor, 0, 0, 0, 0, 0, 'failed', :err)
                    """
                ),
                {
                    "fn": str(path),
                    "fh": "",
                    "at": now,
                    "actor": actor,
                    "err": f"File not found: {path.name}",
                },
            )
        return {
            "import_status": "failed",
            "error_summary": f"File not found: {path}",
            "source_file_name": str(path),
            "total_rows": 0,
        }

    file_hash = _sha256_file(path)
    df = pd.read_excel(path, engine="openpyxl")
    # Normalize column names (strip)
    df.columns = [_norm(c) for c in df.columns]
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        err = f"Missing columns: {', '.join(missing)}"
        with eng.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO analytics_1c_storage_map_imports
                    (source_file_name, source_file_hash, imported_at, actor, total_rows,
                     inserted_rows, updated_rows, deactivated_rows, skipped_rows, import_status, error_summary)
                    VALUES (:fn, :fh, :at, :actor, 0, 0, 0, 0, 0, 'failed', :err)
                    """
                ),
                {"fn": path.name, "fh": file_hash, "at": now, "actor": actor, "err": err},
            )
        return {"import_status": "failed", "error_summary": err, "source_file_name": path.name}

    inserted = updated = skipped = 0
    seen_hashes: set[str] = set()
    rows_out: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        meta = _norm(r.get("Метаданные"))
        storage = _norm(r.get("Имя таблицы хранения"))
        physical = _norm(r.get("Имя таблицы"))
        purpose = _norm(r.get("Назначение"))
        if not any([meta, storage, physical, purpose]):
            skipped += 1
            continue
        rh = _row_hash(meta, storage, physical, purpose)
        if rh in seen_hashes:
            skipped += 1
            continue
        seen_hashes.add(rh)
        rows_out.append(
            {
                "metadata_name": meta,
                "storage_table_name": storage,
                "physical_table_name": physical,
                "purpose": purpose,
                "source_file_name": path.name,
                "source_file_hash": file_hash,
                "row_hash": rh,
                "imported_at": now,
                "is_active": 1,
                "notes": None,
            }
        )

    try:
        with eng.begin() as conn:
            existing = {
                row[0]: row[1]
                for row in conn.execute(
                    text("SELECT row_hash, id FROM analytics_1c_storage_map")
                ).all()
            }
            incoming = {r["row_hash"] for r in rows_out}
            for row in rows_out:
                if row["row_hash"] in existing:
                    conn.execute(
                        text(
                            """
                            UPDATE analytics_1c_storage_map
                            SET metadata_name=:metadata_name,
                                storage_table_name=:storage_table_name,
                                physical_table_name=:physical_table_name,
                                purpose=:purpose,
                                source_file_name=:source_file_name,
                                source_file_hash=:source_file_hash,
                                imported_at=:imported_at,
                                is_active=1
                            WHERE row_hash=:row_hash
                            """
                        ),
                        row,
                    )
                    updated += 1
                else:
                    conn.execute(
                        text(
                            """
                            INSERT INTO analytics_1c_storage_map
                            (metadata_name, storage_table_name, physical_table_name, purpose,
                             source_file_name, source_file_hash, row_hash, imported_at, is_active, notes)
                            VALUES
                            (:metadata_name, :storage_table_name, :physical_table_name, :purpose,
                             :source_file_name, :source_file_hash, :row_hash, :imported_at, :is_active, :notes)
                            """
                        ),
                        row,
                    )
                    inserted += 1

            # Deactivate rows from previous imports of same logical map that are absent
            deactivated = 0
            for rh, _id in existing.items():
                if rh not in incoming:
                    conn.execute(
                        text(
                            "UPDATE analytics_1c_storage_map SET is_active=0 WHERE row_hash=:rh AND is_active=1"
                        ),
                        {"rh": rh},
                    )
                    deactivated += 1

            conn.execute(
                text(
                    """
                    INSERT INTO analytics_1c_storage_map_imports
                    (source_file_name, source_file_hash, imported_at, actor, total_rows,
                     inserted_rows, updated_rows, deactivated_rows, skipped_rows, import_status, error_summary)
                    VALUES
                    (:fn, :fh, :at, :actor, :total, :ins, :upd, :deact, :skip, 'ok', NULL)
                    """
                ),
                {
                    "fn": path.name,
                    "fh": file_hash,
                    "at": now,
                    "actor": actor,
                    "total": len(rows_out),
                    "ins": inserted,
                    "upd": updated,
                    "deact": deactivated,
                    "skip": skipped,
                },
            )
        return {
            "import_status": "ok",
            "source_file_name": path.name,
            "source_file_hash": file_hash,
            "total_rows": len(rows_out),
            "inserted_rows": inserted,
            "updated_rows": updated,
            "deactivated_rows": deactivated,
            "skipped_rows": skipped,
            "imported_at": now,
        }
    except Exception as exc:  # noqa: BLE001
        with eng.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO analytics_1c_storage_map_imports
                    (source_file_name, source_file_hash, imported_at, actor, total_rows,
                     inserted_rows, updated_rows, deactivated_rows, skipped_rows, import_status, error_summary)
                    VALUES (:fn, :fh, :at, :actor, 0, 0, 0, 0, 0, 'failed', :err)
                    """
                ),
                {
                    "fn": path.name,
                    "fh": file_hash,
                    "at": now,
                    "actor": actor,
                    "err": f"{type(exc).__name__}: {str(exc)[:300]}",
                },
            )
        return {
            "import_status": "failed",
            "error_summary": f"{type(exc).__name__}",
            "source_file_name": path.name,
        }


def catalog_status(engine: Engine | None = None) -> dict[str, Any]:
    eng = engine or get_engine()
    apply_migrations(eng)
    with eng.connect() as conn:
        active = conn.execute(
            text("SELECT COUNT(*) FROM analytics_1c_storage_map WHERE is_active=1")
        ).scalar_one()
        total = conn.execute(text("SELECT COUNT(*) FROM analytics_1c_storage_map")).scalar_one()
        last = conn.execute(
            text(
                """
                SELECT source_file_name, source_file_hash, imported_at, actor, total_rows,
                       inserted_rows, updated_rows, deactivated_rows, skipped_rows, import_status, error_summary
                FROM analytics_1c_storage_map_imports
                ORDER BY id DESC LIMIT 1
                """
            )
        ).mappings().first()
    return {
        "active_rows": int(active or 0),
        "total_rows": int(total or 0),
        "last_import": dict(last) if last else None,
        "expected_xlsx_paths": [str(p) for p in DEFAULT_PATHS],
    }


def search_catalog(q: str = "", active_only: bool = True, limit: int = 200, engine: Engine | None = None):
    eng = engine or get_engine()
    apply_migrations(eng)
    limit = max(1, min(int(limit), 1000))
    where = ["1=1"]
    params: dict[str, Any] = {"lim": limit}
    if active_only:
        where.append("is_active=1")
    if q.strip():
        where.append(
            "(metadata_name LIKE :q OR storage_table_name LIKE :q OR physical_table_name LIKE :q OR purpose LIKE :q)"
        )
        params["q"] = f"%{q.strip()}%"
    sql = f"""
        SELECT id, metadata_name, storage_table_name, physical_table_name, purpose,
               source_file_name, imported_at, is_active, notes
        FROM analytics_1c_storage_map
        WHERE {' AND '.join(where)}
        ORDER BY metadata_name, physical_table_name
        LIMIT :lim
    """
    with eng.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]
