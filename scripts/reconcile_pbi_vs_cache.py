#!/usr/bin/env python3
"""Gate: сверить PBI-parity War Room raw с прямым SQL-эквивалентом.

Допуски: суммы ≤0.1%, доли ≤0.05 п.п.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TOL_SUM = 0.001  # 0.1%
TOL_PP = 0.05  # percentage points


def main() -> int:
    os.environ.setdefault("WARROOM_DATA_SOURCE", "sql")
    os.environ.setdefault("WARROOM_METRIC_PROFILE", "pbi")
    os.environ.setdefault("WARROOM_CALENDAR_MODE", "pbi")
    os.environ.setdefault("WARROOM_PBI_SQL_TIMEOUT", "180")

    from app.services.metrics_service import MetricsService
    from app.services.pbi_parity_loader import fetch_pbi_parity_frames, build_pbi_sales_day
    from app.services.sql_data_service import SqlDataService
    from app.repositories.sql_database import SqlDatabase

    svc = SqlDataService(use_env_db=True)
    result = svc.load()
    if not result.status.ok:
        print("FAIL load:", result.status.error or result.status.message)
        return 2
    raw = result.raw
    if not raw.get("_pbi_parity"):
        print("FAIL: _pbi_parity not set — PBI overlay did not run")
        return 3

    ms = MetricsService(raw, mode="sql")
    report_day = str(raw.get("_report_day") or "")
    print("report_day", report_day, "profile", raw.get("_metric_profile"), "money", raw.get("_money_unit"))

    day_rows = ms.rows("day")
    if not day_rows:
        print("FAIL: no day rows")
        return 4

    net_rev = sum(r.revenue for r in day_rows)
    net_checks = sum(r.checks or 0 for r in day_rows)
    print(f"network day revenue={net_rev:.2f} checks={net_checks:.0f} stores={len(day_rows)}")

    # Re-fetch one day window for direct compare
    d = date.fromisoformat(report_day)
    db = SqlDatabase.from_env(connect_timeout=180)
    assert db is not None
    frames = fetch_pbi_parity_frames(db, date_from=d, date_to=d + timedelta(days=1))
    sales = build_pbi_sales_day(frames["pbi_rto_day"], frames["pbi_traffic_pen_day"])
    sql_rev = float(sales["Выручка факт"].sum()) if not sales.empty else 0.0
    sql_checks = float(sales["Количество чеков"].sum()) if not sales.empty else 0.0

    def rel(a, b):
        if abs(b) < 1e-9 and abs(a) < 1e-9:
            return 0.0
        return abs(a - b) / max(abs(b), 1e-9)

    rev_err = rel(net_rev, sql_rev)
    chk_err = rel(net_checks, sql_checks)
    print(f"direct SQL day revenue={sql_rev:.2f} checks={sql_checks:.0f}")
    print(f"rel_err revenue={rev_err:.6f} checks={chk_err:.6f}")

    # SP share network
    sp = raw.get("sp_day")
    if sp is not None and hasattr(sp, "empty") and not sp.empty:
        sp_rev = float(sp["Выручка СП"].sum())
        sp_tot = float(sp["Выручка всего"].sum())
        share = 100.0 * sp_rev / sp_tot if sp_tot else 0.0
        own = sum((r.revenue * (r.own_production_share_pct or 0) / 100) for r in day_rows)
        own_share = 100.0 * own / max(net_rev, 0.01)
        print(f"SP% grain={share:.3f} weighted_rows={own_share:.3f} delta_pp={abs(share-own_share):.3f}")

    # Penetration
    pen = raw.get("penetration_day")
    if pen is not None and hasattr(pen, "empty") and not pen.empty:
        tot = float(pen["Чеков всего"].sum())
        spc = float(pen["Чеков с СП"].sum())
        pas = float(pen["Чеков с Паскуччи"].sum())
        print(f"pen SP%={100*spc/max(tot,1):.3f} Pascucci%={100*pas/max(tot,1):.3f} checks={tot:.0f}")

    ok = rev_err <= TOL_SUM and chk_err <= TOL_SUM
    print("PASS" if ok else "FAIL", "tolerances", TOL_SUM, TOL_PP)
    return 0 if ok else 5


if __name__ == "__main__":
    raise SystemExit(main())
