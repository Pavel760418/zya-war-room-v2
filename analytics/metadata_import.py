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
    Path("/home/andr/zya-war-room-v2/zya-war-room-v2/data/СтруктураХраненияБазыДанных.xlsx"),
)
REQUIRED_COLS = ("Метаданные", "Имя таблицы хранения", "Имя таблицы", "Назначение")
_LAST_RESOLVE_NOTES: str = ""


def _norm(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    text_v = str(val).replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(text_v.split()).strip()


def _looks_like_probe(path: Path) -> bool:
    """Heuristic: SQL INFORMATION_SCHEMA probe files are small and contain 'probe' in purpose."""
    try:
        if path.stat().st_size < 50000:
            sample = pd.read_excel(path, engine="openpyxl", nrows=5)
            sample.columns = [_norm(c) for c in sample.columns]
            if "Назначение" in sample.columns:
                joined = " ".join(_norm(v) for v in sample["Назначение"].tolist()).lower()
                if "probe" in joined or "information_schema" in joined:
                    return True
    except Exception:  # noqa: BLE001
        return False
    return False


def discover_structure_xlsx_candidates() -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    roots_patterns = [
        (Path("/opt/war_rom/data/1c"), "СтруктураХраненияБазыДанных*"),
        (Path("/home/andr"), "**/СтруктураХраненияБазыДанных*"),
    ]
    for root, pat in roots_patterns:
        if not root.exists():
            continue
        for p in root.glob(pat):
            if not p.is_file():
                continue
            key = str(p.resolve())
            if key in seen:
                continue
            seen.add(key)
            found.append(p.resolve())
    for p in DEFAULT_PATHS:
        if p.is_file():
            key = str(p.resolve())
            if key not in seen:
                seen.add(key)
                found.append(p.resolve())
    return found


def resolve_structure_xlsx(path: Optional[str] = None) -> Path:
    """Resolve structure map XLSX without moving/renaming sources.

    Selection: non-probe over probe, then newest mtime, then largest size.
    Criterion stored in _LAST_RESOLVE_NOTES for import journal.
    """
    global _LAST_RESOLVE_NOTES
    if path:
        p = Path(path)
        _LAST_RESOLVE_NOTES = f"explicit path: {p}"
        return p
    env = (os.getenv("WARROM_1C_STRUCTURE_XLSX") or "").strip()
    if env:
        p = Path(env)
        _LAST_RESOLVE_NOTES = f"env WARROM_1C_STRUCTURE_XLSX: {p}"
        return p

    cands = discover_structure_xlsx_candidates()
    if not cands:
        _LAST_RESOLVE_NOTES = "no candidates; fallback DEFAULT_PATHS[0]"
        return DEFAULT_PATHS[0]

    scored: list[tuple[tuple, Path]] = []
    for p in cands:
        try:
            probe = _looks_like_probe(p)
            scored.append(((0 if probe else 1, p.stat().st_mtime, p.stat().st_size), p))
        except OSError:
            continue
    if not scored:
        _LAST_RESOLVE_NOTES = "candidates unreadable; fallback DEFAULT_PATHS[0]"
        return DEFAULT_PATHS[0]
    scored.sort(key=lambda x: x[0], reverse=True)
    chosen = scored[0][1]
    _LAST_RESOLVE_NOTES = (
        f"chosen={chosen}; criterion=non_probe>mtime>size; "
        f"candidates={[str(p) for _, p in scored]}"
    )
    return chosen


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
                    (:fn, :fh, :at, :actor, :total, :ins, :upd, :deact, :skip, 'ok', :notes)
                    """
                ),
                {
                    "fn": str(path),
                    "fh": file_hash,
                    "at": now,
                    "actor": actor,
                    "total": len(rows_out),
                    "ins": inserted,
                    "upd": updated,
                    "deact": deactivated,
                    "skip": skipped,
                    "notes": (_LAST_RESOLVE_NOTES or "")[:900] or None,
                },
            )
        return {
            "import_status": "ok",
            "source_file_name": str(path),
            "source_file_hash": file_hash,
            "total_rows": len(rows_out),
            "inserted_rows": inserted,
            "updated_rows": updated,
            "deactivated_rows": deactivated,
            "skipped_rows": skipped,
            "imported_at": now,
            "resolve_notes": _LAST_RESOLVE_NOTES,
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
        "discovered_candidates": [str(p) for p in discover_structure_xlsx_candidates()],
        "resolve_notes": _LAST_RESOLVE_NOTES,
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
