#!/usr/bin/env python3
"""Interactive read-only MSSQL discovery for War Room.

- Asks SQL password via getpass (no echo; prefers /dev/tty).
- Runs SELECT-only catalog queries.
- Writes DATABASE_URL into ~/.config/warroom/warroom.env (chmod 600).
- Directory ~/.config/warroom is chmod 700.
- Prints a summary WITHOUT password / full URL.
- Writes discovery CSVs + metric candidate mapping (no invented facts).

Usage::

    cd /home/andr/apps/zya-war-room-v2
    source .venv/bin/activate
    python scripts/sql_discover.py
"""
from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENV_PATH = Path.home() / ".config" / "warroom" / "warroom.env"
HOST = "192.168.2.10"
PORT = 1433
USER = "andr"
OUT_DIR = Path.home() / ".config" / "warroom" / "discovery"

# Keyword heuristics for War Room metric candidates (Russian + English).
METRIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "date": ("дата", "date", "period", "период", "день", "месяц", "неделя", "datetime", "dt_", "_dt"),
    "store": ("магазин", "store", "тт", "точка", "shop", "филиал", "warehouse", "склад"),
    "revenue": ("выручка", "revenue", "оборот", "rto", "sales_amount", "суммапродаж", "сумма_продаж"),
    "revenue_plan": ("план", "plan", "budget", "бюджет"),
    "checks": ("чек", "check", "receipt", "qty_check", "количество_чек"),
    "avg_ticket": ("средний_чек", "avg_ticket", "average_check", "средничек"),
    "cogs": ("себестоим", "cogs", "cost", "закуп"),
    "gross_profit": ("вал", "gross", "маржа", "прибыль_вал", "gp_"),
    "gross_margin": ("маржа", "margin", "рентаб"),
    "opex": ("opex", "расход", "издерж", "затрат", "expense", "операционн"),
    "ebitda": ("ebitda", "операционн_приб", "operating_profit", "оп_приб", "прибыль"),
    "staff": ("персонал", "staff", "сотруд", "фот", "зарплат", "payroll", "headcount"),
    "stock": ("остат", "stock", "inventory", "запас"),
    "writeoff": ("списан", "потер", "writeoff", "loss", "недостач"),
}


def _ensure_secret_dirs() -> None:
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(ENV_PATH.parent, 0o700)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(OUT_DIR, 0o700)


def _write_env(database: str, password: str) -> None:
    _ensure_secret_dirs()
    user_q = quote(USER, safe="")
    pass_q = quote(password, safe="")
    url = f"mssql+pymssql://{user_q}:{pass_q}@{HOST}:{PORT}/{database}"
    content = (
        "# War Room secrets — owner-only. Do not commit.\n"
        f"DATABASE_URL={url}\n"
        "WARROOM_DATA_SOURCE=sql\n"
        "WARROOM_SQL_TIMEOUT=8\n"
    )
    ENV_PATH.write_text(content, encoding="utf-8")
    os.chmod(ENV_PATH, 0o600)


def _pick_database(dbs: list[str]) -> str:
    env_db = (os.environ.get("WARROOM_SQL_DATABASE") or "").strip()
    if env_db:
        print(f"Using WARROOM_SQL_DATABASE={env_db}")
        return env_db
    if len(dbs) == 1:
        print(f"Only one user database — auto-select: {dbs[0]}")
        return dbs[0]

    prefer_keys = (
        "zya",
        "war",
        "retail",
        "store",
        "магаз",
        "яблок",
        "1c",
        "erp",
        "bi",
        "dw",
        "dwh",
        "olap",
        "analytics",
        "ut",
        "unf",
        "trade",
    )
    prefer = [d for d in dbs if any(k in d.lower() for k in prefer_keys)]
    default = prefer[0] if prefer else dbs[0]

    try:
        choice = input(f"Enter database name or number [default: {default}]: ").strip()
    except EOFError:
        choice = ""
    if not choice:
        return default
    if choice.isdigit() and 1 <= int(choice) <= len(dbs):
        return dbs[int(choice) - 1]
    return choice


def _norm(s: str) -> str:
    return re.sub(r"[^a-zа-я0-9]+", "", (s or "").lower())


def _map_metrics(columns_csv: Path, objects_csv: Path) -> Path:
    import pandas as pd

    cols = pd.read_csv(columns_csv)
    objs = pd.read_csv(objects_csv)
    hits: dict[str, list[str]] = {k: [] for k in METRIC_KEYWORDS}

    for _, row in cols.iterrows():
        full = f"{row['schema_name']}.{row['object_name']}.{row['column_name']}"
        blob = _norm(f"{row['object_name']} {row['column_name']}")
        for metric, keys in METRIC_KEYWORDS.items():
            if any(_norm(k) in blob for k in keys):
                hits[metric].append(full)

    # Also score object names alone
    for _, row in objs.iterrows():
        blob = _norm(row["object_name"])
        full = f"{row['schema_name']}.{row['object_name']} ({row['object_type']})"
        for metric, keys in METRIC_KEYWORDS.items():
            if any(_norm(k) in blob for k in keys):
                if full not in hits[metric]:
                    hits[metric].append(full)

    report_path = OUT_DIR / "metric_candidates.md"
    lines = [
        "# War Room — SQL metric candidates (heuristic)",
        "",
        "Автоподбор по именам колонок/объектов. **Не подтверждён ИТ.**",
        "Не использовать как финальный маппинг без сверки с Excel и бизнес-правилами.",
        "",
    ]
    for metric, found in hits.items():
        lines.append(f"## {metric}")
        if not found:
            lines.append("- _не найдено по ключевым словам_")
        else:
            for item in found[:40]:
                lines.append(f"- `{item}`")
            if len(found) > 40:
                lines.append(f"- … ещё {len(found) - 40}")
        lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")

    # Compact stdout summary
    print("\n=== Metric candidates (heuristic) ===")
    for metric, found in hits.items():
        status = f"{len(found)} hit(s)" if found else "NOT FOUND"
        print(f"  {metric:15} {status}")
        for item in found[:5]:
            print(f"    - {item}")
        if len(found) > 5:
            print(f"    … +{len(found) - 5} more")
    print(f"Saved: {report_path}")
    return report_path


def main() -> int:
    _ensure_secret_dirs()
    print("=== War Room SQL discovery (SELECT only) ===")
    print(f"Server: {HOST}:{PORT}")
    print(f"User:   {USER}")
    print("Пароль будет запрошен скрыто (getpass). Не вставляйте его в чат.")

    try:
        password = getpass.getpass("SQL password for andr (input hidden): ")
    except Exception as exc:  # noqa: BLE001
        print(f"getpass failed: {type(exc).__name__}. Run this script in an interactive SSH/terminal.")
        return 1
    if not password:
        print("Empty password — abort.")
        return 1

    import pymssql

    try:
        conn = pymssql.connect(
            server=HOST,
            port=PORT,
            user=USER,
            password=password,
            database="master",
            login_timeout=8,
            timeout=30,
        )
    except Exception:  # noqa: BLE001
        print("LOGIN FAILED: auth/connection error (details redacted).")
        return 2

    cur = conn.cursor()
    cur.execute("SELECT @@VERSION")
    version = str(cur.fetchone()[0]).split("\n")[0][:160]
    print(f"Engine: {version}")

    cur.execute(
        """
        SELECT name FROM sys.databases
        WHERE state_desc='ONLINE'
          AND name NOT IN ('master','tempdb','model','msdb')
        ORDER BY name
        """
    )
    dbs = [r[0] for r in cur.fetchall()]
    print("Accessible user databases:")
    for i, name in enumerate(dbs, 1):
        print(f"  {i}. {name}")
    conn.close()

    if not dbs:
        print("No user databases visible — ask IT for DB name / permissions.")
        return 3

    database = _pick_database(dbs)
    print(f"Using database: {database}")

    _write_env(database, password)
    mode = oct(ENV_PATH.stat().st_mode & 0o777)
    dir_mode = oct(ENV_PATH.parent.stat().st_mode & 0o777)
    print(f"Wrote secrets file: {ENV_PATH}")
    print(f"Permissions: dir {dir_mode} file {mode}")

    from app.repositories.sql_database import SqlDatabase

    db = SqlDatabase.from_env()
    assert db is not None
    status = db.ping()
    print(f"Ping ok={status.ok} db={status.database}")
    if not status.ok:
        print(f"Ping error: {status.error}")
        return 4

    schemas = db.list_schemas()
    objects = db.list_tables_and_views()
    can_select, select_msg = db.probe_select_permission()
    print(f"SELECT probe: {select_msg} (ok={can_select})")
    print(f"Schemas: {len(schemas)}  Tables/Views: {len(objects)}")

    schemas_path = OUT_DIR / "schemas.csv"
    objects_path = OUT_DIR / "tables_views.csv"
    schemas.to_csv(schemas_path, index=False)
    objects.to_csv(objects_path, index=False)
    print(f"Saved: {schemas_path}")
    print(f"Saved: {objects_path}")

    # All columns (SELECT-only INFORMATION_SCHEMA)
    sample_cols = []
    for _, row in objects.iterrows():
        cols = db.list_columns(row["schema_name"], row["object_name"])
        cols = cols.assign(
            schema_name=row["schema_name"],
            object_name=row["object_name"],
            object_type=row["object_type"],
        )
        sample_cols.append(cols)
    cols_path = OUT_DIR / "columns.csv"
    if sample_cols:
        import pandas as pd

        all_cols = pd.concat(sample_cols, ignore_index=True)
        all_cols.to_csv(cols_path, index=False)
        print(f"Saved: {cols_path} ({len(all_cols)} columns)")
    else:
        print("No columns discovered.")
        cols_path.write_text(
            "schema_name,object_name,object_type,column_name,data_type,is_nullable,max_length,numeric_precision,ordinal_position\n",
            encoding="utf-8",
        )

    print("\nSchemas:")
    print(schemas.to_string(index=False))
    print("\nPreview objects (first 60):")
    print(objects.head(60).to_string(index=False))

    if cols_path.exists() and objects_path.exists():
        _map_metrics(cols_path, objects_path)

    # Sync docs stub with pointer to discovery output (no secrets)
    docs = ROOT / "docs" / "sql_metric_mapping.md"
    if docs.exists():
        note = (
            f"\n\n## Последний discovery\n\n"
            f"- База: `{database}`\n"
            f"- Артефакты: `~/.config/warroom/discovery/` "
            f"(schemas.csv, tables_views.csv, columns.csv, metric_candidates.md)\n"
            f"- Статус SELECT: ok={can_select}\n"
        )
        text = docs.read_text(encoding="utf-8")
        marker = "## Последний discovery"
        if marker in text:
            text = text.split(marker)[0].rstrip() + note
        else:
            text = text.rstrip() + note
        docs.write_text(text, encoding="utf-8")
        print(f"Updated: {docs}")

    print("\nDone. Passwords were not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
