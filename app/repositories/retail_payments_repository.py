"""Shift-close payments: dbo._Document119 + dbo._Document119_VT2299 + dbo._Reference89.

See app/domain/payment_form_mapping.py for the per-check limitation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd

from app.domain.payment_form_mapping import (
    PAYMENT_CATEGORY_BONUSES,
    PAYMENT_CATEGORY_CARDS,
    PAYMENT_CATEGORY_CASH,
    PAYMENT_CATEGORY_CASHLESS,
    PAYMENT_CATEGORY_CERTIFICATES,
    PAYMENT_CATEGORY_OTHER,
    build_payment_form_map,
    payment_form_label,
)
from app.domain.retail_1c_dates import inclusive_date_to_exclusive, sql_date_from_doc, to_1c_datetime
from app.domain.store_prefix_map import extract_store_prefix, prefixes_for_store_name, store_name_from_document_number
from app.repositories.sql_database import SqlDatabase

SHIFT_DOC = "_Document119"
SHIFT_PAY_VT = "_Document119_VT2299"
REF_PAYMENT = "_Reference89"


@dataclass
class PaymentPeriodFilters:
    date_from: date
    date_to: date
    store_name: Optional[str] = None


def _validate_period(f: PaymentPeriodFilters) -> None:
    if f.date_from > f.date_to:
        raise ValueError("date_from must be <= date_to")
    if (f.date_to - f.date_from).days + 1 > 93:
        raise ValueError("Период больше 93 дней — сузьте диапазон.")


def _store_filter_clause(f: PaymentPeriodFilters) -> tuple[str, list]:
    prefixes = prefixes_for_store_name(f.store_name) if f.store_name else []
    if not prefixes:
        return "", []
    clauses, params = [], []
    for p in prefixes:
        clauses.append("LTRIM(RTRIM(CAST(d._Number AS nvarchar(50)))) LIKE %s")
        params.append(f"{p}%")
    return f" AND ({' OR '.join(clauses)})", params


class RetailPaymentsRepository:
    DATA_SCOPE_LABEL = "оплаты по закрытиям смен (не форма оплаты отдельного чека)"

    def __init__(self, db: Optional[SqlDatabase] = None):
        self.db = db or SqlDatabase.from_env(connect_timeout=120)
        if self.db is None:
            raise RuntimeError("DATABASE_URL не задан — см. ~/.config/warroom/warroom.env")
        self._payment_map = self._load_reference_map()

    def _load_reference_map(self):
        ref = self.db.fetch_df(
            f"""
            SELECT _IDRRef, LTRIM(RTRIM(CAST(_Description AS nvarchar(255)))) AS descr
            FROM dbo.{REF_PAYMENT}
            WHERE _Marked = 0x00
            """
        )
        return build_payment_form_map(ref)

    def load_payment_lines(self, f: PaymentPeriodFilters) -> pd.DataFrame:
        """Raw shift-close payment lines with store and form label."""
        _validate_period(f)
        sale_date = sql_date_from_doc("d")
        dt_from = to_1c_datetime(f.date_from)
        dt_to_excl = to_1c_datetime(inclusive_date_to_exclusive(f.date_to))
        store_clause, store_params = _store_filter_clause(f)
        sql = f"""
        SELECT
            {sale_date} AS close_date,
            LTRIM(RTRIM(CAST(d._Number AS nvarchar(50)))) AS shift_document_number,
            d._IDRRef AS shift_doc_id,
            v._Fld2301RRef AS payment_form_id,
            CAST(v._Fld2302 AS float) AS amount
        FROM dbo.{SHIFT_DOC} AS d
        INNER JOIN dbo.{SHIFT_PAY_VT} AS v ON v._Document119_IDRRef = d._IDRRef
        WHERE d._Posted = 0x01
          AND d._Date_Time >= %s
          AND d._Date_Time < %s
          {store_clause}
        """
        params: list = [dt_from, dt_to_excl, *store_params]
        df = self.db.fetch_df(sql, params=tuple(params))
        if df.empty:
            return df
        df["store_prefix"] = df["shift_document_number"].map(extract_store_prefix)
        df["store_name"] = df["shift_document_number"].map(store_name_from_document_number)
        df["payment_form_id"] = df["payment_form_id"].apply(lambda x: bytes(x) if x is not None else None)

        def _label(b):
            return payment_form_label(self._payment_map.get(b) if b else None)

        def _cat(b):
            info = self._payment_map.get(b) if b else None
            return info.category if info else PAYMENT_CATEGORY_OTHER

        df["payment_form_name"] = df["payment_form_id"].map(_label)
        df["payment_category"] = df["payment_form_id"].map(_cat)
        df["data_scope"] = self.DATA_SCOPE_LABEL
        return df

    def load_payment_summary_by_shift(self, f: PaymentPeriodFilters) -> pd.DataFrame:
        """One row per shift-close document × payment form."""
        return self.load_payment_lines(f)

    def load_payment_summary_daily(self, f: PaymentPeriodFilters) -> pd.DataFrame:
        """Aggregate payments by calendar day, store, and payment category."""
        lines = self.load_payment_lines(f)
        if lines.empty:
            return lines
        agg = (
            lines.groupby(["close_date", "store_name", "payment_category", "payment_form_name"], as_index=False)
            .agg(amount=("amount", "sum"), shift_documents=("shift_doc_id", "nunique"))
            .sort_values(["close_date", "store_name", "amount"], ascending=[True, True, False])
        )
        agg["data_scope"] = self.DATA_SCOPE_LABEL
        return agg

    def load_payment_summary_by_category(self, f: PaymentPeriodFilters) -> pd.DataFrame:
        """Roll up to cash / cards / cashless / certificates / bonuses / other."""
        lines = self.load_payment_lines(f)
        if lines.empty:
            return pd.DataFrame(
                columns=[
                    "close_date",
                    "store_name",
                    "cash",
                    "cards",
                    "cashless",
                    "certificates",
                    "bonuses",
                    "other",
                    "total",
                    "data_scope",
                ]
            )
        pivot = (
            lines.groupby(["close_date", "store_name", "payment_category"], as_index=False)["amount"]
            .sum()
            .pivot_table(
                index=["close_date", "store_name"],
                columns="payment_category",
                values="amount",
                fill_value=0.0,
                aggfunc="sum",
            )
            .reset_index()
        )
        for cat in (
            PAYMENT_CATEGORY_CASH,
            PAYMENT_CATEGORY_CARDS,
            PAYMENT_CATEGORY_CASHLESS,
            PAYMENT_CATEGORY_CERTIFICATES,
            PAYMENT_CATEGORY_BONUSES,
            PAYMENT_CATEGORY_OTHER,
        ):
            if cat not in pivot.columns:
                pivot[cat] = 0.0
        pivot["total"] = pivot[
            [
                PAYMENT_CATEGORY_CASH,
                PAYMENT_CATEGORY_CARDS,
                PAYMENT_CATEGORY_CASHLESS,
                PAYMENT_CATEGORY_CERTIFICATES,
                PAYMENT_CATEGORY_BONUSES,
                PAYMENT_CATEGORY_OTHER,
            ]
        ].sum(axis=1)
        pivot["data_scope"] = self.DATA_SCOPE_LABEL
        return pivot
