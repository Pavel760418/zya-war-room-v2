"""SQL data service: physical 1C tables → War Room ``raw`` dict.

Uses ``app.ingestion.sql_extract`` (physical names from
``StrukturaKhraneniiaBazyDannykh.xlsx``) and SELECT-only pymssql access.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd

from app.core.settings import get_app_settings, missing_database_secret_keys, redact_error
from app.ingestion.metadata_catalog import known_war_room_physicals
from app.ingestion.schema import META_SHEET, SCHEMA
from app.ingestion.sql_extract import CATALOG_QUERIES, PHYSICAL, get_query
from app.repositories.sql_database import SqlDatabase, SqlStatus


@dataclass
class SqlLoadResult:
    raw: dict
    status: SqlStatus
    warnings: list[str] = field(default_factory=list)
    mapping_complete: bool = False
    last_success_at: Optional[str] = None
    confidence_notes: list[str] = field(default_factory=list)


class SqlDataService:
    def __init__(self, db: Optional[SqlDatabase] = None):
        settings = get_app_settings()
        timeout = max(settings.sql_connect_timeout, 60)
        self.db = db if db is not None else SqlDatabase.from_env(connect_timeout=timeout)

    def status(self) -> SqlStatus:
        if self.db is None:
            missing = missing_database_secret_keys() or ("DATABASE_URL",)
            return SqlStatus(
                ok=False,
                message=(
                    "DATABASE_URL не задан. Укажите Secrets в Streamlit Cloud "
                    "или переменные окружения (см. .streamlit/secrets.toml.example)."
                ),
                error="missing_database_url",
                engine=",".join(missing),
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
            missing = missing_database_secret_keys()
            raw["meta"] = pd.DataFrame(
                {
                    META_SHEET.key_col: [
                        "Название сети",
                        "Валюта",
                        "Источник",
                        "SQL статус",
                        "SQL ошибка",
                        "Не заданы secrets",
                    ],
                    META_SHEET.value_col: [
                        "Зеленое Яблоко",
                        "RUB",
                        "sql",
                        "недоступен",
                        status.error or status.message,
                        ", ".join(missing) if missing else "—",
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
        return self._load_from_catalog(status, now)

    def _window_params(self) -> dict[str, date]:
        end = date.today() + timedelta(days=1)
        start = date.today() - timedelta(days=31)
        month_start = date.today().replace(day=1)
        return {
            "date_from": start,
            "date_to": end,
            "week_from": date.today() - timedelta(days=7),
            "week_to": end,
            "month_from": month_start,
            "month_to": end,
        }

    def _load_from_catalog(self, status: SqlStatus, now: str) -> SqlLoadResult:
        assert self.db is not None
        raw = self.empty_raw()
        warnings: list[str] = []
        notes: list[str] = [
            f"Физический маппинг из каталога: Продажи→{PHYSICAL.get('РегистрНакопления.Продажи')}",
            f"Остатки→{PHYSICAL.get('ТоварыНаСкладах')}, Списания→{PHYSICAL.get('Документ.СписаниеТоваров')}",
            f"Инвентаризация→{PHYSICAL.get('Документ.Инвентаризация')}, Магазины→{PHYSICAL.get('Справочник.Магазины')}",
        ]
        params = self._window_params()

        # Primary path: catalog physical queries for each schema sheet
        sheet_keys = [
            ("продажи_день", "sales_day"),
            ("продажи_неделя", "sales_week"),
            ("продажи_месяц", "sales_month"),
            ("доступность_неделя", "availability_week"),
            ("пенетрация_неделя", "penetration_week"),
            ("списания_неделя", "writeoff_week"),
            ("потери_месяц", "losses_month"),
            ("расходы_месяц", "expenses_month"),
            ("прибыль_месяц", "profit_month"),
            ("сп_месяц", "sp_month"),
            ("остатки_месяц", "stock_month"),
        ]

        ok_sheets = 0
        for catalog_key, schema_key in sheet_keys:
            try:
                sql, bind = get_query(catalog_key, params=params, pymssql_style=True)
                # Drop None binds — pymssql dislikes missing keys in some versions
                clean = {k: v for k, v in bind.items() if v is not None}
                df = self.db.fetch_df(sql, params=clean)
                spec = SCHEMA.get(schema_key)
                if spec is not None:
                    for c in spec.columns:
                        if c.canonical not in df.columns:
                            df[c.canonical] = c.default
                raw[schema_key] = df
                ok_sheets += 1
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{schema_key}: {redact_error(exc)}")

        # Shape sales sheets for MetricsService (aggregate to latest day / week / month labels)
        raw = self._normalize_sales_sheets(raw)

        mapping_complete = ok_sheets >= 3 and not raw["sales_day"].empty
        if raw["sales_day"].empty and ok_sheets:
            warnings.append("Продажи за окно пусты — проверьте период и фильтры магазинов.")

        phys = known_war_room_physicals()
        raw["meta"] = pd.DataFrame(
            {
                META_SHEET.key_col: [
                    "Название сети",
                    "Валюта",
                    "Источник",
                    "SQL статус",
                    "Текущий день",
                    "Режим SQL",
                    "Продажи",
                    "Списания",
                    "Инвентаризация",
                    "Остатки",
                ],
                META_SHEET.value_col: [
                    "Зеленое Яблоко",
                    "RUB",
                    "sql",
                    "ok" if mapping_complete else "partial",
                    date.today().isoformat(),
                    "metadata_catalog physical",
                    phys.get("РегистрНакопления.Продажи", ""),
                    phys.get("Документ.СписаниеТоваров", ""),
                    phys.get("Документ.Инвентаризация", ""),
                    phys.get("ТоварыНаСкладах", ""),
                ],
            }
        )
        return SqlLoadResult(
            raw=raw,
            status=status,
            warnings=warnings,
            mapping_complete=mapping_complete,
            last_success_at=self.db.last_success_iso or now,
            confidence_notes=notes,
        )

    def _normalize_sales_sheets(self, raw: dict) -> dict:
        """Collapse multi-day extract into MetricsService-friendly day/week/month frames."""
        day = raw.get("sales_day")
        if not isinstance(day, pd.DataFrame) or day.empty or "Дата" not in day.columns:
            return raw
        day = day.copy()
        day["Дата"] = pd.to_datetime(day["Дата"], errors="coerce")
        latest = day["Дата"].max()
        if pd.isna(latest):
            return raw
        day_latest = day.loc[day["Дата"] == latest].copy()
        week_cut = latest - pd.Timedelta(days=6)
        week = day.loc[day["Дата"] >= week_cut].copy()
        month_mask = (day["Дата"].dt.year == latest.year) & (day["Дата"].dt.month == latest.month)
        month = day.loc[month_mask].copy()

        def _agg(df: pd.DataFrame, period: str) -> pd.DataFrame:
            if df.empty:
                return df
            g = (
                df.groupby("Магазин", as_index=False)
                .agg(
                    **{
                        "Выручка факт": ("Выручка факт", "sum"),
                        "Выручка план": ("Выручка план", "sum"),
                        "Количество чеков": ("Количество чеков", "sum"),
                    }
                )
            )
            if period == "date":
                g["Дата"] = latest.strftime("%Y-%m-%d")
            elif period == "week":
                g["Неделя"] = "текущая (7д, SQL)"
            else:
                g["Месяц"] = latest.strftime("%Y-%m")
            return g

        # Prefer dedicated week/month extracts when non-empty; else aggregate from day.
        if raw.get("sales_week") is None or getattr(raw["sales_week"], "empty", True):
            raw["sales_week"] = _agg(week, "week")
        if raw.get("sales_month") is None or getattr(raw["sales_month"], "empty", True):
            raw["sales_month"] = _agg(month, "month")
        raw["sales_day"] = _agg(day_latest, "date")
        return raw


def _safe_ident(name: str) -> bool:
    if not name or len(name) > 128:
        return False
    return all(ch.isalnum() or ch in ("_",) for ch in name)
