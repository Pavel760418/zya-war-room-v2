"""Isolated analytics metrics facade over existing retail SQL repositories.

Does not modify Streamlit UI. Returns explicit statuses for missing/unconfirmed data.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

import pandas as pd

from app.core.settings import redact_error
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
class MetricValue:
    code: str
    name: str
    value: Any = None
    unit: Optional[str] = None
    status: str = "ok"  # ok | no_confirmed_data | requires_mapping | requires_final_1c_reconciliation | not_found
    warning: Optional[str] = None


@dataclass
class AnalyticsSnapshot:
    ok: bool
    message: str
    loaded_at: str
    date_from: str
    date_to: str
    store_filter: Optional[str]
    sql_status: dict
    metrics: list[MetricValue] = field(default_factory=list)
    tables: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


_CACHE: dict[str, tuple[float, AnalyticsSnapshot]] = {}
_CACHE_TTL_SEC = 300.0
_LAST_OK_AT: Optional[str] = None


def invalidate_cache() -> int:
    n = len(_CACHE)
    _CACHE.clear()
    return n


def sql_health() -> SqlStatus:
    db = SqlDatabase.from_env(connect_timeout=30)
    if db is None:
        return SqlStatus(ok=False, message="DATABASE_URL не задан", error="missing_database_url")
    return db.ping()


def _mv(code, name, value=None, unit=None, status="ok", warning=None) -> MetricValue:
    return MetricValue(code=code, name=name, value=value, unit=unit, status=status, warning=warning)


def load_analytics(
    date_from: date,
    date_to: date,
    store_name: Optional[str] = None,
    use_cache: bool = True,
) -> AnalyticsSnapshot:
    global _LAST_OK_AT
    key = f"{date_from}:{date_to}:{store_name or ''}"
    now_ts = datetime.now(timezone.utc).timestamp()
    if use_cache and key in _CACHE:
        ts, snap = _CACHE[key]
        if now_ts - ts < _CACHE_TTL_SEC:
            return snap

    loaded_at = datetime.now(timezone.utc).isoformat()
    st = sql_health()
    if not st.ok:
        snap = AnalyticsSnapshot(
            ok=False,
            message=st.message,
            loaded_at=loaded_at,
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
            store_filter=store_name,
            sql_status=asdict(st) if hasattr(st, "__dataclass_fields__") else st.__dict__,
            metrics=[_mv("sql", "SQL", status="no_confirmed_data", warning=st.error or st.message)],
            warnings=[st.error or st.message],
        )
        return snap

    warnings = [
        "Оплаты по закрытиям смен: форма оплаты не привязана к отдельному чеку.",
        RetailInventoryRepository.COGS_WARNING,
        RetailInventoryRepository.STOCK_WARNING,
    ]
    metrics: list[MetricValue] = []
    tables: dict[str, Any] = {}

    try:
        db = SqlDatabase.from_env(connect_timeout=120)
        assert db is not None
        sales = RetailSalesRepository(db)
        pays = RetailPaymentsRepository(db)
        inv = RetailInventoryRepository(db)
        sf = SalesPeriodFilters(date_from, date_to, store_name)
        pf = PaymentPeriodFilters(date_from, date_to, store_name)
        invf = InventoryFilters(date_from, date_to, store_name)

        receipts = sales.load_receipts_daily(sf)
        sales_daily = sales.load_sales_daily(sf)
        by_store = sales.load_sales_by_store(sf)
        by_cashier = sales.load_sales_by_cashier(sf)
        pay_cat = pays.load_payment_summary_by_category(pf)
        cogs = inv.load_cogs_daily(invf)
        stock = inv.load_stock_by_warehouse(invf)
        writeoffs = inv.load_writeoffs_daily(invf)
        inventories = inv.load_inventories_daily(invf)
        supplier_returns = inv.load_supplier_returns_daily(invf)
        transfers = inv.load_transfers_daily(invf)
        price_types = sales.load_price_type_candidates(sf)

        if receipts.empty:
            metrics.append(_mv("net_revenue", "Чистая выручка", status="no_confirmed_data"))
            metrics.append(_mv("sales", "Продажи", status="no_confirmed_data"))
            metrics.append(_mv("returns", "Возвраты", status="no_confirmed_data"))
            metrics.append(_mv("checks", "Количество чеков", status="no_confirmed_data"))
            metrics.append(_mv("avg_ticket", "Средний чек", status="no_confirmed_data"))
        else:
            sales_amt = float(receipts["sales_amount"].sum())
            ret_amt = float(receipts["returns_amount"].sum())
            net = float(receipts["net_revenue"].sum())
            checks = float(receipts["sales_checks"].sum())
            metrics.extend(
                [
                    _mv("sales", "Продажи", sales_amt, "rub"),
                    _mv("returns", "Возвраты", ret_amt, "rub"),
                    _mv("net_revenue", "Чистая выручка", net, "rub"),
                    _mv("checks", "Количество чеков", checks, "count"),
                    _mv(
                        "avg_ticket",
                        "Средний чек",
                        (net / checks) if checks else None,
                        "rub",
                        status="ok" if checks else "no_confirmed_data",
                    ),
                ]
            )

        if sales_daily.empty:
            metrics.append(_mv("qty_sold", "Количество проданных товаров", status="no_confirmed_data"))
            metrics.append(_mv("line_amount", "Сумма строк чека", status="no_confirmed_data"))
            metrics.append(_mv("line_amount_vat", "Сумма строк с НДС", status="no_confirmed_data"))
        else:
            sale_lines = sales_daily[sales_daily["operation_type"] == OP_SALE]
            metrics.append(_mv("qty_sold", "Количество проданных товаров", float(sale_lines["qty_sold"].sum()) if not sale_lines.empty else 0.0, "qty"))
            metrics.append(_mv("line_amount", "Сумма строк чека", float(sales_daily["line_amount"].sum()), "rub"))
            metrics.append(_mv("line_amount_vat", "Сумма строк с НДС", float(sales_daily["line_amount_vat"].sum()), "rub"))

        metrics.append(
            _mv(
                "cashier_slice",
                "Кассир (доп. разрез)",
                None if by_cashier.empty else int(by_cashier["document_count"].sum()),
                "docs",
                status="ok" if not by_cashier.empty else "no_confirmed_data",
            )
        )

        if price_types.empty or price_types["price_type_name"].isna().all():
            metrics.append(
                _mv(
                    "price_type",
                    "Тип цены",
                    status="requires_mapping",
                    warning="Справочник для _Fld4016RRef не сопоставлен",
                )
            )
        else:
            metrics.append(_mv("price_type", "Тип цены", int(len(price_types)), "distinct", status="ok"))

        if pay_cat.empty:
            metrics.append(
                _mv(
                    "payments_by_shift_close",
                    "Оплаты по закрытиям смен",
                    status="no_confirmed_data",
                    warning="Форма оплаты доступна на уровне закрытия смены и не привязана к отдельному чеку",
                )
            )
        else:
            metrics.append(
                _mv(
                    "payments_by_shift_close",
                    "Оплаты по закрытиям смен",
                    float(pay_cat["total"].sum()),
                    "rub",
                    warning="Форма оплаты доступна на уровне закрытия смены и не привязана к отдельному чеку",
                )
            )
            for col, title in [
                ("cash", "Наличные"),
                ("cards", "Карты"),
                ("cashless", "Безнал"),
                ("certificates", "Сертификаты"),
                ("bonuses", "Бонусы"),
                ("other", "Прочее"),
            ]:
                if col in pay_cat.columns:
                    metrics.append(_mv(f"pay_{col}", title, float(pay_cat[col].sum()), "rub"))

        if cogs.empty:
            metrics.append(
                _mv(
                    "cogs",
                    "Себестоимость",
                    status="requires_final_1c_reconciliation",
                    warning="Нет движений _AccumRg6691 за период",
                )
            )
            metrics.append(_mv("gross_profit", "Валовая прибыль (регистр)", status="no_confirmed_data"))
            metrics.append(_mv("gross_margin", "Валовая маржа (регистр)", status="no_confirmed_data"))
            metrics.append(
                _mv(
                    "gross_profit_vs_checks",
                    "Валовая прибыль (чеки−COGS)",
                    status="invalid_mix",
                    warning="Не смешивать net_revenue чеков с COGS AccumRg",
                )
            )
        else:
            cogs_v = float(cogs["cogs"].sum())
            reg_rev = float(cogs["revenue"].sum())
            metrics.append(
                _mv(
                    "cogs",
                    "Себестоимость",
                    cogs_v,
                    "rub",
                    status="ok_register_grain",
                    warning=RetailInventoryRepository.COGS_WARNING,
                )
            )
            metrics.append(
                _mv(
                    "register_revenue",
                    "Выручка регистра AccumRg6691",
                    reg_rev,
                    "rub",
                    status="ok_register_grain",
                    warning="Не равна выручке чеков Document156",
                )
            )
            gp_reg = reg_rev - cogs_v
            metrics.append(
                _mv(
                    "gross_profit",
                    "Валовая прибыль (регистр)",
                    gp_reg,
                    "rub",
                    status="ok_register_grain",
                    warning="Маржа только внутри AccumRg6691",
                )
            )
            metrics.append(
                _mv(
                    "gross_margin",
                    "Валовая маржа (регистр)",
                    (gp_reg / reg_rev * 100) if reg_rev else None,
                    "pct",
                    status="ok_register_grain",
                    warning="Маржа только внутри AccumRg6691",
                )
            )
            net_v = next((m.value for m in metrics if m.code == "net_revenue" and m.value is not None), None)
            if net_v is not None and float(net_v) > 0:
                ratio = reg_rev / float(net_v)
                metrics.append(
                    _mv(
                        "accum_vs_checks_ratio",
                        "Отношение выручки AccumRg / чеки",
                        ratio,
                        "x",
                        status="reconciled_mismatch",
                        warning="Контроль: смешивать нельзя; ≈4.4× к продажам чеков / ≈44× к net_revenue (2026-08-10)",
                    )
                )

        if stock.empty:
            metrics.append(_mv("stock_qty", "Остатки в штуках", status="requires_final_1c_reconciliation"))
            metrics.append(_mv("stock_rub", "Остатки в рублях", status="requires_final_1c_reconciliation"))
        else:
            metrics.append(
                _mv(
                    "stock_qty",
                    "Остатки в штуках",
                    float(stock["qty"].sum()),
                    "qty",
                    status="requires_final_1c_reconciliation",
                    warning="Кандидат _AccumRg6601",
                )
            )
            metrics.append(
                _mv(
                    "stock_rub",
                    "Остатки в рублях",
                    float(stock["amount_rub"].sum()),
                    "rub",
                    status="requires_final_1c_reconciliation",
                    warning="Кандидат _AccumRg6601",
                )
            )

        if inventories.empty:
            metrics.append(_mv("inventories", "Инвентаризация", status="no_confirmed_data"))
            metrics.append(_mv("inventory_adjustments", "Инвентаризационные корректировки", status="no_confirmed_data"))
            metrics.append(_mv("shortages", "Недостачи", status="no_confirmed_data"))
        else:
            inv_amt = float(inventories["amount_rub"].sum())
            metrics.append(
                _mv(
                    "inventories",
                    "Инвентаризация",
                    inv_amt,
                    "rub",
                    status="ok",
                    warning="Каталог+бизнес: _Document124 Документ.Инвентаризация",
                )
            )
            metrics.append(
                _mv(
                    "inventory_adjustments",
                    "Инвентаризационные корректировки",
                    inv_amt,
                    "rub",
                    status="ok",
                    warning="_Document124 по знаку суммы",
                )
            )
            short = inventories[inventories["disposal_type"].astype(str).str.contains("недостача", na=False)]
            metrics.append(
                _mv(
                    "shortages",
                    "Недостачи",
                    float(short["amount_rub"].sum()) if not short.empty else 0.0,
                    "rub",
                    status="ok",
                    warning="Инвентаризация: недостача (header<0)",
                )
            )

        if writeoffs.empty:
            metrics.append(_mv("writeoffs", "Списания", status="no_confirmed_data"))
        else:
            metrics.append(
                _mv(
                    "writeoffs",
                    "Списания",
                    float(writeoffs["amount_rub"].sum()),
                    "rub",
                    status="ok",
                    warning="Каталог: _Document172 Документ.СписаниеТоваров",
                )
            )
            metrics.append(
                _mv(
                    "writeoff_qty",
                    "Количество списанного товара",
                    float(writeoffs["qty"].sum()),
                    "qty",
                    status="ok",
                )
            )

        if supplier_returns.empty:
            metrics.append(_mv("supplier_returns", "Возврат поставщику", status="no_confirmed_data"))
        else:
            metrics.append(
                _mv(
                    "supplier_returns",
                    "Возврат поставщику",
                    float(supplier_returns["amount_rub"].sum()),
                    "rub",
                    status="ok",
                    warning="Каталог: _Document112 Документ.ВозвратПоставщику",
                )
            )

        if transfers.empty:
            metrics.append(_mv("transfers", "Перемещения", status="no_confirmed_data"))
        else:
            amt = float(transfers["amount_candidate"].sum()) if "amount_candidate" in transfers.columns else None
            metrics.append(
                _mv(
                    "transfers",
                    "Перемещения",
                    amt if amt is not None else float(transfers["document_count"].sum()),
                    "rub" if amt is not None else "docs",
                    status="ok",
                    warning="Каталог: _Document144 Документ.ПеремещениеТоваров",
                )
            )
        metrics.append(_mv("products", "Номенклатура", status="ok", warning="Источник _Reference58 через строки чека"))
        metrics.append(_mv("last_update", "Последнее обновление", loaded_at, "ts"))

        # Unknown store prefixes
        unknown = []
        if not by_store.empty:
            unk = by_store[by_store["store_name"].astype(str).str.contains("требуется mapping", na=False)]
            if not unk.empty:
                unknown = (
                    unk.groupby(["store_prefix", "store_name"], as_index=False)
                    .agg(documents=("document_count", "sum"))
                    .to_dict(orient="records")
                )
                warnings.append(f"Неизвестные префиксы магазинов: {len(unknown)}")

        def _df(df: pd.DataFrame):
            if df is None or df.empty:
                return []
            out = df.copy()
            for c in out.columns:
                if out[c].dtype == object:
                    out[c] = out[c].astype(str)
            return out.to_dict(orient="records")

        tables = {
            "receipts_daily": _df(receipts),
            "sales_by_store": _df(by_store),
            "payments_by_category": _df(pay_cat),
            "cogs_daily": _df(cogs),
            "stock_by_warehouse": _df(stock),
            "inventories_daily": _df(inventories),
            "writeoffs_daily": _df(writeoffs),
            "supplier_returns_daily": _df(supplier_returns),
            "transfers_daily": _df(transfers),
            "unknown_store_prefixes": unknown,
            "payment_scope_label": "Оплаты по закрытиям смен",
        }

        snap = AnalyticsSnapshot(
            ok=True,
            message="analytics ok",
            loaded_at=loaded_at,
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
            store_filter=store_name,
            sql_status={"ok": True, "database": st.database, "server": st.server},
            metrics=metrics,
            tables=tables,
            warnings=warnings,
        )
        _LAST_OK_AT = loaded_at
        _CACHE[key] = (now_ts, snap)
        return snap
    except Exception as exc:  # noqa: BLE001
        err = redact_error(exc)
        return AnalyticsSnapshot(
            ok=False,
            message="Ошибка analytics SQL",
            loaded_at=loaded_at,
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
            store_filter=store_name,
            sql_status={"ok": False, "error": err},
            metrics=[_mv("error", "Ошибка", status="no_confirmed_data", warning=err)],
            warnings=[err],
        )


def last_success_at() -> Optional[str]:
    return _LAST_OK_AT
