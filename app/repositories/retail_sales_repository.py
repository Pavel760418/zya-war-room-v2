"""Confirmed retail sales SQL layer: dbo._Document156 + dbo._Document156_VT4039.

Read-only SELECT, parameterized date bounds, no heavy unbounded scans.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.domain.retail_1c_dates import inclusive_date_to_exclusive, sql_date_from_doc, to_1c_datetime
from app.domain.store_prefix_map import (
    extract_store_prefix,
    prefixes_for_store_name,
    store_name_from_document_number,
)
from app.repositories.sql_database import SqlDatabase

DOC_TABLE = "_Document156"
VT_LINES = "_Document156_VT4039"
REF_PRICE_TYPES = "_Reference92"

# _Fld4036: 1 = return, 2 = sale (IT-confirmed).
OP_RETURN = 1
OP_SALE = 2


@dataclass
class SalesPeriodFilters:
    date_from: date
    date_to: date
    store_name: Optional[str] = None


def _validate_period(f: SalesPeriodFilters) -> None:
    if f.date_from > f.date_to:
        raise ValueError("date_from must be <= date_to")
    span = (f.date_to - f.date_from).days + 1
    if span > 93:
        raise ValueError("Период больше 93 дней — сузьте диапазон (защита от тяжёлых запросов).")


def _store_sql_filter(f: SalesPeriodFilters) -> tuple[str, list]:
    prefixes = prefixes_for_store_name(f.store_name) if f.store_name else []
    if not prefixes:
        return "", []
    # Parameterized OR on LEFT number prefix (2 chars).
    clauses = []
    params: list = []
    for p in prefixes:
        clauses.append("LTRIM(RTRIM(CAST(d._Number AS nvarchar(50)))) LIKE %s")
        params.append(f"{p}%")
    return f" AND ({' OR '.join(clauses)})", params


class RetailSalesRepository:
    def __init__(self, db: Optional[SqlDatabase] = None):
        self.db = db or SqlDatabase.from_env(connect_timeout=120)
        if self.db is None:
            raise RuntimeError("DATABASE_URL не задан — см. ~/.config/warroom/warroom.env")

    def _base_doc_where(self, f: SalesPeriodFilters) -> tuple[str, list]:
        _validate_period(f)
        sale_date = sql_date_from_doc("d")
        dt_from = to_1c_datetime(f.date_from)
        dt_to_excl = to_1c_datetime(inclusive_date_to_exclusive(f.date_to))
        store_clause, store_params = _store_sql_filter(f)
        where = f"""
        d._Posted = 0x01
        AND d._Date_Time >= %s
        AND d._Date_Time < %s
        {store_clause}
        """
        params = [dt_from, dt_to_excl, *store_params]
        return where, params, sale_date

    def load_receipts_daily(self, f: SalesPeriodFilters) -> pd.DataFrame:
        """One row per calendar day: checks, returns, sales, net revenue, avg ticket."""
        where, params, sale_date = self._base_doc_where(f)
        sql = f"""
        SELECT
            {sale_date} AS sale_date,
            SUM(CASE WHEN d._Fld4036 = {OP_SALE} THEN 1 ELSE 0 END) AS sales_checks,
            SUM(CASE WHEN d._Fld4036 = {OP_RETURN} THEN 1 ELSE 0 END) AS return_checks,
            COUNT(*) AS total_checks,
            SUM(CASE WHEN d._Fld4036 = {OP_SALE} THEN CAST(d._Fld4030 AS float) ELSE 0 END) AS sales_amount,
            SUM(CASE WHEN d._Fld4036 = {OP_RETURN} THEN CAST(d._Fld4030 AS float) ELSE 0 END) AS returns_amount,
            SUM(CASE WHEN d._Fld4036 = {OP_SALE} THEN CAST(d._Fld4030 AS float) ELSE 0 END)
              - SUM(CASE WHEN d._Fld4036 = {OP_RETURN} THEN CAST(d._Fld4030 AS float) ELSE 0 END) AS net_revenue
        FROM dbo.{DOC_TABLE} AS d
        WHERE {where}
        GROUP BY {sale_date}
        ORDER BY {sale_date}
        """
        df = self.db.fetch_df(sql, params=tuple(params))
        if df.empty:
            return df
        df["avg_ticket"] = df.apply(
            lambda r: (r["net_revenue"] / r["sales_checks"]) if r["sales_checks"] else None,
            axis=1,
        )
        return df

    def load_sales_daily(self, f: SalesPeriodFilters) -> pd.DataFrame:
        """Daily sales with line aggregates (qty, line sums) via bounded two-step fetch."""
        return self._load_sales_daily_two_step(f)

    def _load_sales_daily_two_step(self, f: SalesPeriodFilters) -> pd.DataFrame:
        where, params, sale_date = self._base_doc_where(f)
        doc_sql = f"""
        SELECT
            d._IDRRef AS doc_id,
            {sale_date} AS sale_date,
            d._Fld4036 AS operation_type,
            CAST(d._Fld4030 AS float) AS document_amount
        FROM dbo.{DOC_TABLE} AS d
        WHERE {where}
        """
        docs = self.db.fetch_df(doc_sql, params=tuple(params))
        if docs.empty:
            return pd.DataFrame(
                columns=[
                    "sale_date",
                    "operation_type",
                    "document_count",
                    "document_amount",
                    "line_count",
                    "qty_sold",
                    "line_amount",
                    "line_amount_vat",
                ]
            )

        # Lines for selected docs only — batch by ids if needed
        ids = docs["doc_id"].tolist()
        line_frames: list[pd.DataFrame] = []
        batch = 500
        for i in range(0, len(ids), batch):
            chunk = ids[i : i + batch]
            placeholders = ",".join(["%s"] * len(chunk))
            line_sql = f"""
            SELECT
                v._Document156_IDRRef AS doc_id,
                COUNT(*) AS line_count,
                SUM(CAST(v._Fld4042 AS float)) AS qty_sold,
                SUM(CAST(v._Fld4048 AS float)) AS line_amount,
                SUM(CAST(v._Fld4054 AS float)) AS line_amount_vat
            FROM dbo.{VT_LINES} AS v
            WHERE v._Document156_IDRRef IN ({placeholders})
            GROUP BY v._Document156_IDRRef
            """
            line_frames.append(self.db.fetch_df(line_sql, params=tuple(chunk)))

        lines = pd.concat(line_frames, ignore_index=True) if line_frames else pd.DataFrame()
        merged = docs.merge(lines, on="doc_id", how="left")
        for col in ("line_count", "qty_sold", "line_amount", "line_amount_vat"):
            merged[col] = pd.to_numeric(merged.get(col), errors="coerce").fillna(0)

        out = (
            merged.groupby(["sale_date", "operation_type"], as_index=False)
            .agg(
                document_count=("doc_id", "count"),
                document_amount=("document_amount", "sum"),
                line_count=("line_count", "sum"),
                qty_sold=("qty_sold", "sum"),
                line_amount=("line_amount", "sum"),
                line_amount_vat=("line_amount_vat", "sum"),
            )
            .sort_values(["sale_date", "operation_type"])
        )
        return out

    def load_returns_daily(self, f: SalesPeriodFilters) -> pd.DataFrame:
        f_ret = SalesPeriodFilters(f.date_from, f.date_to, f.store_name)
        daily = self.load_receipts_daily(f_ret)
        if daily.empty:
            return daily
        return daily[
            ["sale_date", "return_checks", "returns_amount"]
        ].rename(columns={"return_checks": "document_count", "returns_amount": "amount"})

    def load_sales_by_store(self, f: SalesPeriodFilters) -> pd.DataFrame:
        where, params, sale_date = self._base_doc_where(f)
        sql = f"""
        SELECT
            {sale_date} AS sale_date,
            LTRIM(RTRIM(CAST(d._Number AS nvarchar(50)))) AS document_number,
            d._Fld4036 AS operation_type,
            CAST(d._Fld4030 AS float) AS document_amount
        FROM dbo.{DOC_TABLE} AS d
        WHERE {where}
        """
        df = self.db.fetch_df(sql, params=tuple(params))
        if df.empty:
            return df
        df["store_prefix"] = df["document_number"].map(extract_store_prefix)
        df["store_name"] = df["document_number"].map(store_name_from_document_number)
        agg = (
            df.groupby(["sale_date", "store_name", "store_prefix", "operation_type"], as_index=False)
            .agg(document_count=("document_amount", "count"), amount=("document_amount", "sum"))
            .sort_values(["sale_date", "store_name", "operation_type"])
        )
        return agg

    def load_sales_by_cashier(self, f: SalesPeriodFilters) -> pd.DataFrame:
        """Optional slice — cashier name from _Fld4020 (not a primary KPI)."""
        where, params, sale_date = self._base_doc_where(f)
        sql = f"""
        SELECT
            {sale_date} AS sale_date,
            LTRIM(RTRIM(CAST(d._Fld4020 AS nvarchar(4000)))) AS cashier,
            d._Fld4036 AS operation_type,
            COUNT(*) AS document_count,
            SUM(CAST(d._Fld4030 AS float)) AS amount
        FROM dbo.{DOC_TABLE} AS d
        WHERE {where}
        GROUP BY {sale_date}, LTRIM(RTRIM(CAST(d._Fld4020 AS nvarchar(4000)))), d._Fld4036
        ORDER BY sale_date, amount DESC
        """
        return self.db.fetch_df(sql, params=tuple(params))

    def load_price_type_candidates(self, f: SalesPeriodFilters) -> pd.DataFrame:
        """Frequency of _Fld4016RRef on checks; names from _Reference92 when available."""
        _validate_period(f)
        where, params, _sale_date = self._base_doc_where(f)
        sql = f"""
        SELECT
            d._Fld4016RRef AS price_type_id,
            COUNT(*) AS check_count,
            SUM(CAST(d._Fld4030 AS float)) AS document_amount
        FROM dbo.{DOC_TABLE} AS d
        WHERE {where}
        GROUP BY d._Fld4016RRef
        ORDER BY check_count DESC
        """
        freq = self.db.fetch_df(sql, params=tuple(params))
        if freq.empty:
            return freq

        ref = self.db.fetch_df(
            f"""
            SELECT _IDRRef AS price_type_id,
                   LTRIM(RTRIM(CAST(_Description AS nvarchar(255)))) AS price_type_name
            FROM dbo.{REF_PRICE_TYPES}
            WHERE _Marked = 0x00
            """
        )

        def _bkey(val) -> Optional[str]:
            if val is None:
                return None
            return bytes(val).hex()

        freq["_join_key"] = freq["price_type_id"].map(_bkey)
        if not ref.empty:
            ref["_join_key"] = ref["price_type_id"].map(_bkey)
            freq = freq.merge(ref[["_join_key", "price_type_name"]], on="_join_key", how="left")
        else:
            freq["price_type_name"] = None
        freq.drop(columns=["_join_key"], inplace=True, errors="ignore")
        freq["mapping_status"] = freq.apply(
            lambda row: (
                "confirmed_name"
                if pd.notna(row.get("price_type_name")) and str(row.get("price_type_name")).strip()
                else "candidate_no_ref92_match"
            ),
            axis=1,
        )
        return freq
