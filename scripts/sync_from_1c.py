#!/usr/bin/env python3
"""Синхронизация raw-слоя МегаМетрики из 1С (MSSQL) в локальный SQLite-кэш.

Запуск (read-only к 1С):
  /home/andr/apps/zya-war-room-v2/.venv/bin/python scripts/sync_from_1c.py

При сбое 1С предыдущий кэш не трогается.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MSK = ZoneInfo("Europe/Moscow")

LOG_DIR = Path(os.environ.get("WARROOM_SYNC_LOG_DIR", str(ROOT / "var" / "log")))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "sync_from_1c.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("warroom.sync")


def _now_msk() -> datetime:
    return datetime.now(timezone.utc).astimezone(MSK)


def _count_rows(raw: dict) -> dict[str, int]:
    import pandas as pd

    out = {}
    for k, v in raw.items():
        if isinstance(v, pd.DataFrame):
            out[k] = int(len(v))
    return out


def _morning_sync_ok_today(log_file: Path) -> bool:
    """True, если сегодня до 12:00 МСК уже был успешный sync OK."""
    if not log_file.is_file():
        return False
    today_msk = _now_msk().strftime("%Y-%m-%d")
    try:
        text = log_file.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    for line in text.splitlines():
        if "sync OK" not in line:
            continue
        # asctime: 2026-08-12 08:00:01,123 ... (время сервера = UTC)
        try:
            stamp = line.split(",", 1)[0].strip()
            ts_utc = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            ts_msk = ts_utc.astimezone(MSK)
            if ts_msk.strftime("%Y-%m-%d") == today_msk and ts_msk.hour < 12:
                return True
        except ValueError:
            continue
    return False


def main() -> int:
    started = _now_msk()
    hour_msk = started.hour
    log.info(
        "=== sync start %s (MSK) / %s (UTC) ===",
        started.isoformat(timespec="seconds"),
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    from app.services.local_cache_store import LocalCacheStore
    from app.services.sql_data_service import SqlDataService

    store = LocalCacheStore()
    prev = store.last_success_at()

    if hour_msk >= 12:
        if _morning_sync_ok_today(LOG_FILE):
            log.info(
                "резервный запуск ≥12:00 МСК: утренний sync OK — выполняем плановое повторное обновление"
            )
        else:
            log.warning(
                "резервный запуск ≥12:00 МСК: утренний sync не зафиксирован как успешный — "
                "выполняем полную синхронизацию заново"
            )

    try:
        os.environ["WARROOM_DATA_SOURCE"] = "sql"
        svc = SqlDataService(use_env_db=True)
        result = svc.load()
    except Exception as exc:  # noqa: BLE001
        log.error(
            "синхронизация не выполнена (%s), использованы данные от %s",
            exc,
            prev or "—",
        )
        return 2

    if not result.status.ok or not result.mapping_complete:
        log.error(
            "синхронизация не выполнена: status.ok=%s mapping_complete=%s error=%s; "
            "использованы данные от %s",
            result.status.ok,
            result.mapping_complete,
            result.status.error or result.status.message,
            prev or "—",
        )
        return 3

    raw = result.raw
    raw["_data_source"] = "local_cache"
    counts = _count_rows(raw)
    try:
        path = store.save_raw_atomic(raw, synced_at=started.isoformat(timespec="seconds"))
    except Exception as exc:  # noqa: BLE001
        log.error("запись кэша не удалась: %s; прежний кэш нетронут (%s)", exc, prev or "—")
        return 4

    ended = datetime.now(timezone.utc).astimezone()
    log.info("sync OK → %s", path)
    log.info("rows: %s", counts)
    log.info(
        "=== sync end %s duration=%.1fs prev=%s ===",
        ended.isoformat(timespec="seconds"),
        (ended - started).total_seconds(),
        prev or "—",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
