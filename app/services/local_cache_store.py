"""Локальный SQLite-кэш сырого raw-слоя МегаМетрики (снимок из 1С).

Атомарная публикация: пишем во временный файл → os.replace на боевой путь.
Пользовательский UI читает только этот файл; MSSQL 1С не трогает.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

DEFAULT_CACHE_DIR = Path(os.environ.get("WARROOM_CACHE_DIR", "/home/andr/apps/zya-war-room-v2/var/cache"))
CACHE_DB_NAME = "warroom_raw.sqlite"
META_TABLE = "_sync_meta"
KV_TABLE = "_raw_kv"


def cache_db_path(cache_dir: Optional[Path] = None) -> Path:
    d = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d / CACHE_DB_NAME


def _utcnow() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class LocalCacheStore:
    """Чтение/запись raw-слоя SqlDataService в SQLite."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else cache_db_path()

    def exists(self) -> bool:
        return self.path.is_file() and self.path.stat().st_size > 0

    def last_success_at(self) -> Optional[str]:
        if not self.exists():
            return None
        try:
            with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as conn:
                row = conn.execute(
                    f"SELECT value FROM {META_TABLE} WHERE key='last_success_at'"
                ).fetchone()
                return row[0] if row else None
        except Exception:  # noqa: BLE001
            return None

    def load_raw(self) -> Optional[dict[str, Any]]:
        if not self.exists():
            return None
        try:
            with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as conn:
                tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                raw: dict[str, Any] = {}
                if KV_TABLE in tables:
                    for key, payload, kind in conn.execute(
                        f"SELECT key, payload, kind FROM {KV_TABLE}"
                    ):
                        if kind == "json":
                            raw[key] = json.loads(payload)
                        else:
                            raw[key] = payload
                for name in tables:
                    if name.startswith("_"):
                        continue
                    raw[name] = pd.read_sql_query(f'SELECT * FROM "{name}"', conn)
                # meta flags
                if META_TABLE in tables:
                    for key, value in conn.execute(f"SELECT key, value FROM {META_TABLE}"):
                        if key.startswith("flag_"):
                            flag = key[len("flag_") :]
                            if value in {"1", "true", "True"}:
                                raw[flag] = True
                            elif value in {"0", "false", "False"}:
                                raw[flag] = False
                            else:
                                raw[flag] = value
                        elif key == "last_success_at":
                            raw["_cache_synced_at"] = value
                            raw["_data_source"] = "local_cache"
                return raw
        except Exception:  # noqa: BLE001
            return None

    def save_raw_atomic(self, raw: dict[str, Any], *, synced_at: Optional[str] = None) -> Path:
        """Атомарно записать raw: tmp → replace."""
        synced_at = synced_at or _utcnow()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp.sqlite")
        if tmp.exists():
            tmp.unlink()
        conn = sqlite3.connect(tmp)
        try:
            conn.execute(
                f"CREATE TABLE {META_TABLE} (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute(
                f"CREATE TABLE {KV_TABLE} (key TEXT PRIMARY KEY, payload TEXT NOT NULL, kind TEXT NOT NULL)"
            )
            meta_rows = [
                ("last_success_at", synced_at),
                ("schema_version", "1"),
            ]
            for key, val in raw.items():
                if isinstance(val, pd.DataFrame):
                    # sanitize column names for sqlite
                    df = val.copy()
                    df.columns = [str(c) for c in df.columns]
                    df.to_sql(key, conn, index=False, if_exists="replace")
                elif key.startswith("_") and isinstance(val, (bool, int, float, str)):
                    meta_rows.append((f"flag_{key}", json.dumps(val) if not isinstance(val, str) else str(val)))
                elif key.startswith("_"):
                    conn.execute(
                        f"INSERT INTO {KV_TABLE}(key, payload, kind) VALUES (?,?,?)",
                        (key, json.dumps(val, default=str), "json"),
                    )
                elif isinstance(val, dict):
                    conn.execute(
                        f"INSERT INTO {KV_TABLE}(key, payload, kind) VALUES (?,?,?)",
                        (key, json.dumps(val, default=str), "json"),
                    )
            # store list notes etc.
            for key, val in raw.items():
                if key in {"confidence_notes"} or (
                    key.startswith("_") and isinstance(val, list)
                ):
                    conn.execute(
                        f"INSERT OR REPLACE INTO {KV_TABLE}(key, payload, kind) VALUES (?,?,?)",
                        (key, json.dumps(val, default=str), "json"),
                    )
            conn.executemany(
                f"INSERT OR REPLACE INTO {META_TABLE}(key, value) VALUES (?,?)",
                meta_rows,
            )
            conn.commit()
        finally:
            conn.close()
        os.replace(tmp, self.path)
        # touch sidecar for humans
        stamp = self.path.with_suffix(".last_success.txt")
        stamp.write_text(synced_at + "\n", encoding="utf-8")
        return self.path
