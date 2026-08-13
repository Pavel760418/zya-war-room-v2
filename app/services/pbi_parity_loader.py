"""Assemble PBI-parity raw sheets from retail + ucs (read-only)."""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Any, Optional

import pandas as pd

from app.ingestion.sql_pbi_overview import (
    SQL_PBI_EXPENSE_DAILY,
    SQL_PBI_INVENTORY_DAILY,
    SQL_PBI_RTO_DAILY,
    SQL_PBI_SURPLUS_DAILY,
    SQL_PBI_TRAFFIC_PEN_DAILY,
    SQL_PBI_WRITEOFF_ALL_ARTICLES_DAILY,
    SQL_PBI_WRITEOFF_DAILY,
)
from app.metrics.loss_articles import (
    EXPENSE_ARTICLES,
    GROUP_EXPENSE,
    GROUP_INVENTORY,
    classify_article,
    is_commodity_writeoff,
    is_expense,
)
from app.repositories.sql_database import SqlDatabase

log = logging.getLogger("warroom.pbi_parity")


def metric_profile() -> str:
    return (os.environ.get("WARROOM_METRIC_PROFILE") or "pbi").strip().lower()


def calendar_mode() -> str:
    return (os.environ.get("WARROOM_CALENDAR_MODE") or "pbi").strip().lower()


def fetch_pbi_parity_frames(
    db: SqlDatabase,
    *,
    date_from: date,
    date_to: date,
    rto_date_from: Optional[date] = None,
) -> dict[str, pd.DataFrame]:
    """Pull daily PBI grains. ``date_to`` exclusive.

    ``rto_date_from`` — расширенное окно для LFL/г/г (DATEADD −1 YEAR); если None — = date_from.
    Трафик/списания остаются в коротком окне ``date_from``.
    """
    bind = {"date_from": date_from, "date_to": date_to}
    rto_bind = {"date_from": rto_date_from or date_from, "date_to": date_to}
    out: dict[str, pd.DataFrame] = {}
    old_timeout = db.connect_timeout
    db.connect_timeout = max(old_timeout, int(os.environ.get("WARROOM_PBI_SQL_TIMEOUT", "180")))
    try:
        out["pbi_rto_day"] = db.fetch_df(SQL_PBI_RTO_DAILY, params=rto_bind)
        out["pbi_writeoff_day"] = db.fetch_df(SQL_PBI_WRITEOFF_DAILY, params=bind)
        out["pbi_writeoff_all_day"] = db.fetch_df(SQL_PBI_WRITEOFF_ALL_ARTICLES_DAILY, params=bind)
        out["pbi_expense_day"] = db.fetch_df(SQL_PBI_EXPENSE_DAILY, params=bind)
        out["pbi_inventory_day"] = db.fetch_df(SQL_PBI_INVENTORY_DAILY, params=bind)
        out["pbi_surplus_day"] = db.fetch_df(SQL_PBI_SURPLUS_DAILY, params=bind)
        out["pbi_traffic_pen_day"] = db.fetch_df(SQL_PBI_TRAFFIC_PEN_DAILY, params=bind)
    finally:
        db.connect_timeout = old_timeout
    return out


def build_pbi_sales_day(
    rto: pd.DataFrame, traffic: pd.DataFrame, *, clip_to_traffic: bool = False
) -> pd.DataFrame:
    """Merge revenue (retail) + checks (ucs) into sales_day shape.

    ``clip_to_traffic=False`` (default for calendar): keep full RTO history for month/LFL.
    """
    if rto is None or rto.empty:
        rto = pd.DataFrame(columns=["Дата", "Магазин", "Выручка факт", "Выручка СП"])
    if traffic is None or traffic.empty:
        traffic = pd.DataFrame(columns=["Дата", "Магазин", "Количество чеков", "Чеков с СП", "Чеков с Паскуччи"])
    r = rto.copy()
    t = traffic.copy()
    r["Дата"] = pd.to_datetime(r["Дата"], errors="coerce")
    t["Дата"] = pd.to_datetime(t["Дата"], errors="coerce")
    r["Магазин"] = r["Магазин"].astype(str)
    t["Магазин"] = t["Магазин"].astype(str)
    # Для UI sales_day по умолчанию не режем историю RTO — месяц/LFL берут полный календарь.
    if clip_to_traffic and not t.empty:
        t_min, t_max = t["Дата"].min(), t["Дата"].max()
        r = r[(r["Дата"] >= t_min) & (r["Дата"] <= t_max)].copy() if t_min is not pd.NaT else r
    merged = r.merge(
        t[["Дата", "Магазин", "Количество чеков", "Чеков с СП", "Чеков с Паскуччи"]],
        on=["Дата", "Магазин"],
        how="outer",
    )
    for col in ("Выручка факт", "Выручка СП", "Количество чеков", "Чеков с СП", "Чеков с Паскуччи"):
        if col not in merged.columns:
            merged[col] = 0.0
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0)
    merged["Выручка план"] = 0.0
    return merged


def build_pbi_losses_day(
    writeoff: pd.DataFrame,
    inventory: pd.DataFrame,
    *,
    writeoff_all: Optional[pd.DataFrame] = None,
    expenses: Optional[pd.DataFrame] = None,
    surplus: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Структура потерь: товарные Списания + Недостачи + Расходы (отдельно)."""
    frames = []
    # Prefer article-level commodity writeoffs
    src = writeoff if isinstance(writeoff, pd.DataFrame) else pd.DataFrame()
    if isinstance(writeoff_all, pd.DataFrame) and not writeoff_all.empty:
        w_all = writeoff_all.copy()
        w_all["Статья списания"] = w_all.get("Статья списания", "").astype(str)
        commodity = w_all[w_all["Статья списания"].map(is_commodity_writeoff)].copy()
        if not commodity.empty:
            commodity["Вид потерь"] = commodity["Статья списания"]
            commodity["Группа"] = "Списания"
            frames.append(commodity)
        # Other non-expense articles for structure (optional detail)
        other = w_all[
            ~w_all["Статья списания"].map(is_commodity_writeoff)
            & ~w_all["Статья списания"].map(is_expense)
        ].copy()
        if not other.empty:
            other["Вид потерь"] = other["Статья списания"]
            other["Группа"] = other["Статья списания"].map(classify_article)
            frames.append(other)
    elif isinstance(src, pd.DataFrame) and not src.empty:
        w = src.copy()
        if "Статья списания" not in w.columns:
            w["Статья списания"] = "Потеря потребительских свойств"
        w["Вид потерь"] = w["Статья списания"].astype(str)
        w["Группа"] = "Списания"
        frames.append(w)

    if isinstance(expenses, pd.DataFrame) and not expenses.empty:
        e = expenses.copy()
        e["Статья списания"] = e.get("Статья списания", "").astype(str)
        e["Вид потерь"] = e["Статья списания"]
        e["Группа"] = GROUP_EXPENSE
        frames.append(e)
    elif isinstance(writeoff_all, pd.DataFrame) and not writeoff_all.empty:
        exp = writeoff_all[writeoff_all["Статья списания"].astype(str).isin(EXPENSE_ARTICLES)].copy()
        if not exp.empty:
            exp["Вид потерь"] = exp["Статья списания"].astype(str)
            exp["Группа"] = GROUP_EXPENSE
            frames.append(exp)

    if isinstance(inventory, pd.DataFrame) and not inventory.empty:
        inv = inventory.copy()
        inv["Вид потерь"] = GROUP_INVENTORY
        inv["Группа"] = GROUP_INVENTORY
        inv["Статья списания"] = GROUP_INVENTORY
        inv["Сумма"] = pd.to_numeric(inv["Сумма"], errors="coerce").fillna(0.0)
        frames.append(inv)

    if isinstance(surplus, pd.DataFrame) and not surplus.empty:
        from app.metrics.loss_articles import GROUP_SURPLUS

        su = surplus.copy()
        su["Вид потерь"] = GROUP_SURPLUS
        su["Группа"] = GROUP_SURPLUS
        su["Статья списания"] = GROUP_SURPLUS
        su["Сумма"] = pd.to_numeric(su["Сумма"], errors="coerce").fillna(0.0)
        frames.append(su)

    if not frames:
        return pd.DataFrame(columns=["Дата", "Магазин", "Вид потерь", "Группа", "Статья списания", "Сумма"])
    out = pd.concat(frames, ignore_index=True)
    out["Дата"] = pd.to_datetime(out["Дата"], errors="coerce")
    return out


def build_pbi_penetration_day(traffic: pd.DataFrame) -> pd.DataFrame:
    if traffic is None or traffic.empty:
        return pd.DataFrame(columns=["Дата", "Магазин", "Чеков всего", "Чеков с СП", "Чеков с Паскуччи"])
    df = traffic.copy()
    df["Дата"] = pd.to_datetime(df["Дата"], errors="coerce")
    df = df.rename(columns={"Количество чеков": "Чеков всего"})
    return df[["Дата", "Магазин", "Чеков всего", "Чеков с СП", "Чеков с Паскуччи"]]


def build_pbi_sp_day(rto: pd.DataFrame) -> pd.DataFrame:
    if rto is None or rto.empty:
        return pd.DataFrame(columns=["Дата", "Магазин", "Выручка СП", "Выручка всего"])
    df = rto.copy()
    df["Дата"] = pd.to_datetime(df["Дата"], errors="coerce")
    df["Выручка всего"] = pd.to_numeric(df["Выручка факт"], errors="coerce").fillna(0.0)
    df["Выручка СП"] = pd.to_numeric(df.get("Выручка СП", 0), errors="coerce").fillna(0.0)
    return df[["Дата", "Магазин", "Выручка СП", "Выручка всего"]]


def apply_pbi_parity_to_raw(raw: dict[str, Any], frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Replace UI-facing sheets with PBI grains; keep legacy_* copies if present."""
    for key in (
        "sales_day",
        "sales_week",
        "sales_month",
        "penetration_week",
        "losses_month",
        "writeoff_week",
        "sp_month",
        "expenses_month",
    ):
        if key in raw and isinstance(raw[key], pd.DataFrame) and f"legacy_{key}" not in raw:
            raw[f"legacy_{key}"] = raw[key].copy()

    sales = build_pbi_sales_day(frames.get("pbi_rto_day", pd.DataFrame()), frames.get("pbi_traffic_pen_day", pd.DataFrame()))
    losses = build_pbi_losses_day(
        frames.get("pbi_writeoff_day", pd.DataFrame()),
        frames.get("pbi_inventory_day", pd.DataFrame()),
        writeoff_all=frames.get("pbi_writeoff_all_day"),
        expenses=frames.get("pbi_expense_day"),
        surplus=frames.get("pbi_surplus_day"),
    )
    pen = build_pbi_penetration_day(frames.get("pbi_traffic_pen_day", pd.DataFrame()))
    sp = build_pbi_sp_day(frames.get("pbi_rto_day", pd.DataFrame()))

    raw["pbi_rto_day"] = frames.get("pbi_rto_day", pd.DataFrame())
    raw["pbi_traffic_pen_day"] = frames.get("pbi_traffic_pen_day", pd.DataFrame())
    raw["pbi_writeoff_day"] = frames.get("pbi_writeoff_day", pd.DataFrame())
    raw["pbi_writeoff_all_day"] = frames.get("pbi_writeoff_all_day", pd.DataFrame())
    raw["pbi_expense_day"] = frames.get("pbi_expense_day", pd.DataFrame())
    raw["pbi_inventory_day"] = frames.get("pbi_inventory_day", pd.DataFrame())
    raw["pbi_surplus_day"] = frames.get("pbi_surplus_day", pd.DataFrame())

    raw["sales_day"] = sales
    raw["penetration_week"] = pen
    raw["losses_month"] = losses
    # KPI «Спи» = все статьи РТО С
    wo_all = frames.get("pbi_writeoff_all_day", pd.DataFrame())
    if isinstance(wo_all, pd.DataFrame) and not wo_all.empty:
        raw["writeoff_week"] = wo_all.copy()
    else:
        wo = frames.get("pbi_writeoff_day", pd.DataFrame())
        raw["writeoff_week"] = wo.copy() if isinstance(wo, pd.DataFrame) else pd.DataFrame(
            columns=["Дата", "Магазин", "Статья списания", "Сумма"]
        )
    exp = frames.get("pbi_expense_day", pd.DataFrame())
    raw["expenses_month"] = exp.copy() if isinstance(exp, pd.DataFrame) else pd.DataFrame()
    raw["sp_month"] = sp
    raw["_metric_profile"] = "pbi"
    raw["_money_unit"] = "rub"
    raw["_pbi_parity"] = True
    return raw


def pbi_report_day(sales: pd.DataFrame) -> Optional[pd.Timestamp]:
    """Calendar mode pbi: latest date with any network sales (no 80% gate)."""
    if sales is None or sales.empty or "Дата" not in sales.columns:
        return None
    d = pd.to_datetime(sales["Дата"], errors="coerce").dropna()
    if d.empty:
        return None
    return d.max()


def lfl_rto_pct(current: float, prior_year: float) -> Optional[float]:
    """DAX LFL РТО: IF(id2=0, BLANK, DIVIDE(id1,id2)-1) → доля в % для UI."""
    if prior_year is None or float(prior_year) == 0.0:
        return None
    return (float(current) / float(prior_year) - 1.0) * 100.0
