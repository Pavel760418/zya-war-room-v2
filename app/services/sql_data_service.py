"""SQL data service: maps MSSQL 1C retail candidates into War Room ``raw`` dict.

Uses only SELECT. Candidate queries are tagged by confidence:
- high / medium / low — from discovery Excel analysis
- never claimed as IT-confirmed fact

Catalog ETL templates (logical 1C names, MSSQL dialect) live in
``app.ingestion.sql_extract`` (War-Room_Katalog_Metrik_SQL.xlsx). Physical
``_DocumentNNN`` / ``_AccumRgNNNN`` mapping still goes through the confirmed
retail repositories below until IT signs off on catalog object names.

Primary runtime feed (confirmed checks):
  dbo._Document156 + VT4039

Fallback candidate:
  dbo._AccumRg6691 + dbo._Reference64 (store) + resources _Fld6703/6704/6708
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from app.core.settings import get_app_settings, redact_error
from app.ingestion.schema import META_SHEET, SCHEMA
from app.repositories.sql_database import SqlDatabase, SqlStatus


@dataclass
class SqlLoadResult:
    raw: dict
    status: SqlStatus
    warnings: list[str] = field(default_factory=list)
    mapping_complete: bool = False
    last_success_at: Optional[str] = None
    confidence_notes: list[str] = field(default_factory=list)


# Official IT-confirmed mapping (empty until sign-off).
SQL_SHEET_MAPPING: dict[str, dict[str, Any]] = {}

# Discovery-backed candidates (high / medium / low). Not invented numbers.
CANDIDATE_QUERIES_ENABLED = True
YEAR_OFFSET = 2000  # dbo._YearOffset confirmed = 2000


class SqlDataService:
    def __init__(self, db: Optional[SqlDatabase] = None):
        settings = get_app_settings()
        # Longer timeout for aggregate SELECTs over accumulation registers.
        timeout = max(settings.sql_connect_timeout, 60)
        self.db = db or SqlDatabase.from_env(connect_timeout=timeout)

    def status(self) -> SqlStatus:
        if self.db is None:
            return SqlStatus(
                ok=False,
                message="DATABASE_URL не задан — укажите секреты в ~/.config/warroom/warroom.env",
                error="missing_database_url",
            )
        return self.db.ping()

    def empty_raw(self) -> dict:
        raw: dict = {
            "meta": pd.DataFrame(
                {
                    META_SHEET.key_col: ["Название сети", "Валюта", "Источник", "SQL статус"],
                    META_SHEET.value_col: ["Зеленое Яблоко", "RUB", "sql", "нет данных"],
                }
            )
        }
        for _canon, spec in SCHEMA.items():
            raw[spec.canonical] = pd.DataFrame({c.canonical: pd.Series(dtype=object) for c in spec.columns})
        return raw

    def load(self) -> SqlLoadResult:
        status = self.status()
        now = datetime.now(timezone.utc).isoformat()
        if not status.ok or self.db is None:
            raw = self.empty_raw()
            raw["meta"] = pd.DataFrame(
                {
                    META_SHEET.key_col: ["Название сети", "Валюта", "Источник", "SQL статус", "SQL ошибка"],
                    META_SHEET.value_col: [
                        "Зеленое Яблоко",
                        "RUB",
                        "sql",
                        "недоступен",
                        status.error or status.message,
                    ],
                }
            )
            return SqlLoadResult(
                raw=raw,
                status=status,
                warnings=[status.message, status.error or ""],
                mapping_complete=False,
                last_success_at=None,
            )

        if SQL_SHEET_MAPPING:
            return self._load_confirmed_mapping(status, now)

        if CANDIDATE_QUERIES_ENABLED:
            return self._load_candidates(status, now)

        raw = self.empty_raw()
        raw["meta"] = pd.DataFrame(
            {
                META_SHEET.key_col: ["Название сети", "Валюта", "Источник", "SQL статус", "Примечание"],
                META_SHEET.value_col: [
                    "Зеленое Яблоко",
                    "RUB",
                    "sql",
                    "подключён, маппинг пуст",
                    "Включите candidate-режим или подтвердите SQL_SHEET_MAPPING",
                ],
            }
        )
        return SqlLoadResult(
            raw=raw,
            status=status,
            warnings=["SQL доступен, но источники метрик не подключены."],
            mapping_complete=False,
            last_success_at=self.db.last_success_iso or now,
        )

    def _load_confirmed_mapping(self, status: SqlStatus, now: str) -> SqlLoadResult:
        assert self.db is not None
        raw = self.empty_raw()
        warnings: list[str] = []
        try:
            for sheet, cfg in SQL_SHEET_MAPPING.items():
                schema = cfg["schema"]
                obj = cfg["object"]
                colmap: dict[str, str] = cfg.get("column_map", {})
                select_cols = []
                for canon, sql_col in colmap.items():
                    if not _safe_ident(sql_col) or not _safe_ident(canon):
                        warnings.append(f"Пропущена небезопасная колонка в {sheet}")
                        continue
                    select_cols.append(f"[{sql_col}] AS [{canon}]")
                if not select_cols or not _safe_ident(schema) or not _safe_ident(obj):
                    continue
                sql = f"SELECT {', '.join(select_cols)} FROM [{schema}].[{obj}]"
                df = self.db.fetch_df(sql)
                spec = SCHEMA.get(sheet)
                if spec:
                    for c in spec.columns:
                        if c.canonical not in df.columns:
                            df[c.canonical] = c.default
                raw[sheet] = df
            raw["meta"] = pd.DataFrame(
                {
                    META_SHEET.key_col: ["Название сети", "Валюта", "Источник", "SQL статус", "Текущий день"],
                    META_SHEET.value_col: ["Зеленое Яблоко", "RUB", "sql", "ok", now[:10]],
                }
            )
            return SqlLoadResult(
                raw=raw,
                status=status,
                warnings=warnings,
                mapping_complete=True,
                last_success_at=self.db.last_success_iso or now,
            )
        except Exception as exc:  # noqa: BLE001
            return SqlLoadResult(
                raw=self.empty_raw(),
                status=SqlStatus(
                    ok=False,
                    message="Ошибка чтения SQL",
                    server=status.server,
                    database=status.database,
                    error=redact_error(exc),
                ),
                warnings=[redact_error(exc)],
                mapping_complete=False,
                last_success_at=None,
            )

    def _load_candidates(self, status: SqlStatus, now: str) -> SqlLoadResult:
        """Feed Excel-compatible raw from confirmed receipts; keep UI/MetricsService unchanged."""
        assert self.db is not None
        # Prefer confirmed _Document156 checks; fall back to AccumRg6691 if needed.
        try:
            return self._load_from_document156(status, now)
        except Exception as exc:  # noqa: BLE001
            warnings = [f"Чеки _Document156 недоступны: {redact_error(exc)} — fallback AccumRg6691"]
            try:
                result = self._load_from_accumrg6691(status, now)
                result.warnings = warnings + list(result.warnings or [])
                return result
            except Exception as exc2:  # noqa: BLE001
                return SqlLoadResult(
                    raw=self.empty_raw(),
                    status=SqlStatus(
                        ok=False,
                        message="Ошибка SQL загрузки",
                        server=status.server,
                        database=status.database,
                        error=redact_error(exc2),
                    ),
                    warnings=[redact_error(exc), redact_error(exc2)],
                    mapping_complete=False,
                )

    def _load_from_document156(self, status: SqlStatus, now: str) -> SqlLoadResult:
        """Confirmed retail checks → same raw sheets MetricsService already expects."""
        from datetime import date, timedelta

        from app.repositories.retail_sales_repository import OP_SALE, RetailSalesRepository, SalesPeriodFilters

        assert self.db is not None
        raw = self.empty_raw()
        warnings: list[str] = [
            "Планы продаж, доступность ТЗ/СП, СП — в SQL не подключены (как в Excel-шаблоне будут 0).",
            "Оплаты по закрытиям смен доступны в SQL-слое, но не в карточках текущего UI.",
        ]
        notes: list[str] = [
            "Источник продаж: dbo._Document156 + VT4039 (подтверждено).",
            "Магазин: префикс _Number → Python mapping.",
            "Чистая выручка = продажи (_Fld4036=2) − возвраты (_Fld4036=1).",
            "Чеки = количество документов продажи.",
        ]

        end = date.today()
        start = end - timedelta(days=30)
        sales_repo = RetailSalesRepository(self.db)
        by_store = sales_repo.load_sales_by_store(SalesPeriodFilters(start, end))
        if by_store.empty:
            warnings.append("Нет проведённых чеков _Document156 за последние 30 дней.")
            return SqlLoadResult(
                raw=raw,
                status=status,
                warnings=warnings,
                mapping_complete=False,
                last_success_at=self.db.last_success_iso or now,
                confidence_notes=notes,
            )

        by_store = by_store.copy()
        by_store["sale_date"] = pd.to_datetime(by_store["sale_date"])
        by_store["store_name"] = by_store["store_name"].astype(str)
        # Net revenue per store/day: sales − returns
        sales_part = by_store[by_store["operation_type"] == OP_SALE].groupby(
            ["sale_date", "store_name"], as_index=False
        ).agg(revenue=("amount", "sum"), checks=("document_count", "sum"))
        ret_part = by_store[by_store["operation_type"] == 1].groupby(
            ["sale_date", "store_name"], as_index=False
        ).agg(returns=("amount", "sum"))
        daily = sales_part.merge(ret_part, on=["sale_date", "store_name"], how="left")
        daily["returns"] = daily["returns"].fillna(0.0)
        daily["net_revenue"] = daily["revenue"] - daily["returns"]

        latest = daily["sale_date"].max()
        week_cut = latest - pd.Timedelta(days=6)
        month_mask = (daily["sale_date"].dt.year == latest.year) & (daily["sale_date"].dt.month == latest.month)

        day_df = daily.loc[daily["sale_date"] == latest]
        week_df = daily.loc[daily["sale_date"] >= week_cut]
        month_df = daily.loc[month_mask]

        def _sheet(df: pd.DataFrame, period: str) -> pd.DataFrame:
            if df.empty:
                return pd.DataFrame(
                    {
                        "Магазин": pd.Series(dtype=object),
                        "Выручка факт": pd.Series(dtype=float),
                        "Выручка план": pd.Series(dtype=float),
                        "Количество чеков": pd.Series(dtype=float),
                    }
                )
            g = (
                df.groupby("store_name", as_index=False)
                .agg(revenue=("net_revenue", "sum"), checks=("checks", "sum"))
            )
            out = pd.DataFrame(
                {
                    "Магазин": g["store_name"].astype(str),
                    "Выручка факт": pd.to_numeric(g["revenue"], errors="coerce").fillna(0.0),
                    "Выручка план": 0.0,
                    "Количество чеков": pd.to_numeric(g["checks"], errors="coerce").fillna(0.0),
                }
            )
            if period == "date":
                out["Дата"] = latest.strftime("%Y-%m-%d")
            elif period == "week":
                out["Неделя"] = "текущая (7д, SQL)"
            else:
                out["Месяц"] = latest.strftime("%Y-%m")
            return out

        raw["sales_day"] = _sheet(day_df, "date")
        raw["sales_week"] = _sheet(week_df, "week")
        raw["sales_month"] = _sheet(month_df, "month")
        notes.append(f"Магазинов за день {latest.date()}: {len(raw['sales_day'])}")
        notes.append(f"Чеков продаж (день): {int(raw['sales_day']['Количество чеков'].sum()) if not raw['sales_day'].empty else 0}")

        # Soft enrichment: stock losses remain empty (not confirmed for UI sheets).
        raw["meta"] = pd.DataFrame(
            {
                META_SHEET.key_col: [
                    "Название сети",
                    "Валюта",
                    "Источник",
                    "SQL статус",
                    "Текущий день",
                    "Режим SQL",
                    "Выручка",
                    "Чеки",
                    "Ограничения",
                ],
                META_SHEET.value_col: [
                    "Зеленое Яблоко",
                    "RUB",
                    "sql",
                    "ok",
                    latest.strftime("%Y-%m-%d"),
                    "Document156 confirmed",
                    "dbo._Document156._Fld4030 (продажи−возвраты)",
                    "dbo._Document156 count(_Fld4036=2)",
                    "План/ТЗ/СП/остатки в UI пока 0 — нет подтверждённого SQL-маппинга",
                ],
            }
        )
        return SqlLoadResult(
            raw=raw,
            status=status,
            warnings=warnings,
            mapping_complete=True,
            last_success_at=self.db.last_success_iso or now,
            confidence_notes=notes,
        )

    def _load_from_accumrg6691(self, status: SqlStatus, now: str) -> SqlLoadResult:
        """Legacy fallback candidate register (no check counts)."""
        assert self.db is not None
        raw = self.empty_raw()
        warnings: list[str] = [
            "Fallback: выручка из _AccumRg6691 (кандидат). Чеки = 0.",
        ]
        notes: list[str] = ["Источник: dbo._AccumRg6691 + _Reference64"]
        sales_day = self.db.fetch_df(
            """
            SELECT
                CAST(DATEADD(year, -2000, t._Period) AS date) AS sale_date,
                LTRIM(RTRIM(CAST(r._Description AS nvarchar(255)))) AS store_name,
                LTRIM(RTRIM(CAST(r._Code AS nvarchar(50)))) AS store_code,
                SUM(CAST(t._Fld6703 AS float)) AS qty,
                SUM(CAST(t._Fld6704 AS float)) AS revenue,
                SUM(CAST(t._Fld6708 AS float)) AS cogs
            FROM [dbo].[_AccumRg6691] AS t
            INNER JOIN [dbo].[_Reference64] AS r
                ON r._IDRRef = t._Fld6692RRef
            WHERE t._Period >= DATEADD(year, 2000, CAST(DATEADD(day, -31, GETDATE()) AS date))
              AND t._Period <  DATEADD(year, 2000, CAST(DATEADD(day,  1, GETDATE()) AS date))
              AND r._Marked = 0x00
              AND CAST(r._Description AS nvarchar(255)) NOT LIKE N'%не исп%'
              AND CAST(r._Code AS nvarchar(50)) NOT IN (N'127', N'001', N'100')
            GROUP BY
                CAST(DATEADD(year, -2000, t._Period) AS date),
                LTRIM(RTRIM(CAST(r._Description AS nvarchar(255)))),
                LTRIM(RTRIM(CAST(r._Code AS nvarchar(50))))
            ORDER BY sale_date DESC, revenue DESC
            """
        )
        if sales_day.empty:
            warnings.append("Нет данных _AccumRg6691 за последние 31 день.")
            latest = None
            sales_day_latest = sales_week = sales_month = sales_day
        else:
            sales_day["sale_date"] = pd.to_datetime(sales_day["sale_date"])
            latest = sales_day["sale_date"].max()
            month_mask = (sales_day["sale_date"].dt.year == latest.year) & (
                sales_day["sale_date"].dt.month == latest.month
            )
            week_cut = latest - pd.Timedelta(days=6)
            sales_month = (
                sales_day.loc[month_mask]
                .groupby(["store_name", "store_code"], as_index=False)
                .agg(revenue=("revenue", "sum"), qty=("qty", "sum"), cogs=("cogs", "sum"))
            )
            sales_week = (
                sales_day.loc[sales_day["sale_date"] >= week_cut]
                .groupby(["store_name", "store_code"], as_index=False)
                .agg(revenue=("revenue", "sum"), qty=("qty", "sum"), cogs=("cogs", "sum"))
            )
            sales_day_latest = sales_day.loc[sales_day["sale_date"] == latest].copy()

        def _to_sales_sheet(df: pd.DataFrame, period_label: str) -> pd.DataFrame:
            if df.empty:
                return pd.DataFrame(
                    {
                        "Магазин": pd.Series(dtype=object),
                        "Выручка факт": pd.Series(dtype=float),
                        "Выручка план": pd.Series(dtype=float),
                        "Количество чеков": pd.Series(dtype=float),
                    }
                )
            out = pd.DataFrame(
                {
                    "Магазин": df["store_name"].astype(str),
                    "Выручка факт": pd.to_numeric(df["revenue"], errors="coerce").fillna(0.0),
                    "Выручка план": 0.0,
                    "Количество чеков": 0.0,
                }
            )
            if period_label == "date" and "sale_date" in df.columns:
                out["Дата"] = pd.to_datetime(df["sale_date"]).dt.strftime("%Y-%m-%d")
            elif period_label == "week":
                out["Неделя"] = "текущая (7д, кандидат)"
            elif period_label == "month":
                out["Месяц"] = latest.strftime("%Y-%m") if latest is not None else ""
            return out

        raw["sales_day"] = _to_sales_sheet(sales_day_latest, "date")
        raw["sales_week"] = _to_sales_sheet(sales_week, "week")
        raw["sales_month"] = _to_sales_sheet(sales_month, "month")
        raw["meta"] = pd.DataFrame(
            {
                META_SHEET.key_col: ["Название сети", "Валюта", "Источник", "SQL статус", "Текущий день"],
                META_SHEET.value_col: [
                    "Зеленое Яблоко",
                    "RUB",
                    "sql-candidates",
                    "ok (fallback)",
                    (latest.strftime("%Y-%m-%d") if latest is not None else now[:10]),
                ],
            }
        )
        return SqlLoadResult(
            raw=raw,
            status=status,
            warnings=warnings,
            mapping_complete=False,
            last_success_at=self.db.last_success_iso or now,
            confidence_notes=notes,
        )


def _safe_ident(name: str) -> bool:
    if not name or len(name) > 128:
        return False
    return all(ch.isalnum() or ch in ("_",) for ch in name)
