"""COGS, stock, write-offs — SQL candidates (SELECT only, bounded periods)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd

from app.domain.retail_1c_dates import inclusive_date_to_exclusive, sql_period_from_accum, to_1c_datetime
from app.domain.store_prefix_map import prefixes_for_store_name
from app.domain.warehouse_store_map import warehouse_to_store
from app.repositories.sql_database import SqlDatabase

ACCUM_SALES = "_AccumRg6691"
ACCUM_STOCK = "_AccumRg6601"
REF_STORE = "_Reference64"
REF_WAREHOUSE = "_Reference76"
DOC_WRITEOFF = "_Document124"
VT_WRITEOFF = "_Document124_VT2532"
DOC_TRANSFER = "_Document122"
REF_NOMEN = "_Reference58"


@dataclass
class InventoryFilters:
    date_from: date
    date_to: date
    store_name: Optional[str] = None


def _validate(f: InventoryFilters) -> None:
    if f.date_from > f.date_to:
        raise ValueError("date_from must be <= date_to")
    if (f.date_to - f.date_from).days + 1 > 31:
        raise ValueError("Инвентарные регистры: период не более 31 дня.")


class RetailInventoryRepository:
    COGS_WARNING = "Себестоимость из _AccumRg6691._Fld6708 — требуется финальная сверка с 1С."
    STOCK_WARNING = "Остатки из _AccumRg6601 — кандидат по складу; связь склад→магазин эвристическая."

    def __init__(self, db: Optional[SqlDatabase] = None):
        self.db = db or SqlDatabase.from_env(connect_timeout=120)
        if self.db is None:
            raise RuntimeError("DATABASE_URL не задан")

    def _period_params(self, f: InventoryFilters) -> tuple:
        _validate(f)
        return (
            to_1c_datetime(f.date_from),
            to_1c_datetime(inclusive_date_to_exclusive(f.date_to)),
        )

    def load_cogs_daily(self, f: InventoryFilters) -> pd.DataFrame:
        """Revenue + COGS by store/day from _AccumRg6691."""
        d0, d1 = self._period_params(f)
        sale_date = sql_period_from_accum("t")
        sql = f"""
        SELECT
            {sale_date} AS sale_date,
            LTRIM(RTRIM(CAST(r._Description AS nvarchar(255)))) AS store_name,
            LTRIM(RTRIM(CAST(r._Code AS nvarchar(50)))) AS store_code,
            SUM(CAST(t._Fld6704 AS float)) AS revenue,
            SUM(CAST(t._Fld6708 AS float)) AS cogs,
            SUM(CAST(t._Fld6703 AS float)) AS qty_sold
        FROM dbo.{ACCUM_SALES} AS t
        INNER JOIN dbo.{REF_STORE} AS r ON r._IDRRef = t._Fld6692RRef
        WHERE t._Active = 0x01
          AND t._Period >= %s AND t._Period < %s
          AND r._Marked = 0x00
        GROUP BY {sale_date},
            LTRIM(RTRIM(CAST(r._Description AS nvarchar(255)))),
            LTRIM(RTRIM(CAST(r._Code AS nvarchar(50))))
        ORDER BY sale_date, revenue DESC
        """
        df = self.db.fetch_df(sql, params=(d0, d1))
        if df.empty or not f.store_name:
            return df
        return df[df["store_name"].astype(str).str.contains(f.store_name, case=False, na=False)]

    def load_stock_by_warehouse(self, f: InventoryFilters) -> pd.DataFrame:
        """Stock candidate: sum qty (_Fld6607) and amount (_Fld6608) by warehouse/day."""
        d0, d1 = self._period_params(f)
        sale_date = sql_period_from_accum("t")
        sql = f"""
        SELECT
            {sale_date} AS stock_date,
            LTRIM(RTRIM(CAST(w._Description AS nvarchar(255)))) AS warehouse,
            SUM(CAST(t._Fld6607 AS float)) AS qty,
            SUM(CAST(t._Fld6608 AS float)) AS amount_rub,
            SUM(CASE WHEN CAST(t._Fld6605 AS float) = 1 THEN CAST(t._Fld6608 AS float) ELSE 0 END) AS move_in_rub,
            SUM(CASE WHEN CAST(t._Fld6605 AS float) = 2 THEN CAST(t._Fld6608 AS float) ELSE 0 END) AS move_out_rub
        FROM dbo.{ACCUM_STOCK} AS t
        INNER JOIN dbo.{REF_WAREHOUSE} AS w ON w._IDRRef = t._Fld6603RRef
        WHERE t._Active = 0x01
          AND t._Period >= %s AND t._Period < %s
        GROUP BY {sale_date}, LTRIM(RTRIM(CAST(w._Description AS nvarchar(255))))
        ORDER BY stock_date, amount_rub DESC
        """
        df = self.db.fetch_df(sql, params=(d0, d1))
        if df.empty:
            return df
        df["store_name"] = df["warehouse"].map(warehouse_to_store)
        if f.store_name:
            df = df[df["store_name"].astype(str).str.contains(f.store_name, case=False, na=False)]
        return df

    def load_writeoffs_daily(self, f: InventoryFilters) -> pd.DataFrame:
        """Write-off candidate: _Document124 + lines VT2532."""
        _validate(f)
        d0 = to_1c_datetime(f.date_from)
        d1 = to_1c_datetime(inclusive_date_to_exclusive(f.date_to))
        from app.domain.retail_1c_dates import sql_date_from_doc

        sale_date = sql_date_from_doc("d")
        store_clause, store_params = "", []
        if f.store_name:
            prefixes = prefixes_for_store_name(f.store_name)
            if prefixes:
                parts, store_params = [], []
                for p in prefixes:
                    parts.append("LTRIM(RTRIM(CAST(d._Number AS nvarchar(50)))) LIKE %s")
                    store_params.append(f"{p}%")
                store_clause = f" AND ({' OR '.join(parts)})"

        docs = self.db.fetch_df(
            f"""
            SELECT d._IDRRef AS doc_id, {sale_date} AS op_date,
                   LTRIM(RTRIM(CAST(d._Number AS nvarchar(50)))) AS doc_number,
                   CAST(d._Fld2523 AS float) AS header_amount,
                   CAST(d._Fld2526_RTRef AS binary(4)) AS op_type_ref
            FROM dbo.{DOC_WRITEOFF} AS d
            WHERE d._Posted = 0x01
              AND d._Date_Time >= %s AND d._Date_Time < %s
              {store_clause}
            """,
            params=(d0, d1, *store_params),
        )
        if docs.empty:
            return pd.DataFrame(
                columns=[
                    "op_date",
                    "store_name",
                    "disposal_type",
                    "document_count",
                    "qty",
                    "amount_rub",
                ]
            )
        from app.domain.store_prefix_map import store_name_from_document_number

        docs["store_name"] = docs["doc_number"].map(store_name_from_document_number)
        ids = [bytes(x) for x in docs["doc_id"].tolist()]
        line_frames: list[pd.DataFrame] = []
        batch = 400
        for i in range(0, len(ids), batch):
            chunk = ids[i : i + batch]
            ph = ",".join(["%s"] * len(chunk))
            line_frames.append(
                self.db.fetch_df(
                    f"""
                    SELECT _Document124_IDRRef AS doc_id,
                           SUM(CAST(_Fld2535 AS float)) AS qty,
                           SUM(CAST(_Fld2540 AS float)) AS amount_rub
                    FROM dbo.{VT_WRITEOFF}
                    WHERE _Document124_IDRRef IN ({ph})
                    GROUP BY _Document124_IDRRef
                    """,
                    params=tuple(chunk),
                )
            )
        lines = pd.concat(line_frames, ignore_index=True) if line_frames else pd.DataFrame()
        merged = docs.merge(lines, on="doc_id", how="left")
        merged["qty"] = pd.to_numeric(merged.get("qty"), errors="coerce").fillna(0)
        merged["amount_rub"] = pd.to_numeric(merged.get("amount_rub"), errors="coerce").fillna(0)
        merged["disposal_type"] = merged["header_amount"].apply(
            lambda x: "списание (кандидат _Document124)"
            if float(x or 0) < 0
            else "инвентаризационная корректировка (кандидат)"
            if float(x or 0) > 0
            else "неидентифицированный тип выбытия"
        )
        out = (
            merged.groupby(["op_date", "store_name", "disposal_type"], as_index=False)
            .agg(document_count=("doc_id", "count"), qty=("qty", "sum"), amount_rub=("amount_rub", "sum"))
            .sort_values(["op_date", "amount_rub"], ascending=[True, False])
        )
        return out

    def load_transfers_daily(self, f: InventoryFilters) -> pd.DataFrame:
        """Transfer candidate: _Document122."""
        _validate(f)
        d0 = to_1c_datetime(f.date_from)
        d1 = to_1c_datetime(inclusive_date_to_exclusive(f.date_to))
        from app.domain.retail_1c_dates import sql_date_from_doc

        sale_date = sql_date_from_doc("d")
        sql = f"""
        SELECT {sale_date} AS op_date,
               COUNT(*) AS document_count,
               SUM(CAST(d._Fld2443 AS float)) AS qty_candidate,
               SUM(CAST(d._Fld2444 AS float)) AS amount_candidate
        FROM dbo.{DOC_TRANSFER} AS d
        WHERE d._Posted = 0x01
          AND d._Date_Time >= %s AND d._Date_Time < %s
        GROUP BY {sale_date}
        """
        df = self.db.fetch_df(sql, params=(d0, d1))
        if not df.empty:
            df["disposal_type"] = "перемещение (кандидат _Document122)"
        return df

    def load_nomenclature_top(
        self, f: InventoryFilters, doc_ids: list[bytes], limit: int = 100
    ) -> pd.DataFrame:
        """Top nomenclature by qty from check lines (requires pre-selected doc ids)."""
        if not doc_ids:
            return pd.DataFrame(columns=["nomenclature", "qty", "amount_rub"])
        from app.repositories.retail_sales_repository import VT_LINES

        frames: list[pd.DataFrame] = []
        batch = 400
        for i in range(0, len(doc_ids), batch):
            chunk = doc_ids[i : i + batch]
            ph = ",".join(["%s"] * len(chunk))
            frames.append(
                self.db.fetch_df(
                    f"""
                    SELECT v._Fld4041RRef AS nom_id,
                           SUM(CAST(v._Fld4042 AS float)) AS qty,
                           SUM(CAST(v._Fld4048 AS float)) AS amount_rub
                    FROM dbo.{VT_LINES} AS v
                    WHERE v._Document156_IDRRef IN ({ph})
                    GROUP BY v._Fld4041RRef
                    """,
                    params=tuple(chunk),
                )
            )
        agg = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if agg.empty:
            return agg
        agg = agg.groupby("nom_id", as_index=False).agg(qty=("qty", "sum"), amount_rub=("amount_rub", "sum"))
        agg = agg.sort_values("amount_rub", ascending=False).head(limit)
        nom_ids = [bytes(x) for x in agg["nom_id"].tolist()]
        names: dict[bytes, str] = {}
        for nid in nom_ids:
            row = self.db.fetch_df(
                f"SELECT LTRIM(RTRIM(CAST(_Description AS nvarchar(255)))) AS n FROM dbo.{REF_NOMEN} WHERE _IDRRef = %s",
                params=(nid,),
            )
            if not row.empty:
                names[nid] = str(row.iloc[0, 0])
        agg["nomenclature"] = agg["nom_id"].map(lambda x: names.get(bytes(x), "Требуется mapping номенклатуры"))
        return agg[["nomenclature", "qty", "amount_rub"]]
