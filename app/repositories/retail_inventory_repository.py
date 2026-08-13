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
DOC_INVENTORY = "_Document124"
VT_INVENTORY = "_Document124_VT2532"
DOC_SUPPLIER_RETURN = "_Document112"
VT_SUPPLIER_RETURN = "_Document112_VT1970"
# DocumentChngR1990 — регистрация изменений Document112 (не тело)
DOC_WRITEOFF = "_Document172"  # Документ.СписаниеТоваров (каталог 1С)
VT_WRITEOFF = "_Document172_VT4675"
DOC_TRANSFER = "_Document144"  # Документ.ПеремещениеТоваров (каталог 1С)
VT_TRANSFER = "_Document144_VT3584"
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
    COGS_WARNING = (
        "COGS из _AccumRg6691._Fld6708. Зерно регистра ≠ чеки _Document156 "
        "(контроль 2026-08-10: AccumRg выручка ~4.4× продаж чеков). "
        "Маржу считать только внутри AccumRg (выручка Fld6704 − COGS Fld6708), не смешивать с net_revenue чеков."
    )
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

    def load_inventories_daily(self, f: InventoryFilters) -> pd.DataFrame:
        """Инвентаризация: _Document124 + VT2532 (подтверждено бизнесом)."""
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
                   CAST(d._Fld2523 AS float) AS header_amount
            FROM dbo.{DOC_INVENTORY} AS d
            WHERE d._Posted = 0x01
              AND d._Marked = 0x00
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
                    FROM dbo.{VT_INVENTORY}
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
            lambda x: "инвентаризация: недостача"
            if float(x or 0) < 0
            else "инвентаризация: излишек"
            if float(x or 0) > 0
            else "инвентаризация: нулевая корректировка"
        )
        return (
            merged.groupby(["op_date", "store_name", "disposal_type"], as_index=False)
            .agg(document_count=("doc_id", "count"), qty=("qty", "sum"), amount_rub=("amount_rub", "sum"))
            .sort_values(["op_date", "amount_rub"], ascending=[True, False])
        )

    def load_writeoffs_daily(self, f: InventoryFilters) -> pd.DataFrame:
        """Списание товаров: _Document172 + VT4675 (каталог: Документ.СписаниеТоваров)."""
        _validate(f)
        d0 = to_1c_datetime(f.date_from)
        d1 = to_1c_datetime(inclusive_date_to_exclusive(f.date_to))
        from app.domain.retail_1c_dates import sql_date_from_doc
        from app.domain.store_prefix_map import store_name_from_document_number

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
                   CAST(d._Fld4665 AS float) AS header_amount
            FROM dbo.{DOC_WRITEOFF} AS d
            WHERE d._Posted = 0x01
              AND d._Marked = 0x00
              AND d._Date_Time >= %s AND d._Date_Time < %s
              {store_clause}
            """,
            params=(d0, d1, *store_params),
        )
        if docs.empty:
            return pd.DataFrame(
                columns=["op_date", "store_name", "disposal_type", "document_count", "qty", "amount_rub"]
            )
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
                    SELECT _Document172_IDRRef AS doc_id,
                           SUM(CAST(_Fld4680 AS float)) AS qty,
                           SUM(CAST(_Fld4685 AS float)) AS amount_rub
                    FROM dbo.{VT_WRITEOFF}
                    WHERE _Document172_IDRRef IN ({ph})
                    GROUP BY _Document172_IDRRef
                    """,
                    params=tuple(chunk),
                )
            )
        lines = pd.concat(line_frames, ignore_index=True) if line_frames else pd.DataFrame()
        merged = docs.merge(lines, on="doc_id", how="left")
        merged["qty"] = pd.to_numeric(merged.get("qty"), errors="coerce").fillna(0)
        merged["amount_rub"] = pd.to_numeric(merged.get("amount_rub"), errors="coerce").fillna(
            pd.to_numeric(merged["header_amount"], errors="coerce")
        )
        merged["disposal_type"] = "списание товаров (_Document172)"
        return (
            merged.groupby(["op_date", "store_name", "disposal_type"], as_index=False)
            .agg(document_count=("doc_id", "count"), qty=("qty", "sum"), amount_rub=("amount_rub", "sum"))
            .sort_values(["op_date", "amount_rub"], ascending=[True, False])
        )

    def load_transfers_daily(self, f: InventoryFilters) -> pd.DataFrame:
        """Перемещение товаров: _Document144 + VT3584 (каталог: Документ.ПеремещениеТоваров)."""
        _validate(f)
        d0 = to_1c_datetime(f.date_from)
        d1 = to_1c_datetime(inclusive_date_to_exclusive(f.date_to))
        from app.domain.retail_1c_dates import sql_date_from_doc
        from app.domain.store_prefix_map import store_name_from_document_number

        sale_date = sql_date_from_doc("d")
        docs = self.db.fetch_df(
            f"""
            SELECT d._IDRRef AS doc_id, {sale_date} AS op_date,
                   LTRIM(RTRIM(CAST(d._Number AS nvarchar(50)))) AS doc_number,
                   CAST(d._Fld3569 AS float) AS header_amount
            FROM dbo.{DOC_TRANSFER} AS d
            WHERE d._Posted = 0x01
              AND d._Date_Time >= %s AND d._Date_Time < %s
            """,
            params=(d0, d1),
        )
        if docs.empty:
            return pd.DataFrame(
                columns=["op_date", "store_name", "disposal_type", "document_count", "qty_candidate", "amount_candidate"]
            )
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
                    SELECT _Document144_IDRRef AS doc_id,
                           SUM(CAST(_Fld3587 AS float)) AS qty_candidate,
                           SUM(CAST(_Fld3592 AS float)) AS amount_candidate
                    FROM dbo.{VT_TRANSFER}
                    WHERE _Document144_IDRRef IN ({ph})
                    GROUP BY _Document144_IDRRef
                    """,
                    params=tuple(chunk),
                )
            )
        lines = pd.concat(line_frames, ignore_index=True) if line_frames else pd.DataFrame()
        merged = docs.merge(lines, on="doc_id", how="left")
        merged["qty_candidate"] = pd.to_numeric(merged.get("qty_candidate"), errors="coerce").fillna(0)
        merged["amount_candidate"] = pd.to_numeric(merged.get("amount_candidate"), errors="coerce").fillna(
            pd.to_numeric(merged["header_amount"], errors="coerce")
        )
        merged["disposal_type"] = "перемещение товаров (_Document144)"
        return (
            merged.groupby(["op_date", "store_name", "disposal_type"], as_index=False)
            .agg(
                document_count=("doc_id", "count"),
                qty_candidate=("qty_candidate", "sum"),
                amount_candidate=("amount_candidate", "sum"),
            )
            .sort_values(["op_date", "amount_candidate"], ascending=[True, False])
        )

    def load_supplier_returns_daily(self, f: InventoryFilters) -> pd.DataFrame:
        """Возврат поставщику: _Document112 (+ ChngR1990 = регистрация изменений)."""
        _validate(f)
        d0 = to_1c_datetime(f.date_from)
        d1 = to_1c_datetime(inclusive_date_to_exclusive(f.date_to))
        from app.domain.retail_1c_dates import sql_date_from_doc
        from app.domain.store_prefix_map import store_name_from_document_number

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
                   CAST(d._Fld1964 AS float) AS header_amount
            FROM dbo.{DOC_SUPPLIER_RETURN} AS d
            WHERE d._Posted = 0x01
              AND d._Date_Time >= %s AND d._Date_Time < %s
              {store_clause}
            """,
            params=(d0, d1, *store_params),
        )
        if docs.empty:
            return pd.DataFrame(
                columns=["op_date", "store_name", "document_count", "qty", "amount_rub"]
            )
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
                    SELECT _Document112_IDRRef AS doc_id,
                           SUM(CAST(_Fld1973 AS float)) AS qty,
                           SUM(CAST(_Fld1977 AS float)) AS amount_rub
                    FROM dbo.{VT_SUPPLIER_RETURN}
                    WHERE _Document112_IDRRef IN ({ph})
                    GROUP BY _Document112_IDRRef
                    """,
                    params=tuple(chunk),
                )
            )
        lines = pd.concat(line_frames, ignore_index=True) if line_frames else pd.DataFrame()
        merged = docs.merge(lines, on="doc_id", how="left")
        merged["qty"] = pd.to_numeric(merged.get("qty"), errors="coerce").fillna(0)
        merged["amount_rub"] = pd.to_numeric(merged.get("amount_rub"), errors="coerce").fillna(
            pd.to_numeric(merged["header_amount"], errors="coerce")
        )
        return (
            merged.groupby(["op_date", "store_name"], as_index=False)
            .agg(document_count=("doc_id", "count"), qty=("qty", "sum"), amount_rub=("amount_rub", "sum"))
            .sort_values(["op_date", "amount_rub"], ascending=[True, False])
        )

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
