"""SQL data service: physical 1C tables → War Room ``raw`` dict.

Uses ``app.ingestion.sql_extract`` (physical names from
``StrukturaKhraneniiaBazyDannykh.xlsx``) and SELECT-only pymssql access.

Обычный пользовательский режим читает локальный SQLite-кэш
(``WARROOM_DATA_SOURCE=cache``, по умолчанию). Прямой MSSQL — только
для sync-скрипта и диагностики (``WARROOM_DATA_SOURCE=sql``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
import math
import os

import pandas as pd

from app.core.settings import get_app_settings, get_gateway_settings, missing_database_secret_keys, redact_error
from app.ingestion.metadata_catalog import known_war_room_physicals
from app.ingestion.schema import META_SHEET, SCHEMA
from app.ingestion.sql_extract import CATALOG_QUERIES, PHYSICAL, get_query
from app.repositories.sql_database import SqlDatabase, SqlStatus
from app.services.gateway_client import GatewaySettings as ClientGatewaySettings
from app.services.gateway_client import fetch_gateway_raw
from app.services.local_cache_store import LocalCacheStore


@dataclass
class SqlLoadResult:
    raw: dict
    status: SqlStatus
    warnings: list[str] = field(default_factory=list)
    mapping_complete: bool = False
    last_success_at: Optional[str] = None
    confidence_notes: list[str] = field(default_factory=list)


def _is_streamlit_cloud() -> bool:
    if (os.environ.get("STREAMLIT_RUNTIME_ENV") or "").strip().lower() == "cloud":
        return True
    if (os.environ.get("STREAMLIT_SHARING_MODE") or "").strip().lower() in {"streamlit", "cloud"}:
        return True
    return Path("/mount/src").is_dir()


def _resolve_source_mode() -> str:
    """LAN: ``WARROOM_DATA_SOURCE=cache`` из systemd. Cloud: sqlite snapshot в data/cloud_snapshot."""
    raw = (os.environ.get("WARROOM_DATA_SOURCE") or "").strip().lower()
    # Streamlit Cloud often injects secrets into env; public :3000 gateway is Metabase HTML.
    if _is_streamlit_cloud():
        try:
            if LocalCacheStore().exists():
                return "cache"
        except OSError:
            pass
    if raw:
        return raw
    try:
        if LocalCacheStore().exists():
            return "cache"
    except OSError:
        pass
    try:
        from app.core.settings import _secret_get

        raw = (_secret_get("WARROOM_DATA_SOURCE") or _secret_get("DATA_SOURCE_MODE") or "").strip().lower()
    except Exception:  # noqa: BLE001
        raw = ""
    if raw:
        return raw
    return "sql"


class SqlDataService:
    def __init__(self, db: Optional[SqlDatabase] = None, *, use_env_db: bool = True):
        settings = get_app_settings()
        timeout = max(settings.sql_connect_timeout, 60)
        if db is not None:
            self.db = db
        elif use_env_db:
            self.db = SqlDatabase.from_env(connect_timeout=timeout)
        else:
            self.db = None
        self._source_mode = _resolve_source_mode()

    @property
    def uses_live_sql(self) -> bool:
        return self._source_mode in {"sql", "live", "mssql", "1c"}

    def load(self) -> SqlLoadResult:
        # Пользовательский режим: только локальный кэш (без обращений к 1С).
        if not self.uses_live_sql:
            try:
                cached = self._load_from_local_cache()
            except OSError as exc:
                # Streamlit Cloud: старый абсолютный путь /home/andr → Permission denied
                if get_gateway_settings() is not None or self.db is not None:
                    return self._load_live()
                return SqlLoadResult(
                    raw=self.empty_raw(),
                    status=SqlStatus(
                        ok=False,
                        message="Кэш недоступен на этой машине. Задайте WARROOM_GATEWAY_* или DATABASE_URL.",
                        server="local_cache",
                        engine="sqlite",
                        error=redact_error(exc),
                    ),
                    warnings=["cache_os_error"],
                    mapping_complete=False,
                    last_success_at=None,
                )
            if cached is not None:
                return cached
            # Без кэша: на Cloud есть gateway — не блокируем UI.
            allow_fallback = (os.environ.get("WARROOM_ALLOW_LIVE_FALLBACK") or "").strip().lower() in {
                "1",
                "true",
                "yes",
            }
            if allow_fallback or get_gateway_settings() is not None:
                return self._load_live()
            store = LocalCacheStore()
            return SqlLoadResult(
                raw=self.empty_raw(),
                status=SqlStatus(
                    ok=False,
                    message="Локальный кэш ещё не создан. Дождитесь синхронизации или запустите sync_from_1c.py.",
                    server="local_cache",
                    database=str(store.path),
                    engine="sqlite",
                    error="cache_missing",
                ),
                warnings=["cache_missing"],
                mapping_complete=False,
                last_success_at=None,
            )
        return self._load_live()

    def _load_from_local_cache(self) -> Optional[SqlLoadResult]:
        store = LocalCacheStore()
        raw = store.load_raw()
        if not raw:
            return None
        synced = store.last_success_at() or raw.get("_cache_synced_at") or "—"
        raw["_data_source"] = "local_cache"
        raw["_cache_synced_at"] = synced
        # Re-normalize PBI grains so calendar/report-day logic stays current after code updates.
        if raw.get("_pbi_parity") or raw.get("_metric_profile") == "pbi":
            from app.services.pbi_parity_loader import (
                build_pbi_losses_day,
                build_pbi_penetration_day,
                build_pbi_sales_day,
                build_pbi_sp_day,
            )

            if isinstance(raw.get("pbi_rto_day"), pd.DataFrame) and not raw["pbi_rto_day"].empty:
                raw["sales_day"] = build_pbi_sales_day(
                    raw.get("pbi_rto_day", pd.DataFrame()),
                    raw.get("pbi_traffic_pen_day", pd.DataFrame()),
                    clip_to_traffic=False,
                )
            elif isinstance(raw.get("_sales_day_grain"), pd.DataFrame) and not raw["_sales_day_grain"].empty:
                raw["sales_day"] = raw["_sales_day_grain"].copy()
            if isinstance(raw.get("pbi_traffic_pen_day"), pd.DataFrame):
                raw["penetration_week"] = build_pbi_penetration_day(raw["pbi_traffic_pen_day"])
                raw["sp_month"] = build_pbi_sp_day(raw.get("pbi_rto_day", pd.DataFrame()))
                raw["losses_month"] = build_pbi_losses_day(
                    raw.get("pbi_writeoff_day", pd.DataFrame()),
                    raw.get("pbi_inventory_day", pd.DataFrame()),
                    writeoff_all=raw.get("pbi_writeoff_all_day"),
                    expenses=raw.get("pbi_expense_day"),
                    surplus=raw.get("pbi_surplus_day"),
                )
                wo_src = raw.get("pbi_writeoff_all_day")
                if isinstance(wo_src, pd.DataFrame) and not wo_src.empty:
                    raw["writeoff_week"] = wo_src.copy()
            if isinstance(raw.get("sales_day"), pd.DataFrame) and not raw["sales_day"].empty:
                raw = self._normalize_period_sheets(raw)
        raw.setdefault(
            "_report_note",
            raw.get("_report_note")
            or f"Локальный снимок данных из 1С на {synced}",
        )
        status = SqlStatus(
            ok=True,
            message=f"Локальный кэш (снимок 1С: {synced})",
            server="local_cache",
            database=str(store.path),
            engine="sqlite",
            last_success_at=synced if isinstance(synced, str) else None,
        )
        sales = raw.get("sales_day")
        mapping_ok = isinstance(sales, pd.DataFrame) and not sales.empty
        return SqlLoadResult(
            raw=raw,
            status=status,
            warnings=[],
            mapping_complete=mapping_ok,
            last_success_at=synced if isinstance(synced, str) else None,
            confidence_notes=list(raw.get("_tech_confidence_notes") or [])
            if isinstance(raw.get("_tech_confidence_notes"), list)
            else [
                "Источник UI: локальный SQLite-кэш на сервере приложения",
                f"Последняя синхронизация с 1С: {synced}",
            ],
        )

    def _load_live(self) -> SqlLoadResult:
        # Prefer direct MSSQL on LAN; otherwise use public SQL gateway (Cloud).
        if self.db is None:
            gw = get_gateway_settings()
            if gw is not None:
                return fetch_gateway_raw(
                    ClientGatewaySettings(base_url=gw.url, token=gw.token, timeout_sec=90, retries=4)
                )
            status = self.status()
            now = datetime.now(timezone.utc).isoformat()
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

        status = self.status()
        now = datetime.now(timezone.utc).isoformat()
        if not status.ok:
            # Soft failover to gateway when direct SQL flakes
            gw = get_gateway_settings()
            if gw is not None:
                return fetch_gateway_raw(
                    ClientGatewaySettings(base_url=gw.url, token=gw.token, timeout_sec=90, retries=4)
                )
            raw = self.empty_raw()
            raw["meta"] = pd.DataFrame(
                {
                    META_SHEET.key_col: [
                        "Название сети",
                        "Валюта",
                        "Источник",
                        "SQL статус",
                        "SQL ошибка",
                    ],
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
        result = self._load_from_catalog(status, now)
        if result.raw is not None:
            result.raw["_data_source"] = "live_sql"
        return result

    def status(self) -> SqlStatus:
        if not self.uses_live_sql:
            try:
                store = LocalCacheStore()
                synced = store.last_success_at()
                if store.exists() and synced:
                    return SqlStatus(
                        ok=True,
                        message=f"Локальный кэш актуален (снимок 1С: {synced})",
                        server="local_cache",
                        database=str(store.path),
                        engine="sqlite",
                        last_success_at=synced,
                    )
            except OSError:
                # Fall through to gateway / MSSQL status on Cloud.
                pass
        if self.db is None:
            gw = get_gateway_settings()
            if gw is not None:
                try:
                    from app.services.gateway_client import fetch_gateway_health

                    health = fetch_gateway_health(
                        ClientGatewaySettings(base_url=gw.url, token=gw.token, timeout_sec=20, retries=2)
                    )
                    return SqlStatus(
                        ok=bool(health.get("sql_ok") or health.get("ok")),
                        message="SQL gateway: " + ("ok" if health.get("ok") else "degraded"),
                        server=health.get("server") or gw.url,
                        database=health.get("database"),
                        engine="gateway",
                        error=health.get("error"),
                        last_success_at=health.get("ts"),
                    )
                except Exception as exc:  # noqa: BLE001
                    return SqlStatus(
                        ok=False,
                        message="SQL gateway недоступен",
                        server=gw.url,
                        error=redact_error(exc),
                        engine="gateway",
                    )
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

    def _window_params(self) -> dict[str, date]:
        end = date.today() + timedelta(days=1)
        lookback = int(os.environ.get("WARROOM_LOOKBACK_DAYS", "31"))
        start = date.today() - timedelta(days=lookback)
        # LFL/г/г: RTO с 01.01.2025 (или override), трафик остаётся в коротком окне
        rto_from_env = (os.environ.get("WARROOM_RTO_DATE_FROM") or "2025-01-01").strip()
        try:
            rto_from = date.fromisoformat(rto_from_env)
        except ValueError:
            rto_from = date(2025, 1, 1)
        month_start = date.today().replace(day=1)
        return {
            "date_from": start,
            "date_to": end,
            "rto_date_from": rto_from,
            # ТЗ: остаток на конец предыдущего дня (week_to exclusive = сегодня 00:00).
            # СП: продажи за окно lookback; UI затем пересчитывает по выбранному периоду.
            "week_from": start,
            "week_to": date.today(),
            "month_from": month_start,
            "month_to": end,
        }

    def _load_from_catalog(self, status: SqlStatus, now: str) -> SqlLoadResult:
        assert self.db is not None
        raw = self.empty_raw()
        warnings: list[str] = []
        # Бизнес-формулировки для UI; тех. имена — только в debug-логе (_tech_confidence_notes).
        notes: list[str] = [
            "Чеки и выручка — документ закрытия смены / снятые кассы [проверено]",
            "Доля СП — продажи по папке собственного производства",
            "Списания — документ списания товаров по статьям доходов и расходов",
            "Недостачи — инвентаризация (отрицательная сумма недостачи)",
            "Остатки — снимок складских итогов на отчётную дату (не поток движений за 120 дней)",
            "Паскуччи — оценка по составу смены (приближённо, методология уточняется)",
        ]
        raw["_tech_confidence_notes"] = [
            f"Чеки/выручка → {PHYSICAL.get('Документ.ЗакрытиеСмены', '_Document119')}"
            f"+{PHYSICAL.get('Документ.ЗакрытиеСмены.СнятыеКассы', '_Document119_VT2313')} [VERIFIED]",
            f"Остатки → {PHYSICAL.get('РегистрНакопления.ОстаткиТоваровКомпании.Остатки', '_AccumRgT6616')} [VERIFIED]",
            "M09 Паскуччи: proxy NEEDS_REVIEW (нет построчного ID чека)",
        ]
        params = self._window_params()

        # Primary path: catalog physical queries for each schema sheet
        sheet_keys = [
            ("продажи_день", "sales_day"),
            ("продажи_неделя", "sales_week"),
            ("продажи_месяц", "sales_month"),
            ("доступность_неделя", "availability_week"),
            ("доступность_sku", "availability_sku"),
            ("доступность_сп_день", "availability_sp_day"),
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

        # PBI-parity overlay (default): AccumRg6691 + ucs.CASHSAIL + партии
        from app.services.pbi_parity_loader import (
            apply_pbi_parity_to_raw,
            fetch_pbi_parity_frames,
            metric_profile,
        )

        profile = metric_profile()
        if profile in {"pbi", "pbi_parity", "tkpt"}:
            try:
                frames = fetch_pbi_parity_frames(
                    self.db,
                    date_from=params["date_from"],
                    date_to=params["date_to"],
                    rto_date_from=params.get("rto_date_from"),
                )
                raw = apply_pbi_parity_to_raw(raw, frames)
                notes = [
                    "PBI-parity Обзор: выручка = _AccumRg6691._Fld6707 (сеть TREATAS)",
                    "Трафик/пенетрация = ucs.CASHSAIL (distinct чек+касса+день)",
                    "Списания (1РТО С) = 2 статьи; Расходы = Обед/Представительские; Недостачи = Инвентаризация",
                    "LFL/г/г = DIVIDE(РТО, DATEADD−1 YEAR)−1 (мера LFL РТО)",
                    "Доля СП % = РТО СП / РТО (папка 00107646 / «Производство Зеленого яблока»)",
                    "Паскуччи = марка _Reference93 через _Fld808RRef (NEEDS_REVIEW в модели)",
                ]
                raw["_tech_confidence_notes"] = list(notes)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"pbi_parity: {redact_error(exc)}")
                raw["_metric_profile"] = "legacy"
                raw["_pbi_parity"] = False

        # Shape sales + losses + penetration to aligned day/week/month windows
        raw = self._normalize_period_sheets(raw)

        mapping_complete = ok_sheets >= 3 and not raw["sales_day"].empty
        if raw.get("_pbi_parity") and isinstance(raw.get("sales_day"), pd.DataFrame):
            mapping_complete = not raw["sales_day"].empty
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
                    "Профиль метрик",
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
                    str(raw.get("_metric_profile") or profile),
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

    def _normalize_period_sheets(self, raw: dict) -> dict:
        """Align day/week/month from daily grain — no ISO-week truncation / iloc[0] loss.

        Week = last 7 calendar days ending at the selected report day (inclusive).
        Month = calendar month of that day.
        Network = sum of stores (enforced later by MetricsService summing rows).
        """
        day = raw.get("sales_day")
        if not isinstance(day, pd.DataFrame) or day.empty or "Дата" not in day.columns:
            return raw
        day = day.copy()
        day["Дата"] = pd.to_datetime(day["Дата"], errors="coerce")
        day = day.dropna(subset=["Дата"])
        if day.empty:
            return raw

        stores_per_day = day.groupby("Дата")["Магазин"].nunique()
        max_stores = int(stores_per_day.max()) if len(stores_per_day) else 0
        from app.services.pbi_parity_loader import calendar_mode

        profile = str(raw.get("_metric_profile") or "").strip().lower()
        if profile in {"pbi", "pbi_parity", "tkpt"}:
            cal = "pbi"
        elif profile in {"legacy", "warroom"}:
            cal = "legacy"
        else:
            cal = calendar_mode()
        anchor = raw.get("_anchor_date")
        if anchor:
            latest = pd.to_datetime(anchor, errors="coerce")
            if pd.isna(latest):
                latest = day["Дата"].max()
            else:
                latest = latest.normalize()
                # clamp to available data
                available = set(day["Дата"].dt.normalize().unique())
                if latest not in available:
                    # nearest previous day with data
                    earlier = sorted(d for d in available if d <= latest)
                    latest = earlier[-1] if earlier else day["Дата"].max()
            threshold = max_stores or 1
            eligible = stores_per_day
        elif cal in {"pbi", "calendar"} or raw.get("_metric_profile") == "pbi":
            # PBI: календарный день без порога 80%. Для дефолта UI берём последний день
            # с максимальным охватом магазинов (обычно вчера), а не «сегодня с 2 кассами».
            peak = stores_per_day[stores_per_day == max_stores] if max_stores else stores_per_day
            latest = peak.index.max() if len(peak) else day["Дата"].max()
            threshold = max_stores or 1
            eligible = peak if len(peak) else stores_per_day
        else:
            # Legacy: ≥80% магазинов от исторического максимума в окне.
            threshold = max(1, int(math.ceil(max_stores * 0.8))) if max_stores else 1
            eligible = stores_per_day[stores_per_day >= threshold]
            latest = eligible.index.max() if len(eligible) else day["Дата"].max()
        if pd.isna(latest):
            return raw

        stores_on_day = int(stores_per_day.get(latest, 0) or 0)
        incomplete = stores_on_day < max_stores
        missing_n = max(0, max_stores - stores_on_day)

        def _last_complete(start: pd.Timestamp, end: pd.Timestamp) -> pd.Timestamp:
            """Последний день окна с максимальным охватом магазинов (как полный день PBI)."""
            mask = (stores_per_day.index >= start) & (stores_per_day.index <= end)
            w = stores_per_day.loc[mask]
            if w.empty:
                return end
            peak = int(w.max())
            complete = w[w >= max(peak, 1)]
            return pd.Timestamp(complete.index.max()) if len(complete) else end

        week_cut = latest - pd.Timedelta(days=6)
        week_end = latest
        month_start = pd.Timestamp(latest).replace(day=1)
        month_end = latest
        if cal in {"pbi", "calendar"} or raw.get("_metric_profile") == "pbi":
            # Неделя PBI: полный календарный понедельник–воскресенье, обрезка по последнему полному дню.
            week_cut = latest - pd.Timedelta(days=int(latest.dayofweek))
            week_end = _last_complete(week_cut, week_cut + pd.Timedelta(days=6))
            # Месяц PBI: весь календарный месяц выбранной даты, не MTD до якоря.
            month_end = _last_complete(
                month_start,
                (month_start + pd.offsets.MonthEnd(0)).normalize(),
            )
        day_slice = day.loc[day["Дата"] == latest].copy()
        week_slice = day.loc[(day["Дата"] >= week_cut) & (day["Дата"] <= week_end)].copy()
        month_slice = day.loc[(day["Дата"] >= month_start) & (day["Дата"] <= month_end)].copy()

        custom_from = raw.get("_custom_from")
        custom_to = raw.get("_custom_to")
        if custom_from and custom_to:
            c0 = pd.to_datetime(custom_from, errors="coerce")
            c1 = pd.to_datetime(custom_to, errors="coerce")
            if not pd.isna(c0) and not pd.isna(c1):
                c0, c1 = c0.normalize(), c1.normalize()
                if c0 > c1:
                    c0, c1 = c1, c0
                ranged = day.loc[(day["Дата"] >= c0) & (day["Дата"] <= c1)].copy()
                day_slice = ranged
                week_slice = ranged
                month_slice = ranged
                week_cut, week_end = c0, c1
                month_start, month_end = c0, c1
                if not ranged.empty:
                    latest = ranged["Дата"].max()

        # Магазины, бывшие в «полном» дне окна, но отсутствующие в отчётном дне
        peak_days = stores_per_day[stores_per_day == max_stores].index
        peak_day = peak_days.max() if len(peak_days) else latest
        peak_stores = set(day.loc[day["Дата"] == peak_day, "Магазин"].astype(str))
        latest_stores = set(day_slice["Магазин"].astype(str))
        missing_stores = sorted(peak_stores - latest_stores)
        missing_details: list[str] = []
        for store_name in missing_stores:
            last_dt = day.loc[day["Магазин"].astype(str) == store_name, "Дата"].max()
            if pd.isna(last_dt):
                missing_details.append(store_name)
            else:
                missing_details.append(
                    f"{store_name} (последнее закрытие: {pd.Timestamp(last_dt).strftime('%d.%m')})"
                )
        raw["_report_missing_stores"] = missing_stores
        raw["_report_missing_details"] = missing_details

        def _agg_sales(df: pd.DataFrame, period: str) -> pd.DataFrame:
            if df.empty:
                return df
            g = df.groupby("Магазин", as_index=False).agg(
                **{
                    "Выручка факт": ("Выручка факт", "sum"),
                    "Выручка план": ("Выручка план", "sum"),
                    "Количество чеков": ("Количество чеков", "sum"),
                }
            )
            if period == "date":
                g["Дата"] = latest.strftime("%Y-%m-%d")
            elif period == "week":
                g["Неделя"] = f"{week_cut.strftime('%Y-%m-%d')}…{week_end.strftime('%Y-%m-%d')}"
            else:
                g["Месяц"] = month_start.strftime("%Y-%m")
            return g

        # Always rebuild from day grain (ignore ISO-week SQL extract to keep day⊂week⊂month)
        raw["sales_day"] = _agg_sales(day_slice, "date")
        raw["sales_week"] = _agg_sales(week_slice, "week")
        raw["sales_month"] = _agg_sales(month_slice, "month")
        raw["_sales_day_grain"] = day  # for tests / diagnostics
        raw["_report_day"] = latest.strftime("%Y-%m-%d")
        raw["_week_from"] = week_cut.strftime("%Y-%m-%d")
        raw["_week_to"] = week_end.strftime("%Y-%m-%d")
        raw["_month_from"] = month_start.strftime("%Y-%m-%d")
        raw["_month_to"] = month_end.strftime("%Y-%m-%d")
        raw["_report_stores"] = stores_on_day
        raw["_report_stores_max"] = max_stores
        raw["_report_incomplete"] = incomplete
        day_label = latest.strftime("%d.%m.%Y")
        if incomplete and missing_details:
            raw["_report_note"] = (
                f"Данные за {day_label}: неполные, выгружено {stores_on_day} из {max_stores} магазинов. "
                f"Нет данных: {'; '.join(missing_details)}"
            )
        elif incomplete:
            raw["_report_note"] = (
                f"Данные за {day_label}: неполные, выгружено {stores_on_day} из {max_stores} магазинов."
            )
        else:
            raw["_report_note"] = (
                f"Отчётный день {day_label}: данные по всем {stores_on_day} магазинам. "
                f"Месяц: {month_start.strftime('%d.%m')}–{month_end.strftime('%d.%m.%Y')}."
            )
        raw["_tech_report_note"] = (
            f"PBI-parity: календарный день {day_label}, формулы ТКПТ_обзор / ТКПТ_пенетрация / ТКПТ_потери."
            if raw.get("_metric_profile") == "pbi"
            else ""
        )
        # План / LY: флаги для UI (без синтетических констант).
        plan_sum = 0.0
        for key in ("sales_day", "sales_week", "sales_month"):
            df = raw.get(key)
            if isinstance(df, pd.DataFrame) and not df.empty and "Выручка план" in df.columns:
                plan_sum += float(pd.to_numeric(df["Выручка план"], errors="coerce").fillna(0).sum())
        raw["_plan_available"] = plan_sum > 0
        years = set(int(y) for y in day["Дата"].dt.year.dropna().unique().tolist())
        rto = raw.get("pbi_rto_day")
        if isinstance(rto, pd.DataFrame) and not rto.empty and "Дата" in rto.columns:
            years |= set(int(y) for y in pd.to_datetime(rto["Дата"], errors="coerce").dt.year.dropna().unique().tolist())
        raw["_ly_available"] = len(years) >= 2

        raw = self._slice_aux_by_windows(
            raw,
            latest=latest,
            week_cut=week_cut,
            week_end=week_end,
            month_start=month_start,
            month_end=month_end,
            day_start=day_slice["Дата"].min() if not day_slice.empty else latest,
            day_end=day_slice["Дата"].max() if not day_slice.empty else latest,
        )
        raw = self._rebuild_sp_availability(raw, start=month_start, end=month_end)
        return raw

    def _rebuild_sp_availability(self, raw: dict, *, start: pd.Timestamp, end: pd.Timestamp) -> dict:
        """СП-доступность = SKU корзины с продажами в [start, end]; ТЗ не трогаем (остаток)."""
        sold = raw.get("availability_sp_day")
        if not isinstance(sold, pd.DataFrame) or sold.empty:
            return raw
        df = sold.copy()
        df["Дата"] = pd.to_datetime(df["Дата"], errors="coerce")
        df["Магазин"] = df["Магазин"].astype(str)
        df["Артикул"] = df["Артикул"].astype(str)
        part = df[(df["Дата"] >= start) & (df["Дата"] <= end)].copy()
        avail = (
            part.groupby("Магазин")["Артикул"].nunique()
            if not part.empty
            else pd.Series(dtype="int64")
        )
        amt = (
            part.groupby(["Магазин", "Артикул"])["Продажи"].sum()
            if not part.empty and "Продажи" in part.columns
            else None
        )
        sold_pairs = set(zip(part["Магазин"], part["Артикул"])) if not part.empty else set()

        sku = raw.get("availability_sku")
        totals: dict[str, int] = {}
        default_total = 0
        if isinstance(sku, pd.DataFrame) and not sku.empty and "Корзина" in sku.columns:
            sku = sku.copy()
            sp_mask = sku["Корзина"].astype(str) == "СП"
            if "Артикул" in sku.columns:
                default_total = int(sku.loc[sp_mask, "Артикул"].nunique())
                totals = sku.loc[sp_mask].groupby(sku.loc[sp_mask, "Магазин"].astype(str))["Артикул"].nunique().to_dict()
            if "В наличии" in sku.columns:
                flags = []
                sales_col = []
                for rec in sku.to_dict(orient="records"):
                    basket = str(rec.get("Корзина") or "")
                    store = str(rec.get("Магазин") or "")
                    art = str(rec.get("Артикул") or "")
                    if basket == "СП":
                        key = (store, art)
                        sold_amt = float(amt.get(key, 0) or 0) if amt is not None else (1.0 if key in sold_pairs else 0.0)
                        flags.append(1 if (key in sold_pairs or sold_amt > 0.001) else 0)
                        sales_col.append(round(sold_amt, 2))
                    else:
                        flags.append(int(rec.get("В наличии") or 0))
                        sales_col.append(float(rec.get("Продажи") or 0))
                sku["В наличии"] = flags
                sku["Продажи"] = sales_col
            raw["availability_sku"] = sku

        week = raw.get("availability_week")
        if isinstance(week, pd.DataFrame) and not week.empty and "Магазин" in week.columns:
            week = week.copy()
            av_col = "Топ СП доступно позиций"
            tot_col = "Топ СП всего позиций"
            if av_col not in week.columns:
                week[av_col] = 0
            if tot_col not in week.columns:
                week[tot_col] = default_total
            for i, rec in week.iterrows():
                store = str(rec.get("Магазин") or "")
                week.at[i, av_col] = int(avail.get(store, 0) or 0)
                cur_tot = rec.get(tot_col)
                if pd.isna(cur_tot) or float(cur_tot or 0) <= 0:
                    week.at[i, tot_col] = int(totals.get(store, default_total) or default_total)
            raw["availability_week"] = week
        return raw

    def _slice_aux_by_windows(
        self,
        raw: dict,
        *,
        latest: pd.Timestamp,
        week_cut: pd.Timestamp,
        week_end: pd.Timestamp,
        month_start: pd.Timestamp,
        month_end: pd.Timestamp,
        day_start: Optional[pd.Timestamp] = None,
        day_end: Optional[pd.Timestamp] = None,
    ) -> dict:
        """Filter losses / writeoffs / penetration to the same day/week/month windows as sales."""
        d0 = day_start if day_start is not None else latest
        d1 = day_end if day_end is not None else latest

        def _prep(df: pd.DataFrame) -> pd.DataFrame:
            if df is None or getattr(df, "empty", True):
                return pd.DataFrame()
            out = df.copy()
            if "Дата" not in out.columns:
                return out
            out["Дата"] = pd.to_datetime(out["Дата"], errors="coerce")
            return out.dropna(subset=["Дата"])

        def _in_week(s: pd.Series) -> pd.Series:
            return (s >= week_cut) & (s <= week_end)

        def _in_month(s: pd.Series) -> pd.Series:
            return (s >= month_start) & (s <= month_end)

        losses = _prep(raw.get("losses_month"))
        if not losses.empty and "Дата" in losses.columns:
            raw["losses_day"] = losses.loc[(losses["Дата"] >= d0) & (losses["Дата"] <= d1)]
            raw["losses_week"] = losses.loc[_in_week(losses["Дата"])]
            raw["losses_month"] = losses.loc[_in_month(losses["Дата"])]
        else:
            raw.setdefault("losses_day", pd.DataFrame())
            raw.setdefault("losses_week", pd.DataFrame())

        wo = _prep(raw.get("writeoff_week"))
        if not wo.empty and "Дата" in wo.columns:
            raw["writeoff_day"] = wo.loc[(wo["Дата"] >= d0) & (wo["Дата"] <= d1)]
            raw["writeoff_week"] = wo.loc[_in_week(wo["Дата"])]
            raw["writeoff_month"] = wo.loc[_in_month(wo["Дата"])]
        else:
            raw.setdefault("writeoff_day", pd.DataFrame())
            raw.setdefault("writeoff_month", pd.DataFrame())

        pen = _prep(raw.get("penetration_week"))
        if not pen.empty and "Дата" in pen.columns:

            def _agg_pen(df: pd.DataFrame) -> pd.DataFrame:
                if df.empty:
                    return df
                cols = [c for c in ("Чеков всего", "Чеков с СП", "Чеков с Паскуччи") if c in df.columns]
                return df.groupby("Магазин", as_index=False)[cols].sum()

            raw["penetration_day"] = _agg_pen(pen.loc[(pen["Дата"] >= d0) & (pen["Дата"] <= d1)])
            raw["penetration_week"] = _agg_pen(pen.loc[_in_week(pen["Дата"])])
            raw["penetration_month"] = _agg_pen(pen.loc[_in_month(pen["Дата"])])
        else:
            raw.setdefault("penetration_day", pd.DataFrame())
            raw.setdefault("penetration_month", pd.DataFrame())

        sp = _prep(raw.get("sp_month"))
        if not sp.empty and "Дата" in sp.columns and "Выручка СП" in sp.columns:

            def _agg_sp(df: pd.DataFrame) -> pd.DataFrame:
                if df.empty:
                    return df
                cols = [c for c in ("Выручка СП", "Выручка всего") if c in df.columns]
                return df.groupby("Магазин", as_index=False)[cols].sum()

            raw["sp_day"] = _agg_sp(sp.loc[(sp["Дата"] >= d0) & (sp["Дата"] <= d1)])
            raw["sp_week"] = _agg_sp(sp.loc[_in_week(sp["Дата"])])
            raw["sp_month"] = _agg_sp(sp.loc[_in_month(sp["Дата"])])
        else:
            raw.setdefault("sp_day", pd.DataFrame())
            raw.setdefault("sp_week", pd.DataFrame())

        return raw


def _safe_ident(name: str) -> bool:
    if not name or len(name) > 128:
        return False
    return all(ch.isalnum() or ch in ("_",) for ch in name)
