"""Orchestrates retail SQL metrics for War Room Streamlit (primary data path)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

import pandas as pd

from app.core.settings import redact_error
from app.domain.store_prefix_map import STORE_PREFIX_TO_NAME
from app.repositories.retail_inventory_repository import InventoryFilters, RetailInventoryRepository
from app.repositories.retail_payments_repository import PaymentPeriodFilters, RetailPaymentsRepository
from app.repositories.retail_sales_repository import (
    OP_RETURN,
    OP_SALE,
    RetailSalesRepository,
    SalesPeriodFilters,
)
from app.repositories.sql_database import SqlDatabase, SqlStatus


@dataclass
class RetailWarRoomSnapshot:
    ok: bool
    message: str
    sql_status: SqlStatus
    loaded_at: str
    date_from: date
    date_to: date
    store_filter: Optional[str]
    warnings: list[str] = field(default_factory=list)
    receipts_daily: pd.DataFrame = field(default_factory=pd.DataFrame)
    sales_daily: pd.DataFrame = field(default_factory=pd.DataFrame)
    sales_by_store: pd.DataFrame = field(default_factory=pd.DataFrame)
    sales_by_cashier: pd.DataFrame = field(default_factory=pd.DataFrame)
    payments_by_category: pd.DataFrame = field(default_factory=pd.DataFrame)
    payment_lines: pd.DataFrame = field(default_factory=pd.DataFrame)
    cogs_daily: pd.DataFrame = field(default_factory=pd.DataFrame)
    stock_by_warehouse: pd.DataFrame = field(default_factory=pd.DataFrame)
    writeoffs_daily: pd.DataFrame = field(default_factory=pd.DataFrame)
    transfers_daily: pd.DataFrame = field(default_factory=pd.DataFrame)
    nomenclature_top: pd.DataFrame = field(default_factory=pd.DataFrame)
    price_types: pd.DataFrame = field(default_factory=pd.DataFrame)
    unknown_store_prefixes: pd.DataFrame = field(default_factory=pd.DataFrame)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    kpis: dict[str, Optional[float]] = field(default_factory=dict)


def _rollup_kpis(
    receipts: pd.DataFrame,
    sales_daily: pd.DataFrame,
    cogs: pd.DataFrame,
    stock: pd.DataFrame,
    writeoffs: pd.DataFrame,
) -> dict[str, Optional[float]]:
    out: dict[str, Optional[float]] = {
        "sales_amount": None,
        "returns_amount": None,
        "net_revenue": None,
        "sales_checks": None,
        "avg_ticket": None,
        "qty_sold": None,
        "line_amount": None,
        "line_amount_vat": None,
        "cogs": None,
        "gross_profit": None,
        "gross_margin_pct": None,
        "stock_qty": None,
        "stock_rub": None,
        "writeoff_amount": None,
        "writeoff_qty": None,
    }
    if not receipts.empty:
        out["sales_amount"] = float(receipts["sales_amount"].sum())
        out["returns_amount"] = float(receipts["returns_amount"].sum())
        out["net_revenue"] = float(receipts["net_revenue"].sum())
        out["sales_checks"] = float(receipts["sales_checks"].sum())
        if out["sales_checks"]:
            out["avg_ticket"] = out["net_revenue"] / out["sales_checks"] if out["net_revenue"] is not None else None
    if not sales_daily.empty:
        sale_rows = sales_daily[sales_daily["operation_type"] == OP_SALE]
        out["qty_sold"] = float(sale_rows["qty_sold"].sum()) if not sale_rows.empty else 0.0
        out["line_amount"] = float(sales_daily["line_amount"].sum())
        out["line_amount_vat"] = float(sales_daily["line_amount_vat"].sum())
    if not cogs.empty:
        out["cogs"] = float(cogs["cogs"].sum())
        reg_rev = float(cogs["revenue"].sum())
        if out["net_revenue"] is not None and out["cogs"] is not None:
            out["gross_profit"] = out["net_revenue"] - out["cogs"]
            base = out["net_revenue"] if out["net_revenue"] else reg_rev
            out["gross_margin_pct"] = (out["gross_profit"] / base * 100) if base else None
    if not stock.empty:
        out["stock_qty"] = float(stock["qty"].sum())
        out["stock_rub"] = float(stock["amount_rub"].sum())
    if not writeoffs.empty:
        out["writeoff_qty"] = float(writeoffs["qty"].sum())
        out["writeoff_amount"] = float(writeoffs["amount_rub"].sum())
    return out


class RetailWarRoomService:
    def __init__(self, db: Optional[SqlDatabase] = None):
        self.db = db or SqlDatabase.from_env(connect_timeout=120)

    def health(self) -> SqlStatus:
        if self.db is None:
            return SqlStatus(ok=False, message="DATABASE_URL не задан", error="missing_database_url")
        return self.db.ping()

    def load(
        self,
        date_from: date,
        date_to: date,
        store_name: Optional[str] = None,
    ) -> RetailWarRoomSnapshot:
        now = datetime.now(timezone.utc).isoformat()
        status = self.health()
        empty = RetailWarRoomSnapshot(
            ok=False,
            message=status.message,
            sql_status=status,
            loaded_at=now,
            date_from=date_from,
            date_to=date_to,
            store_filter=store_name,
            warnings=[status.error or status.message],
        )
        if not status.ok or self.db is None:
            return empty

        warnings: list[str] = [
            "Оплаты — только «Оплаты по закрытиям смен», не привязаны к отдельному чеку.",
            RetailInventoryRepository.COGS_WARNING,
            RetailInventoryRepository.STOCK_WARNING,
        ]
        sf = SalesPeriodFilters(date_from, date_to, store_name)
        pf = PaymentPeriodFilters(date_from, date_to, store_name)
        invf = InventoryFilters(date_from, date_to, store_name)

        try:
            sales = RetailSalesRepository(self.db)
            pays = RetailPaymentsRepository(self.db)
            inv = RetailInventoryRepository(self.db)

            receipts = sales.load_receipts_daily(sf)
            sales_daily = sales.load_sales_daily(sf)
            by_store = sales.load_sales_by_store(sf)
            by_cashier = sales.load_sales_by_cashier(sf)
            price_types = sales.load_price_type_candidates(sf)
            pay_cat = pays.load_payment_summary_by_category(pf)
            pay_lines = pays.load_payment_lines(pf)
            cogs = inv.load_cogs_daily(invf)
            stock = inv.load_stock_by_warehouse(invf)
            writeoffs = inv.load_writeoffs_daily(invf)
            transfers = inv.load_transfers_daily(invf)

            # Unknown prefixes
            if not by_store.empty and "store_prefix" in by_store.columns:
                known = set(STORE_PREFIX_TO_NAME.keys())
                pref = (
                    by_store.assign(
                        _pfx=lambda d: d["store_prefix"].astype(str),
                        _store=lambda d: d["store_name"].astype(str),
                    )
                    .groupby(["_pfx", "_store"], as_index=False)
                    .agg(docs=("document_count", "sum"))
                )
                unknown = pref[~pref["_pfx"].isin(known) | pref["_store"].str.contains("требуется mapping", na=False)]
            else:
                unknown = pd.DataFrame(columns=["prefix", "store_label", "documents"])

            if not unknown.empty:
                unknown = unknown.rename(columns={"_pfx": "prefix", "_store": "store_label", "docs": "documents"})
                warnings.append(f"Неизвестные префиксы магазинов: {len(unknown)}.")

            # Nomenclature (bounded: sales docs only)
            where, params, _ = sales._base_doc_where(sf)
            docs = sales.db.fetch_df(
                f"""
                SELECT d._IDRRef AS doc_id
                FROM dbo._Document156 AS d
                WHERE {where} AND d._Fld4036 = {OP_SALE}
                """,
                params=tuple(params),
            )
            doc_ids = [bytes(x) for x in docs["doc_id"].tolist()] if not docs.empty else []
            nom = inv.load_nomenclature_top(invf, doc_ids, limit=50)

            kpis = _rollup_kpis(receipts, sales_daily, cogs, stock, writeoffs)
            diag = {
                "documents_total": int(receipts["total_checks"].sum()) if not receipts.empty else 0,
                "documents_sales": int(receipts["sales_checks"].sum()) if not receipts.empty else 0,
                "documents_returns": int(receipts["return_checks"].sum()) if not receipts.empty else 0,
                "check_lines": int(sales_daily["line_count"].sum()) if not sales_daily.empty else 0,
                "shift_payment_total": float(pay_cat["total"].sum()) if not pay_cat.empty and "total" in pay_cat.columns else None,
                "data_sources": [
                    "dbo._Document156",
                    "dbo._Document156_VT4039",
                    "dbo._Document119_VT2299",
                    "dbo._AccumRg6691",
                    "dbo._AccumRg6601",
                    "dbo._Document124",
                    "dbo._Reference58",
                ],
            }

            if price_types is not None and not price_types.empty:
                unmapped = price_types[price_types["mapping_status"].astype(str).str.contains("no_ref92", na=False)]
                if len(unmapped):
                    warnings.append("Тип цены: справочник _Reference92 не сопоставлен с _Fld4016RRef — кандидат.")

            return RetailWarRoomSnapshot(
                ok=True,
                message="SQL данные загружены",
                sql_status=status,
                loaded_at=now,
                date_from=date_from,
                date_to=date_to,
                store_filter=store_name,
                warnings=warnings,
                receipts_daily=receipts,
                sales_daily=sales_daily,
                sales_by_store=by_store,
                sales_by_cashier=by_cashier,
                payments_by_category=pay_cat,
                payment_lines=pay_lines,
                cogs_daily=cogs,
                stock_by_warehouse=stock,
                writeoffs_daily=writeoffs,
                transfers_daily=transfers,
                nomenclature_top=nom,
                price_types=price_types,
                unknown_store_prefixes=unknown,
                diagnostics=diag,
                kpis=kpis,
            )
        except Exception as exc:  # noqa: BLE001
            err = redact_error(exc)
            warnings.append(err)
            empty.warnings = warnings
            empty.message = "Ошибка загрузки SQL"
            empty.sql_status = SqlStatus(
                ok=False,
                message=empty.message,
                server=status.server,
                database=status.database,
                error=err,
            )
            return empty
