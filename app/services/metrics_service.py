from __future__ import annotations

from typing import Optional

import pandas as pd

from app.core.business_metrics import (
    availability_pct,
    avg_ticket,
    own_production_share_pct,
    penetration_pct,
    plan_completion_pct,
    status_higher_is_better,
    status_lower_is_better,
    status_plan_pct,
)
from app.models.schemas import (
    KPI,
    ActionItem,
    AlertItem,
    DashboardResponse,
    LossItem,
    StoreDrilldown,
    StoreRow,
)

# Ранжирование лидеров/аутсайдеров (не зависит от плана).
RANKING_METRIC_CODE = "losses_pct"
RANKING_METRIC_LABEL = "Списания, % к выручке (среди магазинов с выручкой ≥40% медианы сети)"
RANKING_METRIC_HELP = (
    "В рейтинг входят только магазины с выручкой не ниже 40% медианы сети за период. "
    "Лидеры — наименьшие потери % к выручке; аутсайдеры — наибольшие. "
    "Магазины ниже порога — «Недостаточно данных для рейтинга»."
)
RANK_MEDIAN_FLOOR = 0.40

# Пороги операционного риска (легенда на экране).
# Доступность в текущих данных сети типично ~45–60% — пороги M06/M07 95/90
# оставляют всех в «высоком»; для управленческой дифференциации используем
# калибровку под фактический контур + приоритет потерь %.
LOSS_PCT_GREEN = 0.8
LOSS_PCT_YELLOW = 1.2
SHOP_AV_GREEN = 60.0
SHOP_AV_YELLOW = 45.0
PROD_AV_GREEN = 50.0
PROD_AV_YELLOW = 30.0
SP_SHARE_GREEN = 33.0
SP_SHARE_YELLOW = 30.0

RISK_LEGEND = (
    "Низкий / средний / высокий риск — относительный рейтинг магазинов периода "
    f"по скору: потери % к выручке (главный сигнал), доля СП (порог {SP_SHARE_YELLOW}%), "
    f"доступность ТЗ/СП (ориентиры {SHOP_AV_YELLOW}% / {PROD_AV_YELLOW}%), доля недостач. "
    "План не участвует, пока не задан в 1С."
)

ABBREVIATIONS = {
    "СП": "Собственное производство",
    "ТЗ": "Торговый зал",
    "РТО": "Розничный товарооборот",
    "г/г": "Год к году (к аналогичному периоду прошлого года)",
    "ФРОВ": "Фрукты и овощи",
}

# Канонические уровни риска (единственные допустимые в UI).
RISK_LABEL_BY_STATUS = {"green": "низкий", "yellow": "средний", "red": "высокий"}
RISK_STATUS_BY_LABEL = {"низкий": "green", "средний": "yellow", "высокий": "red"}



class MetricsService:
    def __init__(self, raw: dict, mode: str = "excel"):
        self.raw = raw
        self.mode = mode
        self.meta = (
            raw.get("meta", {})
            if isinstance(raw.get("meta"), dict)
            else {str(r["ключ"]): r["значение"] for _, r in raw["meta"].iterrows()}
        )

    def _status(self, value: float, green: float, yellow: float, reverse: bool = False) -> str:
        if reverse:
            return status_lower_is_better(value, green, yellow)
        return status_higher_is_better(value, green, yellow)

    def _risk(self, status: str) -> str:
        return RISK_LABEL_BY_STATUS.get(status, "средний")

    @staticmethod
    def _plan_is_set(plan_th: Optional[float]) -> bool:
        """План задан только если сумма плана > 0 (0/None = не внесён в 1С)."""
        return plan_th is not None and float(plan_th) > 0

    @staticmethod
    def _losses_pct(revenue_th: float, losses_th: float) -> float:
        return round(float(losses_th or 0) / max(float(revenue_th or 0), 0.01) * 100.0, 2)

    def _ly_available(self) -> bool:
        if bool(self.raw.get("_ly_available")):
            return True
        rto = self.raw.get("pbi_rto_day")
        if not isinstance(rto, pd.DataFrame) or rto.empty or "Дата" not in rto.columns:
            return False
        years = pd.to_datetime(rto["Дата"], errors="coerce").dt.year.dropna().unique()
        return len(set(int(y) for y in years)) >= 2

    def _plan_available(self) -> bool:
        flag = self.raw.get("_plan_available")
        if flag is not None:
            return bool(flag)
        for key in ("sales_day", "sales_week", "sales_month"):
            df = self.raw.get(key)
            if isinstance(df, pd.DataFrame) and not df.empty and "Выручка план" in df.columns:
                if float(pd.to_numeric(df["Выручка план"], errors="coerce").fillna(0).sum()) > 0:
                    return True
        return False

    def _worst_status(self, *statuses: str) -> str:
        order = {"red": 3, "yellow": 2, "blue": 1, "green": 0, "neutral": 1}
        return max(statuses, key=lambda s: order.get(s, 1))

    def _risk_score(
        self, *, losses_pct: float, shop_av: float, prod_av: float, own_share: float, shortage_pct: float = 0.0
    ) -> float:
        """Чем выше скор — тем хуже. Используется для относительного риска в сети."""
        score = float(losses_pct) * 2.0
        score += max(0.0, SP_SHARE_YELLOW - own_share) * 0.15
        score += max(0.0, SHOP_AV_YELLOW - shop_av) * 0.05
        score += max(0.0, PROD_AV_YELLOW - prod_av) * 0.05
        score += float(shortage_pct) * 0.5
        return score

    def _assign_relative_risk(self, rows: list[StoreRow]) -> list[StoreRow]:
        """Дифференциация риска внутри текущего набора магазинов (тертили по скору)."""
        if not rows:
            return rows
        scored = []
        for r in rows:
            loss_pct = self._losses_pct(r.revenue, r.losses or 0)
            short_pct = self._losses_pct(r.revenue, r.inventory_shortage or 0)
            scored.append(
                (
                    self._risk_score(
                        losses_pct=loss_pct,
                        shop_av=r.shop_availability or 0,
                        prod_av=r.production_availability or 0,
                        own_share=r.own_production_share_pct or 0,
                        shortage_pct=short_pct,
                    ),
                    r,
                )
            )
        scored.sort(key=lambda x: x[0], reverse=True)
        n = len(scored)
        hi = max(1, n // 3)
        mid = max(hi, (2 * n) // 3)
        out: list[StoreRow] = []
        for i, (_sc, r) in enumerate(scored):
            if i < hi:
                color, risk = "red", "высокий"
            elif i < mid:
                color, risk = "yellow", "средний"
            else:
                color, risk = "green", "низкий"
            # сохраняем plan-based окраску, если план задан и хуже
            if self._plan_is_set(r.plan) and r.plan_pct is not None:
                plan_color = status_plan_pct(r.plan_pct)
                color = self._worst_status(color, plan_color)
                risk = self._risk(color)
            out.append(
                StoreRow(
                    store=r.store,
                    region=r.region,
                    cluster=r.cluster,
                    format=r.format,
                    revenue=r.revenue,
                    plan=r.plan,
                    py=r.py,
                    plan_pct=r.plan_pct,
                    yoy=r.yoy,
                    avg_ticket=r.avg_ticket,
                    checks=r.checks,
                    own_production_share_pct=r.own_production_share_pct,
                    shop_availability=r.shop_availability,
                    production_availability=r.production_availability,
                    stock_fact=r.stock_fact,
                    stock_plan=r.stock_plan,
                    losses=r.losses,
                    inventory_shortage=r.inventory_shortage,
                    status_color=color,
                    risk_level=risk,
                )
            )
        return out

    def _operational_status(self, *, losses_pct: float, shop_av: float, prod_av: float, own_share: float) -> str:
        """Черновой статус до относительной калибровки по сети."""
        score = self._risk_score(
            losses_pct=losses_pct, shop_av=shop_av, prod_av=prod_av, own_share=own_share
        )
        if score >= 8:
            return "red"
        if score >= 3:
            return "yellow"
        return "green"

    def _demo_rows(self):
        rows = []
        for item in self.raw["stores"]:
            status = status_plan_pct(item["plan_pct"]) if item.get("plan") else self._operational_status(
                losses_pct=self._losses_pct(item["revenue"], item.get("losses") or 0),
                shop_av=item["shop_availability"],
                prod_av=item["production_availability"],
                own_share=item["own_production_share_pct"],
            )
            if item["own_production_share_pct"] < 30:
                status = self._worst_status(status, "red" if item["own_production_share_pct"] < 28 else "yellow")
            rows.append(
                StoreRow(
                    store=item["store"],
                    region=item["region"],
                    cluster=item["cluster"],
                    format=item["format"],
                    revenue=item["revenue"],
                    plan=item["plan"],
                    py=item.get("py"),
                    plan_pct=item["plan_pct"] if item.get("plan") else None,
                    yoy=item.get("yoy"),
                    avg_ticket=item["avg_ticket"],
                    checks=item["checks"],
                    own_production_share_pct=item["own_production_share_pct"],
                    shop_availability=item["shop_availability"],
                    production_availability=item["production_availability"],
                    stock_fact=item["stock_fact"],
                    stock_plan=item["stock_plan"] if item.get("stock_plan") else None,
                    losses=item["losses"],
                    inventory_shortage=item["inventory_shortage"],
                    status_color=status,
                    risk_level=self._risk(status),
                )
            )
        return rows

    def _losses_frame(self, period: str) -> pd.DataFrame:
        key = {"day": "losses_day", "week": "losses_week", "month": "losses_month"}.get(period, "losses_month")
        df = self.raw.get(key)
        if df is None or getattr(df, "empty", True):
            df = self.raw.get("losses_month")
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()

    def _penetration_frame(self, period: str) -> pd.DataFrame:
        key = {"day": "penetration_day", "week": "penetration_week", "month": "penetration_month"}.get(
            period, "penetration_week"
        )
        df = self.raw.get(key)
        if df is None or getattr(df, "empty", True):
            df = self.raw.get("penetration_week")
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()

    def _writeoff_frame(self, period: str) -> pd.DataFrame:
        key = {"day": "writeoff_day", "week": "writeoff_week", "month": "writeoff_month"}.get(period, "writeoff_week")
        df = self.raw.get(key)
        if df is None or getattr(df, "empty", True):
            df = self.raw.get("writeoff_week")
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()

    @staticmethod
    def _row_dict(df: pd.DataFrame, store: str) -> dict:
        if df is None or getattr(df, "empty", True) or "Магазин" not in df.columns:
            return {}
        hit = df[df["Магазин"].astype(str) == store]
        if hit.empty:
            return {}
        num_cols = [c for c in hit.columns if c != "Магазин" and pd.api.types.is_numeric_dtype(hit[c])]
        if len(hit) > 1 and num_cols:
            out = hit.iloc[0].to_dict()
            for c in num_cols:
                out[c] = float(pd.to_numeric(hit[c], errors="coerce").fillna(0).sum())
            return out
        return hit.iloc[0].to_dict()

    def _is_pbi_parity(self) -> bool:
        return (
            str(self.raw.get("_metric_profile") or "").lower() in {"pbi", "pbi_parity", "tkpt"}
            or str(self.raw.get("_money_unit") or "").lower() == "rub"
            or bool(self.raw.get("_pbi_parity"))
        )

    def _money_unit_code(self) -> str:
        return "rub" if self._is_pbi_parity() else "th_rub"

    def _money_scale(self) -> float:
        """PBI cards = рубли; legacy War Room = тысячи рублей во внутренних полях."""
        return 1.0 if self._is_pbi_parity() else 1000.0

    def _inventory_shortage_th(self, losses: pd.DataFrame, store: str) -> float:
        if losses is None or getattr(losses, "empty", True):
            return 0.0
        store_ls = losses[losses["Магазин"].astype(str) == store] if "Магазин" in losses.columns else losses
        if store_ls.empty:
            return 0.0
        scale = self._money_scale()
        if "Вид потерь" in store_ls.columns:
            mask = store_ls["Вид потерь"].astype(str).str.contains(
                r"инвентар|Недостачи \(инвентаризация\)", case=False, na=False, regex=True
            )
            if "Группа" in store_ls.columns:
                mask = mask | (store_ls["Группа"].astype(str) == "Недостачи (инвентаризация)")
            # не путать со статьёй «Списание обнаруженной недостачи ТМЦ»
            mask = mask & ~store_ls["Вид потерь"].astype(str).str.contains(
                "обнаруженной недостачи", case=False, na=False
            )
            if "Сумма" not in store_ls.columns:
                return 0.0
            # Знак как в DAX РТО И (id1+id2); сеть = сумма знаковых, не abs по магазинам.
            return float(pd.to_numeric(store_ls.loc[mask, "Сумма"], errors="coerce").fillna(0).sum()) / scale
        return 0.0

    def _filter_commodity_writeoffs(self, losses: pd.DataFrame) -> pd.DataFrame:
        """Товарные списания = 1РТО С (2 статьи); без расходов и инвентаризации."""
        from app.metrics.loss_articles import COMMODITY_WRITEOFF_ARTICLES, GROUP_COMMODITY, is_commodity_writeoff

        if losses is None or getattr(losses, "empty", True):
            return pd.DataFrame()
        df = losses
        if "Группа" in df.columns:
            g = df[df["Группа"].astype(str) == GROUP_COMMODITY]
            if not g.empty:
                return g
        if "Статья списания" in df.columns:
            m = df["Статья списания"].astype(str).map(is_commodity_writeoff)
            if m.any():
                return df.loc[m]
        if "Вид потерь" in df.columns:
            m = df["Вид потерь"].astype(str).isin(COMMODITY_WRITEOFF_ARTICLES) | df["Вид потерь"].astype(
                str
            ).str.contains("Списания", case=False, na=False)
            # Exclude inventory / expenses labels
            m = m & ~df["Вид потерь"].astype(str).str.contains(
                "инвентар|недостач|Обед|Представительск|Расход", case=False, na=False
            )
            return df.loc[m]
        return pd.DataFrame()

    def _expenses_th(self, losses: pd.DataFrame, store: str) -> float:
        from app.metrics.loss_articles import EXPENSE_ARTICLES, GROUP_EXPENSE, is_expense

        if losses is None or getattr(losses, "empty", True) or "Магазин" not in losses.columns:
            return 0.0
        store_ls = losses[losses["Магазин"].astype(str) == store]
        if store_ls.empty or "Сумма" not in store_ls.columns:
            return 0.0
        if "Группа" in store_ls.columns:
            mask = store_ls["Группа"].astype(str) == GROUP_EXPENSE
        elif "Статья списания" in store_ls.columns:
            mask = store_ls["Статья списания"].astype(str).map(is_expense)
        else:
            mask = store_ls["Вид потерь"].astype(str).isin(EXPENSE_ARTICLES)
        return float(pd.to_numeric(store_ls.loc[mask, "Сумма"], errors="coerce").fillna(0).sum()) / self._money_scale()

    def _surplus_th(self, losses: pd.DataFrame, store: str) -> float:
        if losses is None or getattr(losses, "empty", True) or "Магазин" not in losses.columns:
            return 0.0
        store_ls = losses[losses["Магазин"].astype(str) == store]
        if store_ls.empty or "Сумма" not in store_ls.columns:
            return 0.0
        mask = store_ls["Вид потерь"].astype(str).str.contains("излиш", case=False, na=False)
        if "Группа" in store_ls.columns:
            mask = mask | store_ls["Группа"].astype(str).str.contains("излиш", case=False, na=False)
        return float(pd.to_numeric(store_ls.loc[mask, "Сумма"], errors="coerce").fillna(0).sum()) / self._money_scale()

    def _losses_th(self, losses: pd.DataFrame, store: str) -> float:
        """Списания.

        PBI колонка «Спи» = РТО С (все статьи с RELATED Операция <> BLANK),
        включая Обед/Представительские; без инвентаризации и оприходования излишков.
        """
        if losses is None or getattr(losses, "empty", True) or "Магазин" not in losses.columns:
            return 0.0
        store_ls = losses[losses["Магазин"].astype(str) == store]
        if store_ls.empty or "Сумма" not in store_ls.columns:
            return 0.0
        if self._is_pbi_parity() and "Вид потерь" in store_ls.columns:
            skip = store_ls["Вид потерь"].astype(str).str.contains(
                r"инвентар|Недостачи \(инвентаризация\)|излиш", case=False, na=False, regex=True
            )
            if "Группа" in store_ls.columns:
                skip = skip | store_ls["Группа"].astype(str).str.contains(
                    r"Недостач|излиш", case=False, na=False, regex=True
                )
            store_ls = store_ls.loc[~skip]
            return float(pd.to_numeric(store_ls["Сумма"], errors="coerce").fillna(0).sum()) / self._money_scale()
        if "Вид потерь" in store_ls.columns:
            mask = ~store_ls["Вид потерь"].astype(str).str.contains("инвентар|недостач|излиш", case=False, na=False)
            store_ls = store_ls.loc[mask]
        return float(pd.to_numeric(store_ls["Сумма"], errors="coerce").fillna(0).sum()) / self._money_scale()

    def _custom_bounds(self) -> Optional[tuple[pd.Timestamp, pd.Timestamp]]:
        start = pd.to_datetime(self.raw.get("_custom_from"), errors="coerce")
        end = pd.to_datetime(self.raw.get("_custom_to"), errors="coerce")
        if pd.isna(start) or pd.isna(end):
            return None
        start, end = start.normalize(), end.normalize()
        if start > end:
            start, end = end, start
        return start, end

    def _period_bounds(self, period: str) -> tuple[pd.Timestamp, pd.Timestamp]:
        custom = self._custom_bounds()
        if custom is not None:
            return custom
        report = pd.to_datetime(self.raw.get("_report_day"), errors="coerce")
        if pd.isna(report):
            report = pd.Timestamp.today().normalize()
        report = report.normalize()
        if period == "day":
            return report, report
        if period == "week":
            start = pd.to_datetime(self.raw.get("_week_from"), errors="coerce")
            end = pd.to_datetime(self.raw.get("_week_to"), errors="coerce")
            if pd.isna(start):
                start = report - pd.Timedelta(days=int(report.dayofweek) if self._is_pbi_parity() else 6)
            if pd.isna(end):
                end = report
            return start.normalize(), end.normalize()
        start = pd.to_datetime(self.raw.get("_month_from"), errors="coerce")
        end = pd.to_datetime(self.raw.get("_month_to"), errors="coerce")
        if pd.isna(start):
            start = report.replace(day=1)
        if pd.isna(end):
            end = report
        return start.normalize(), end.normalize()

    def _yoy_pct_for_store(self, store: str, period: str, current_revenue_display: float) -> Optional[float]:
        """LFL РТО: DIVIDE(РТО, DATEADD(Календарь,-1,YEAR))−1 → %."""
        from dateutil.relativedelta import relativedelta

        from app.services.pbi_parity_loader import lfl_rto_pct

        rto = self.raw.get("pbi_rto_day")
        if not isinstance(rto, pd.DataFrame) or rto.empty:
            return None
        start, end = self._period_bounds(period)
        df = rto.copy()
        df["Дата"] = pd.to_datetime(df["Дата"], errors="coerce")
        df = df[df["Магазин"].astype(str) == store]
        if df.empty:
            return None
        ly_start, ly_end = start - relativedelta(years=1), end - relativedelta(years=1)
        cur = float(
            pd.to_numeric(
                df.loc[(df["Дата"].dt.normalize() >= start) & (df["Дата"].dt.normalize() <= end), "Выручка факт"],
                errors="coerce",
            )
            .fillna(0)
            .sum()
        )
        ly = float(
            pd.to_numeric(
                df.loc[(df["Дата"].dt.normalize() >= ly_start) & (df["Дата"].dt.normalize() <= ly_end), "Выручка факт"],
                errors="coerce",
            )
            .fillna(0)
            .sum()
        )
        if cur <= 0 and current_revenue_display:
            cur = float(current_revenue_display) * self._money_scale()
        v = lfl_rto_pct(cur, ly)
        return None if v is None else round(v, 2)

    def _network_lfl_pct(self, period: str) -> Optional[float]:
        """Сеть: DIVIDE(ΣРТО, ΣРТО год назад)−1, как итог матрицы PBI.

        В знаменатель входят только магазины, видимые в текущем периоде
        (закрытый «Апельсин» не раздувает LY).
        """
        from dateutil.relativedelta import relativedelta

        from app.services.pbi_parity_loader import lfl_rto_pct

        rto = self.raw.get("pbi_rto_day")
        if not isinstance(rto, pd.DataFrame) or rto.empty:
            return None
        start, end = self._period_bounds(period)
        df = rto.copy()
        df["Дата"] = pd.to_datetime(df["Дата"], errors="coerce")
        ly_start, ly_end = start - relativedelta(years=1), end - relativedelta(years=1)
        dnorm = df["Дата"].dt.normalize()
        cur_mask = (dnorm >= start) & (dnorm <= end)
        ly_mask = (dnorm >= ly_start) & (dnorm <= ly_end)
        cur_stores = set(
            df.loc[cur_mask & (pd.to_numeric(df["Выручка факт"], errors="coerce").fillna(0) != 0), "Магазин"].astype(str)
        )
        if cur_stores:
            cur_mask = cur_mask & df["Магазин"].astype(str).isin(cur_stores)
            ly_mask = ly_mask & df["Магазин"].astype(str).isin(cur_stores)
        cur = float(pd.to_numeric(df.loc[cur_mask, "Выручка факт"], errors="coerce").fillna(0).sum())
        ly = float(pd.to_numeric(df.loc[ly_mask, "Выручка факт"], errors="coerce").fillna(0).sum())
        v = lfl_rto_pct(cur, ly)
        return None if v is None else round(v, 2)

    def _penetration_for_store(self, store: str, period: str = "week") -> tuple[float, float]:
        pen = self._penetration_frame(period)
        row = self._row_dict(pen, store) if pen is not None else {}
        if not row:
            return 0.0, 0.0
        total = float(row.get("Чеков всего", 0) or 0)
        sp = round(penetration_pct(row.get("Чеков с СП", 0), total), 1)
        pas = round(penetration_pct(row.get("Чеков с Паскуччи", 0), total), 1)
        return sp, pas

    def _sp_frame(self, period: str) -> pd.DataFrame:
        key = {"day": "sp_day", "week": "sp_week", "month": "sp_month"}.get(period, "sp_month")
        df = self.raw.get(key)
        if df is None or getattr(df, "empty", True):
            df = self.raw.get("sp_month")
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()

    def _excel_rows(self, period: str = "month"):
        sheet_key = {"day": "sales_day", "week": "sales_week", "month": "sales_month"}.get(period, "sales_month")
        sales_month = self.raw.get(sheet_key)
        if sales_month is None or getattr(sales_month, "empty", True):
            sales_month = self.raw.get("sales_month", pd.DataFrame())
        if sales_month is None or getattr(sales_month, "empty", True):
            return []
        availability = self.raw.get("availability_week", pd.DataFrame())
        sp_month = self._sp_frame(period)
        stock = self.raw.get("stock_month", pd.DataFrame())
        losses = self._losses_frame(period)
        ly_ok = self._ly_available()
        scale = self._money_scale()
        rows = []
        for store in sorted(sales_month["Магазин"].dropna().astype(str).unique().tolist()):
            m = self._row_dict(sales_month, store)
            a = self._row_dict(availability, store)
            sp = self._row_dict(sp_month, store)
            st = self._row_dict(stock, store)
            revenue_rub = float(m.get("Выручка факт", 0) or 0)
            plan_rub = float(m.get("Выручка план", 0) or 0)
            checks_abs = float(m.get("Количество чеков", 0) or 0)
            revenue = revenue_rub / scale
            plan = plan_rub / scale if plan_rub > 0 else None
            checks = checks_abs
            ticket = avg_ticket(revenue_rub, checks_abs) if checks_abs else 0.0
            sp_rev = float(sp.get("Выручка СП", 0) or 0)
            sp_total = float(sp.get("Выручка всего", 0) or 0) or revenue_rub
            own_share = own_production_share_pct(sp_rev, sp_total) if sp_total else 0
            shop_av = availability_pct(a.get("Топ ТЗ доступно позиций", 0), a.get("Топ ТЗ всего позиций", 0)) if a else 0
            prod_av = availability_pct(a.get("Топ СП доступно позиций", 0), a.get("Топ СП всего позиций", 0)) if a else 0
            plan_pct = plan_completion_pct(revenue_rub, plan_rub) if plan_rub > 0 else None
            ls = self._losses_th(losses, store)
            inv = self._inventory_shortage_th(losses, store)
            loss_pct = self._losses_pct(revenue, ls)
            yoy_v = self._yoy_pct_for_store(store, period, revenue)
            if plan_rub > 0 and plan_pct is not None:
                status = status_plan_pct(plan_pct)
                status = self._worst_status(
                    status,
                    self._operational_status(
                        losses_pct=loss_pct, shop_av=shop_av, prod_av=prod_av, own_share=own_share
                    ),
                )
            else:
                status = self._operational_status(
                    losses_pct=loss_pct, shop_av=shop_av, prod_av=prod_av, own_share=own_share
                )
            stock_plan_rub = float(st.get("Остатки на конец месяца план", 0) or 0) if st else 0.0
            stock_plan = round(stock_plan_rub / scale, 1) if stock_plan_rub > 0 else None
            stock_fact_rub = float(st.get("Остатки на конец месяца факт", 0) or 0) if st else 0.0
            rows.append(
                StoreRow(
                    store=store,
                    region="Дагестан",
                    cluster="Пилот",
                    format="Супермаркет",
                    revenue=round(revenue, 1 if scale > 1 else 0),
                    plan=round(plan, 1 if scale > 1 else 0) if plan is not None else None,
                    py=None,
                    plan_pct=round(plan_pct, 1) if plan_pct is not None else None,
                    yoy=yoy_v,
                    avg_ticket=round(ticket, 2),
                    checks=round(checks, 0),
                    own_production_share_pct=round(own_share, 1),
                    shop_availability=round(shop_av, 1),
                    production_availability=round(prod_av, 1),
                    stock_fact=round(stock_fact_rub / scale, 1) if st else 0,
                    stock_plan=stock_plan,
                    losses=round(ls, 1 if scale > 1 else 0),
                    inventory_shortage=round(inv, 1 if scale > 1 else 0),
                    status_color=status,
                    risk_level=self._risk(status),
                )
            )
        return self._assign_relative_risk(rows)

    def rows(self, period: str = "month"):
        if self.mode == "demo":
            return self._assign_relative_risk(self._demo_rows())
        return self._excel_rows(period)

    def filters(self):
        rows = self.rows("month")
        return {
            "periods": ["day", "week", "month"],
            "stores": [r.store for r in rows],
            "regions": sorted({r.region for r in rows if r.region}),
            "clusters": sorted({r.cluster for r in rows if r.cluster}),
            "formats": sorted({r.format for r in rows if r.format}),
        }

    @staticmethod
    def rank_stores(summary_rows: list[StoreRow], n: int = 5) -> tuple[list[StoreRow], list[StoreRow], list[StoreRow]]:
        """Лидеры ≠ аутсайдеры по потерям %; микро-магазины исключаются из рейтинга.

        Returns: (top, bottom, insufficient_for_ranking).
        Один и тот же магазин никогда не попадает одновременно в обе группы.
        """
        if not summary_rows:
            return [], [], []
        revs = sorted(float(r.revenue or 0) for r in summary_rows)
        mid = revs[len(revs) // 2] if revs else 0.0
        floor = mid * RANK_MEDIAN_FLOOR
        eligible = [r for r in summary_rows if float(r.revenue or 0) >= floor]
        insufficient = [r for r in summary_rows if float(r.revenue or 0) < floor]
        if not eligible:
            eligible = list(summary_rows)
            insufficient = []
        scored = []
        for r in eligible:
            scored.append((MetricsService._losses_pct(r.revenue, r.losses or 0), -(r.revenue or 0), r))
        scored.sort(key=lambda x: (x[0], x[1]))
        if len(scored) < 2:
            return [], [], insufficient
        take = min(n, max(1, len(scored) // 2))
        top = [x[2] for x in scored[:take]]
        bottom = [x[2] for x in reversed(scored[-take:])]
        top_names = {r.store for r in top}
        bottom = [r for r in bottom if r.store not in top_names]
        if not bottom:
            rest = [x[2] for x in reversed(scored) if x[2].store not in top_names]
            bottom = rest[:take]
        return top, bottom, insufficient

    def build_actions(self, row: StoreRow):
        actions = []
        if (row.shop_availability or 0) < SHOP_AV_YELLOW:
            actions.append(
                ActionItem(
                    priority="P1",
                    title="Проверить доступность ТЗ",
                    owner="Управляющий магазином",
                    eta="24 часа",
                    status_color="red",
                    rationale="Низкая доступность торгового зала ограничивает продажи",
                )
            )
        if (row.production_availability or 0) < PROD_AV_YELLOW:
            actions.append(
                ActionItem(
                    priority="P1",
                    title="Разобрать доступность производства",
                    owner="Руководитель производства",
                    eta="24 часа",
                    status_color="red",
                    rationale="Низкая доступность СП бьёт по доле собственного производства и среднему чеку",
                )
            )
        if (row.own_production_share_pct or 0) < SP_SHARE_YELLOW:
            actions.append(
                ActionItem(
                    priority="P1",
                    title="Поднять вес собственного производства",
                    owner="Операционный руководитель",
                    eta="48 часов",
                    status_color="red",
                    rationale="Доля СП ниже управленческого порога, теряется валовая прибыль",
                )
            )
        if self._plan_is_set(row.stock_plan) and (row.stock_fact or 0) > (row.stock_plan or 0) * 1.05:
            actions.append(
                ActionItem(
                    priority="P2",
                    title="Разобрать рост остатков",
                    owner="Категорийный менеджер / магазин",
                    eta="72 часа",
                    status_color="yellow",
                    rationale="Остатки выше плана — риск перетарки или ошибки заказа",
                )
            )
        if (row.losses or 0) > row.revenue * (LOSS_PCT_YELLOW / 100.0):
            actions.append(
                ActionItem(
                    priority="P1",
                    title="Провести разбор списаний по группам",
                    owner="Операционный контур + магазин",
                    eta="48 часов",
                    status_color="red",
                    rationale="Потери выше порога — нужен разбор по статьям (в т.ч. ФРОВ, производство, инвентаризация)",
                )
            )
        if self._plan_is_set(row.plan) and row.plan_pct is not None and row.plan_pct < 99:
            actions.append(
                ActionItem(
                    priority="P1",
                    title="Разобрать недовыполнение плана",
                    owner="Территориальный руководитель",
                    eta="24 часа",
                    status_color="red",
                    rationale="Нужно проверить трафик, доступность, промо и локальные причины просадки",
                )
            )
        return actions[:6] or [
            ActionItem(
                priority="P3",
                title="Поддерживать текущий операционный режим",
                owner="Управляющий магазином",
                eta="Текущая неделя",
                status_color="green",
                rationale="Ключевые KPI в пределах целевых порогов",
            )
        ]

    def _kpis_from_row_day(self, row: StoreRow) -> list[KPI]:
        loss_pct = self._losses_pct(row.revenue, row.losses or 0)
        plan_hint = "Факт vs план" if self._plan_is_set(row.plan) else "План — не задан в 1С"
        return [
            KPI(
                code="day_revenue",
                label="Выручка день",
                value=float(row.revenue),
                unit=self._money_unit_code(),
                plan=float(row.plan) if self._plan_is_set(row.plan) else None,
                delta_pct=round((row.plan_pct or 0) - 100, 1) if self._plan_is_set(row.plan) else None,
                status_color=row.status_color,
                hint=plan_hint,
            ),
            KPI(
                code="day_checks",
                label="Чеки день",
                value=float(row.checks or 0),
                unit="checks",
                status_color="blue",
                hint="Операционный ритм магазина",
            ),
            KPI(
                code="day_avg_ticket",
                label="Средний чек",
                value=float(row.avg_ticket or 0),
                unit="ticket",
                status_color="blue",
                hint="Выручка / чеки",
            ),
            KPI(
                code="day_losses_pct",
                label="Списания, % к РТО",
                value=loss_pct,
                unit="pct",
                status_color=self._status(loss_pct, LOSS_PCT_GREEN, LOSS_PCT_YELLOW, reverse=True),
                hint="Товарные списания / выручка",
            ),
        ]

    def _kpis_from_row_week(self, row: StoreRow) -> list[KPI]:
        return [
            KPI(
                code="week_revenue",
                label="Выручка неделя",
                value=float(row.revenue),
                unit=self._money_unit_code(),
                yoy=row.yoy,
                status_color=row.status_color,
                hint="Недельный итог" + (" · г/г недоступен" if row.yoy is None else ""),
            ),
            KPI(
                code="week_shop_av",
                label="Доступность ТЗ",
                value=float(row.shop_availability or 0),
                unit="pct",
                status_color=self._status(row.shop_availability or 0, SHOP_AV_GREEN, SHOP_AV_YELLOW),
                hint="Топовые позиции торгового зала",
            ),
            KPI(
                code="week_prod_av",
                label="Доступность СП",
                value=float(row.production_availability or 0),
                unit="pct",
                status_color=self._status(row.production_availability or 0, PROD_AV_GREEN, PROD_AV_YELLOW),
                hint="Топовые позиции собственного производства",
            ),
        ]

    def _kpis_from_row_month(self, row: StoreRow) -> list[KPI]:
        loss_pct = self._losses_pct(row.revenue, row.losses or 0)
        sp_pen, pas_pen = self._penetration_for_store(row.store, "month")
        return [
            KPI(
                code="month_revenue",
                label="Выручка",
                value=float(row.revenue),
                unit=self._money_unit_code(),
                plan=float(row.plan) if self._plan_is_set(row.plan) else None,
                py=float(row.py) if row.py is not None else None,
                yoy=row.yoy,
                status_color=row.status_color,
                hint="Итог периода" + (" · план не задан" if not self._plan_is_set(row.plan) else ""),
            ),
            KPI(
                code="month_share",
                label="Доля СП",
                value=float(row.own_production_share_pct or 0),
                unit="pct",
                status_color=(
                    "green"
                    if (row.own_production_share_pct or 0) >= SP_SHARE_GREEN
                    else "yellow"
                    if (row.own_production_share_pct or 0) >= SP_SHARE_YELLOW
                    else "red"
                ),
                hint="Выручка собственного производства / выручка",
            ),
            KPI(
                code="month_losses",
                label="Списания",
                value=float(row.losses or 0),
                unit=self._money_unit_code(),
                delta_pct=loss_pct,
                status_color=self._status(loss_pct, LOSS_PCT_GREEN, LOSS_PCT_YELLOW, reverse=True),
                hint="Списания, % к выручке",
            ),
            KPI(
                code="month_stock",
                label="Остатки",
                value=float(row.stock_fact or 0),
                unit=self._money_unit_code(),
                plan=float(row.stock_plan) if self._plan_is_set(row.stock_plan) else None,
                status_color="blue",
                hint="Снимок остатков на отчётную дату",
            ),
            KPI(
                code="month_sp_pen",
                label="Пенетрация СП",
                value=sp_pen,
                unit="pct",
                status_color=self._status(sp_pen, 33, 28),
                hint="Чеки с SKU собственного производства / все чеки",
            ),
            KPI(
                code="month_pas_pen",
                label="Пенетрация Паскуччи",
                value=pas_pen,
                unit="pct",
                status_color=self._status(pas_pen, 7, 5),
                hint="Чеки с маркой «Паскуччи» / все чеки. Методология PBI: NEEDS_REVIEW",
            ),
            KPI(
                code="month_tz_av",
                label="Доступность ТЗ",
                value=float(row.shop_availability or 0),
                unit="pct",
                status_color=self._status(row.shop_availability or 0, SHOP_AV_GREEN, SHOP_AV_YELLOW),
                hint="Остаток на конец периода",
            ),
            KPI(
                code="month_sp_av",
                label="Доступность СП",
                value=float(row.production_availability or 0),
                unit="pct",
                status_color=self._status(row.production_availability or 0, PROD_AV_GREEN, PROD_AV_YELLOW),
                hint="Продажи за выбранный период",
            ),
        ]

    def _loss_drivers_for_store(self, store: str, period: str, revenue: float) -> list[LossItem]:
        losses = self._losses_frame(period)
        if losses is None or getattr(losses, "empty", True) or "Магазин" not in losses.columns:
            return []
        store_ls = losses[losses["Магазин"].astype(str) == store]
        if store_ls.empty or "Сумма" not in store_ls.columns:
            return []
        kind_col = "Вид потерь" if "Вид потерь" in store_ls.columns else None
        if not kind_col:
            return []
        out: list[LossItem] = []
        for kind, group in store_ls.groupby(store_ls[kind_col].astype(str)):
            amount = float(pd.to_numeric(group["Сумма"], errors="coerce").fillna(0).sum()) / self._money_scale()
            if abs(amount) <= 0:
                continue
            if str(kind) in {"Списания (PBI)", "PBI 1РТО С"}:
                continue
            amount = abs(amount)
            out.append(
                LossItem(
                    group=str(kind),
                    amount=round(amount, 1),
                    pct_rto=round(amount / max(revenue, 0.01) * 100, 2),
                    status_color=self._status(
                        amount / max(revenue, 0.01) * 100, LOSS_PCT_GREEN, LOSS_PCT_YELLOW, reverse=True
                    ),
                )
            )
        return sorted(out, key=lambda x: x.amount, reverse=True)[:3]

    def _network_context_for_store(self, row: StoreRow, peers: list[StoreRow]) -> list[str]:
        if not peers:
            return []
        loss_pcts = [self._losses_pct(r.revenue, r.losses or 0) for r in peers]
        loss_pcts_sorted = sorted(loss_pcts)
        median_loss = loss_pcts_sorted[len(loss_pcts_sorted) // 2]
        store_loss = self._losses_pct(row.revenue, row.losses or 0)
        delta = round(store_loss - median_loss, 2)
        ctx = [
            f"Потери магазина {store_loss:.2f}% к выручке; медиана сети {median_loss:.2f}% "
            f"({'выше' if delta > 0 else 'ниже' if delta < 0 else 'на уровне'} медианы на {abs(delta):.2f} п.п.)."
        ]
        tz_vals = sorted(float(r.shop_availability or 0) for r in peers)
        med_tz = tz_vals[len(tz_vals) // 2]
        ctx.append(
            f"Доступность ТЗ: {float(row.shop_availability or 0):.1f}% при медиане сети {med_tz:.1f}%."
        )
        return ctx

    def build_drilldown(self, row: StoreRow):
        """Обратная совместимость: строит карточку из одной строки (тесты/демо)."""
        return self.build_drilldown_for_store(row.store, summary_row=row, period="day")

    def build_drilldown_for_store(
        self, store: str, summary_row: Optional[StoreRow] = None, period: str = "day"
    ) -> Optional[StoreDrilldown]:
        """Карточка: независимые агрегаты день / неделя / месяц для одного магазина."""
        by_period = {
            "day": {r.store: r for r in self.rows("day")},
            "week": {r.store: r for r in self.rows("week")},
            "month": {r.store: r for r in self.rows("month")},
        }
        day_row = by_period["day"].get(store)
        week_row = by_period["week"].get(store)
        month_row = by_period["month"].get(store)
        summary = summary_row or day_row or week_row or month_row
        if summary is None:
            return None

        reasons = []
        if self._plan_is_set(summary.plan) and summary.plan_pct is not None and summary.plan_pct < 99:
            reasons.append("Недовыполнение плана связано с просадкой доступности, доли СП и/или трафика.")
        elif not self._plan_is_set(summary.plan):
            reasons.append("План продаж не задан в 1С — оценка идёт по операционным метрикам.")
        if (summary.shop_availability or 0) < SHOP_AV_YELLOW:
            reasons.append("Низкая доступность ТЗ ограничивает базовые продажи по топовым позициям.")
        if (summary.production_availability or 0) < PROD_AV_YELLOW:
            reasons.append("Низкая доступность производства ослабляет роль собственного производства в выручке.")
        if self._plan_is_set(summary.stock_plan) and (summary.stock_fact or 0) > (summary.stock_plan or 0) * 1.05:
            reasons.append("Рост остатков указывает на риск перетарки и снижения оборачиваемости.")
        if (summary.losses or 0) > summary.revenue * (LOSS_PCT_YELLOW / 100.0):
            reasons.append("Потери выше порога и требуют разбора по статьям и ответственным.")

        local_risks: list[AlertItem] = []
        if self._plan_is_set(summary.plan) and summary.plan_pct is not None and summary.plan_pct < 99:
            local_risks.append(
                AlertItem(
                    type="risk",
                    title="План под риском",
                    store=summary.store,
                    severity="red",
                    metric="plan_pct",
                    value=float(summary.plan_pct or 0),
                    comment="Магазин ниже порога выполнения плана",
                )
            )
        if (summary.own_production_share_pct or 0) < SP_SHARE_YELLOW:
            local_risks.append(
                AlertItem(
                    type="risk",
                    title="Низкий вес СП",
                    store=summary.store,
                    severity="red",
                    metric="own_production_share_pct",
                    value=float(summary.own_production_share_pct or 0),
                    comment="СП ниже минимального управленческого порога",
                )
            )
        if (summary.losses or 0) > summary.revenue * (LOSS_PCT_YELLOW / 100.0):
            local_risks.append(
                AlertItem(
                    type="risk",
                    title="Высокие потери",
                    store=summary.store,
                    severity="yellow",
                    metric="losses_pct",
                    value=self._losses_pct(summary.revenue, summary.losses or 0),
                    comment="Потери выше допустимого уровня",
                )
            )

        peers = list(by_period.get(period, by_period["day"]).values())
        return StoreDrilldown(
            store=store,
            summary=summary,
            day_kpis=self._kpis_from_row_day(day_row) if day_row else [],
            week_kpis=self._kpis_from_row_week(week_row) if week_row else [],
            month_kpis=self._kpis_from_row_month(month_row) if month_row else [],
            reasons=reasons or ["Существенных отклонений не выявлено."],
            local_risks=local_risks,
            actions=self.build_actions(summary),
            loss_drivers=self._loss_drivers_for_store(store, period, float(summary.revenue or 0)),
            network_context=self._network_context_for_store(summary, peers),
        )

    def _network_penetration(self, period: str = "week") -> tuple[float, float]:
        pen = self._penetration_frame(period)
        if pen is not None and not getattr(pen, "empty", True) and "Чеков всего" in getattr(pen, "columns", []):
            total = float(pd.to_numeric(pen["Чеков всего"], errors="coerce").fillna(0).sum())
            sp_c = (
                float(pd.to_numeric(pen["Чеков с СП"], errors="coerce").fillna(0).sum())
                if "Чеков с СП" in pen.columns
                else 0.0
            )
            pas_c = (
                float(pd.to_numeric(pen["Чеков с Паскуччи"], errors="coerce").fillna(0).sum())
                if "Чеков с Паскуччи" in pen.columns
                else 0.0
            )
            return round(penetration_pct(sp_c, total), 1), round(penetration_pct(pas_c, total), 1)
        return 0.0, 0.0

    def _losses_breakdown(
        self, revenue: float, period: str = "month", store: Optional[str] = None
    ) -> list[LossItem]:
        scale = self._money_scale()
        losses = self._losses_frame(period)
        if losses is not None and not getattr(losses, "empty", True) and "Вид потерь" in getattr(losses, "columns", []):
            df = losses
            if store and "Магазин" in df.columns:
                df = df[df["Магазин"].astype(str) == str(store)]
            out: list[LossItem] = []
            for kind, group in df.groupby(df["Вид потерь"].astype(str)):
                kind_s = str(kind)
                if kind_s in {"Списания (PBI)", "PBI 1РТО С", "None", "nan", ""}:
                    continue
                amount = float(pd.to_numeric(group["Сумма"], errors="coerce").fillna(0).sum()) / scale
                if abs(amount) < 0.01:
                    continue
                display = amount if "излиш" in kind_s.lower() else abs(amount)
                out.append(
                    LossItem(
                        group=kind_s,
                        amount=round(display, 2),
                        pct_rto=round(display / max(revenue, 0.01) * 100, 2),
                        status_color=self._status(
                            abs(display) / max(revenue, 0.01) * 100, LOSS_PCT_GREEN, LOSS_PCT_YELLOW, reverse=True
                        ),
                    )
                )
            if out:
                return sorted(out, key=lambda x: x.amount, reverse=True)
        wo = self._writeoff_frame(period)
        if wo is not None and not getattr(wo, "empty", True):
            if "Статья списания" in getattr(wo, "columns", []) and "Сумма" in wo.columns:
                dfw = wo
                if store and "Магазин" in dfw.columns:
                    dfw = dfw[dfw["Магазин"].astype(str) == str(store)]
                out = []
                for article, group in dfw.groupby(dfw["Статья списания"].astype(str)):
                    amount = float(pd.to_numeric(group["Сумма"], errors="coerce").fillna(0).sum()) / scale
                    if amount <= 0 or article in {"None", "nan", "", "PBI 1РТО С"}:
                        continue
                    out.append(
                        LossItem(
                            group=str(article),
                            amount=round(amount, 2),
                            pct_rto=round(amount / max(revenue, 0.01) * 100, 2),
                            status_color=self._status(
                                amount / max(revenue, 0.01) * 100, LOSS_PCT_GREEN, LOSS_PCT_YELLOW, reverse=True
                            ),
                        )
                    )
                if out:
                    return sorted(out, key=lambda x: x.amount, reverse=True)
        return []

    def _period_label_ru(self, period: str) -> str:
        custom = self._custom_bounds()
        if custom is not None:
            from app.streamlit_ui.period_range import format_period_label

            return format_period_label(custom[0].date(), custom[1].date())
        return {"day": "День", "week": "Неделя", "month": "Месяц"}.get(period, period)

    def _availability_meta(self, *, selected_store: Optional[str], drill_store: str) -> dict:
        """Формула + агрегат по магазинам + (если есть) SKU-пересчёт для проверки KPI."""
        week = self.raw.get("availability_week")
        sku = self.raw.get("availability_sku")
        check: list[dict] = []
        if isinstance(week, pd.DataFrame) and not week.empty and "Магазин" in week.columns:
            for rec in week.to_dict(orient="records"):
                store_name = str(rec.get("Магазин") or "").strip()
                if not store_name:
                    continue
                tz_tot = float(rec.get("Топ ТЗ всего позиций") or 0)
                tz_av = float(rec.get("Топ ТЗ доступно позиций") or 0)
                sp_tot = float(rec.get("Топ СП всего позиций") or 0)
                sp_av = float(rec.get("Топ СП доступно позиций") or 0)
                check.append(
                    {
                        "Магазин": store_name,
                        "ТЗ доступно": int(tz_av),
                        "ТЗ всего": int(tz_tot),
                        "ТЗ %": round(availability_pct(tz_av, tz_tot), 1),
                        "СП доступно": int(sp_av),
                        "СП всего": int(sp_tot),
                        "СП %": round(availability_pct(sp_av, sp_tot), 1),
                    }
                )
            check.sort(key=lambda x: x["ТЗ %"])

        target = (selected_store or drill_store or "").strip()
        detail: list[dict] = []
        verify: Optional[dict] = None
        if isinstance(sku, pd.DataFrame) and not sku.empty and target and "Магазин" in sku.columns:
            sub = sku[sku["Магазин"].astype(str) == target]
            rows = []
            for rec in sub.to_dict(orient="records"):
                qty = float(rec.get("Остаток") or 0)
                flag = rec.get("В наличии")
                in_stock = int(flag) if flag not in (None, "") else (1 if qty > 0 else 0)
                rows.append(
                    {
                        "Корзина": str(rec.get("Корзина") or ""),
                        "Артикул": str(rec.get("Артикул") or ""),
                        "Номенклатура": str(rec.get("Номенклатура") or ""),
                        "Остаток": round(qty, 3),
                        "Продажи": round(float(rec.get("Продажи") or 0), 2),
                        "В наличии": "да" if in_stock else "нет",
                        "_in_stock": in_stock,
                    }
                )
            rows.sort(key=lambda x: (x["В наличии"] == "да", x["Корзина"], x["Номенклатура"]))
            detail = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]

            def _recount(basket: str) -> dict:
                part = [r for r in rows if r["Корзина"] == basket]
                total = len(part)
                available = sum(1 for r in part if r["_in_stock"])
                return {
                    "available": available,
                    "total": total,
                    "pct": round(availability_pct(available, total), 1),
                }

            tz_r = _recount("ТЗ")
            sp_r = _recount("СП")
            store_check = next((c for c in check if c["Магазин"] == target), None)
            verify = {
                "store": target,
                "tz": tz_r,
                "sp": sp_r,
                "tz_kpi": None if store_check is None else store_check["ТЗ %"],
                "sp_kpi": None if store_check is None else store_check["СП %"],
                "tz_match": store_check is not None and abs(tz_r["pct"] - store_check["ТЗ %"]) < 0.15,
                "sp_match": store_check is not None and abs(sp_r["pct"] - store_check["СП %"]) < 0.15,
            }

        return {
            "availability_formula": (
                "Доступность ТЗ % = SKU «Корзина Топ 200» с нетто-остатком магазина > 0,001 "
                "на конец периода / число SKU в корзине × 100. "
                "Доступность СП % = SKU «Корзина Производство» с продажами за выбранный период "
                "/ число SKU в корзине × 100. "
                "Остаток ТЗ — сумма по складам магазина за 120 дней до конца периода "
                "(шум float не считается наличием)."
            ),
            "availability_check": check,
            "availability_detail": detail,
            "availability_sku_store": target,
            "availability_verify": verify,
        }

    def build_dashboard(self, period="month", store: Optional[str] = None):
        network_rows = self.rows(period)
        rows = [r for r in network_rows if r.store == store] if store else list(network_rows)
        summary_rows = rows if rows else list(network_rows)
        # Рейтинг и фокус всегда по всей сети — иначе при фильтре 1 магазина
        # он становится и «лидером», и «аутсайдером», а медиана = его же потери.
        rank_source = network_rows if network_rows else summary_rows
        plan_available = self._plan_available() or any(self._plan_is_set(r.plan) for r in summary_rows)
        ly_available = self._ly_available()

        if not summary_rows:
            return DashboardResponse(
                period=period,
                scope="store" if store else "network",
                mode="sql",
                selection={"store": store, "region": None, "cluster": None},
                last_update=str(self.raw.get("_report_day") or self.meta.get("Текущий день", "—")),
                title=f"МегаМетрики — {'Сеть' if not store else store}",
                subtitle=f"{self.meta.get('Название сети', 'Зеленое Яблоко')} · {self._period_label_ru(period)}",
                kpis=[],
                alerts=[
                    AlertItem(
                        type="info",
                        title="Нет данных за выбранный период",
                        severity="blue",
                        metric="empty",
                        value=0,
                        comment="В базе нет продаж за этот период или магазин не найден.",
                    )
                ],
                actions=[],
                top_stores=[],
                bottom_stores=[],
                store_table=[],
                losses=[],
                charts={"plan_vs_store": [], "losses_structure": [], "losses_pct_vs_store": []},
                drilldown=None,
                meta={
                    "network": self.meta.get("Название сети", "Зеленое Яблоко"),
                    "currency": self.meta.get("Валюта", "RUB"),
                    "ranking_metric": RANKING_METRIC_LABEL,
                    "ranking_help": RANKING_METRIC_HELP,
                    "risk_legend": RISK_LEGEND,
                    "plan_available": False,
                    "ly_available": False,
                    "empty": True,
                    "abbreviations": ABBREVIATIONS,
                },
            )

        revenue = round(sum(r.revenue for r in summary_rows), 2)
        plan = round(sum((r.plan or 0) for r in summary_rows), 2) if plan_available else 0.0
        own_share = round(
            sum((r.revenue * (r.own_production_share_pct or 0) / 100) for r in summary_rows) / max(revenue, 0.01) * 100,
            1,
        )
        writeoffs_only = round(sum((r.losses or 0) for r in summary_rows), 2)
        inventory = round(sum((r.inventory_shortage or 0) for r in summary_rows), 2)
        lf = self._losses_frame(period)
        surplus = round(sum(self._surplus_th(lf, r.store) for r in summary_rows), 2)
        # PBI «Потери» = РТО С + РТО И + РТО ОИ
        losses = round(writeoffs_only + inventory + surplus, 2)
        stock_fact = round(sum((r.stock_fact or 0) for r in summary_rows), 2)
        stock_plan_sum = round(sum((r.stock_plan or 0) for r in summary_rows if self._plan_is_set(r.stock_plan)), 2)
        checks_abs = round(sum((r.checks or 0) for r in summary_rows), 0)
        scale = self._money_scale()
        avg_ticket_v = (
            (sum((r.revenue or 0) * scale for r in summary_rows) / max(checks_abs, 1)) if checks_abs else 0.0
        )
        loss_pct_net = self._losses_pct(revenue, writeoffs_only)
        plan_pct_net = plan_completion_pct(revenue, plan) if plan > 0 else None
        if store:
            sp_pen, pas_pen = self._penetration_for_store(store, period)
        else:
            sp_pen, pas_pen = self._network_penetration(period)

        day_kpis = [
            KPI(
                code="revenue_day",
                label="Выручка за день",
                value=revenue,
                unit=self._money_unit_code(),
                plan=plan if plan > 0 else None,
                delta_pct=round((revenue / plan - 1) * 100, 1) if plan > 0 else None,
                status_color=status_plan_pct(plan_pct_net) if plan_pct_net is not None else "blue",
                hint="Факт vs план" if plan > 0 else "План — не задан в 1С",
            ),
            KPI(
                code="checks_day",
                label="Чеки",
                value=checks_abs,
                unit="checks",
                status_color="blue",
                hint="Дневной поток",
            ),
            KPI(
                code="avg_ticket_day",
                label="Средний чек",
                value=round(avg_ticket_v, 2),
                unit="ticket",
                status_color="blue",
                hint="Выручка / чеки",
            ),
            KPI(
                code="losses_pct_day",
                label="Списания, % к РТО",
                value=loss_pct_net,
                unit="pct",
                status_color=self._status(loss_pct_net, LOSS_PCT_GREEN, LOSS_PCT_YELLOW, reverse=True),
                hint="Товарные списания / выручка",
            ),
            KPI(
                code="shop_availability",
                label="Доступность ТЗ",
                value=round(sum((r.shop_availability or 0) for r in summary_rows) / max(len(summary_rows), 1), 1),
                unit="pct",
                status_color=self._status(
                    sum((r.shop_availability or 0) for r in summary_rows) / max(len(summary_rows), 1),
                    SHOP_AV_GREEN,
                    SHOP_AV_YELLOW,
                ),
                hint="Корзина топ-позиций торгового зала",
            ),
        ]
        week_kpis = [
            KPI(
                code="revenue_week",
                label="Выручка за неделю",
                value=revenue,
                unit=self._money_unit_code(),
                yoy=None if not ly_available else None,
                status_color="blue",
                hint="Факт за неделю" + (" · нет данных за прошлый год (г/г)" if not ly_available else ""),
            ),
            KPI(
                code="sp_penetration",
                label="Пенетрация СП",
                value=sp_pen,
                unit="pct",
                status_color=self._status(sp_pen, 33, 28),
                hint="Чеки с собственным производством / все чеки",
            ),
            KPI(
                code="pascucci_penetration",
                label="Пенетрация Паскуччи",
                value=pas_pen,
                unit="pct",
                status_color=self._status(pas_pen, 7, 5),
                hint="Чеки с Паскуччи / все чеки",
            ),
            KPI(
                code="writeoff_pct",
                label="Списания, % к РТО",
                value=loss_pct_net,
                unit="pct",
                status_color=self._status(loss_pct_net, LOSS_PCT_GREEN, LOSS_PCT_YELLOW, reverse=True),
                hint="Товарные списания / выручка",
            ),
            KPI(
                code="inventory_shortage",
                label="Недостачи",
                value=inventory,
                unit=self._money_unit_code(),
                status_color=self._status(inventory / max(revenue, 0.01) * 100, 0.15, 0.3, reverse=True),
                hint=f"{inventory / max(revenue, 0.01) * 100:.2f}% от выручки".replace(".", ","),
            ),
        ]
        rev_label = "Выручка" if self._custom_bounds() else "Выручка за месяц"
        month_kpis = [
            KPI(
                code="revenue_month",
                label=rev_label,
                value=revenue,
                unit=self._money_unit_code(),
                plan=plan if plan > 0 else None,
                delta_abs=round(revenue - plan, 2) if plan > 0 else None,
                delta_pct=round((revenue / plan - 1) * 100, 1) if plan > 0 else None,
                yoy=None if not ly_available else None,
                status_color=status_plan_pct(plan_pct_net) if plan_pct_net is not None else "blue",
                hint=(
                    "Факт vs план"
                    if plan > 0
                    else "План — не задан в 1С"
                )
                + (" · нет данных г/г" if not ly_available else ""),
            ),
            KPI(
                code="checks_month",
                label="Чеки",
                value=checks_abs,
                unit="checks",
                status_color="blue",
                hint="Поток покупателей за период",
            ),
            KPI(
                code="avg_ticket_month",
                label="Средний чек",
                value=round(avg_ticket_v, 2),
                unit="ticket",
                status_color="blue",
                hint="Выручка / чеки",
            ),
            KPI(
                code="own_production_share",
                label="Доля СП",
                value=own_share,
                unit="pct",
                status_color=(
                    "green" if own_share >= SP_SHARE_GREEN else "yellow" if own_share >= SP_SHARE_YELLOW else "red"
                ),
                hint="Выручка собственного производства / выручка",
            ),
            KPI(
                code="stock_end_month",
                label="Остатки",
                value=stock_fact,
                unit=self._money_unit_code(),
                plan=stock_plan_sum if stock_plan_sum > 0 else None,
                delta_abs=round(stock_fact - stock_plan_sum, 2) if stock_plan_sum > 0 else None,
                status_color="blue",
                hint="Складские остатки на отчётную дату",
            ),
            KPI(
                code="losses_month",
                label="Списания",
                value=writeoffs_only,
                unit=self._money_unit_code(),
                status_color=self._status(loss_pct_net, LOSS_PCT_GREEN, LOSS_PCT_YELLOW, reverse=True),
                hint=f"{loss_pct_net:.2f}% от выручки".replace(".", ","),
            ),
            KPI(
                code="inventory_shortage_month",
                label="Недостачи",
                value=inventory,
                unit=self._money_unit_code(),
                status_color=self._status(inventory / max(revenue, 0.01) * 100, 0.15, 0.3, reverse=True),
                hint=f"{inventory / max(revenue, 0.01) * 100:.2f}% от выручки".replace(".", ","),
            ),
            KPI(
                code="pbi_losses_total",
                label="Потери (Спи+Инв+ОИ)",
                value=losses,
                unit=self._money_unit_code(),
                status_color=self._status(
                    abs(losses) / max(revenue, 0.01) * 100, LOSS_PCT_GREEN, LOSS_PCT_YELLOW, reverse=True
                ),
                hint=f"{abs(losses) / max(revenue, 0.01) * 100:.2f}% от выручки".replace(".", ","),
            ),
        ]
        # LFL / г/г: сеть = DIVIDE(ΣРТО, ΣРТО LY)−1; магазин = LFL этой точки (как строка матрицы PBI)
        if store and summary_rows:
            net_yoy = summary_rows[0].yoy
        else:
            net_yoy = self._network_lfl_pct(period)
        lfl_kpi = KPI(
            code="lfl_rto",
            label="LFL РТО",
            value=float(net_yoy) if net_yoy is not None else 0.0,
            unit="pct",
            yoy=net_yoy,
            status_color="blue",
            hint="к прошлому году" if net_yoy is not None else "нет данных за прошлый год",
        )
        kpis = {"day": day_kpis, "week": week_kpis, "month": month_kpis}[period]
        for k in kpis:
            if k.code.startswith("revenue") and net_yoy is not None:
                k.yoy = net_yoy
        kpis = list(kpis) + [lfl_kpi]
        codes = {k.code for k in kpis}
        shop_av_net = round(
            sum((r.shop_availability or 0) for r in summary_rows) / max(len(summary_rows), 1), 1
        )
        prod_av_net = round(
            sum((r.production_availability or 0) for r in summary_rows) / max(len(summary_rows), 1), 1
        )
        if "sp_penetration" not in codes:
            kpis.append(
                KPI(
                    code="sp_penetration",
                    label="Пенетрация СП",
                    value=sp_pen,
                    unit="pct",
                    status_color=self._status(sp_pen, 33, 28),
                    hint="Чеки с SKU «Производство Зеленого яблока» / все чеки (PBI Пенетрация)",
                )
            )
        if "pascucci_penetration" not in codes:
            kpis.append(
                KPI(
                    code="pascucci_penetration",
                    label="Пенетрация Паскуччи",
                    value=pas_pen,
                    unit="pct",
                    status_color=self._status(pas_pen, 7, 5),
                    hint="Чеки с маркой «Паскуччи» / все чеки. Методология PBI: NEEDS_REVIEW",
                )
            )
        if "shop_availability" not in codes:
            kpis.append(
                KPI(
                    code="shop_availability",
                    label="Доступность ТЗ",
                    value=shop_av_net,
                    unit="pct",
                    status_color=self._status(shop_av_net, SHOP_AV_GREEN, SHOP_AV_YELLOW),
                    hint="Корзина Топ 200: SKU с остатком на конец периода / SKU в корзине",
                )
            )
        if "production_availability" not in codes:
            kpis.append(
                KPI(
                    code="production_availability",
                    label="Доступность СП",
                    value=prod_av_net,
                    unit="pct",
                    status_color=self._status(prod_av_net, PROD_AV_GREEN, PROD_AV_YELLOW),
                    hint="Корзина Производство: SKU с продажами за период / SKU в корзине",
                )
            )
        losses_breakdown = self._losses_breakdown(revenue, period, store=store)
        top, bottom, insufficient = self.rank_stores(rank_source, n=5)
        actions = []
        for row in bottom[:3]:
            actions.extend(self.build_actions(row)[:2])
        actions = actions[:6]
        alerts: list[AlertItem] = []
        for row in summary_rows:
            if self._plan_is_set(row.plan) and row.plan_pct is not None and row.plan_pct < 99:
                alerts.append(
                    AlertItem(
                        type="risk",
                        title="План под риском",
                        store=row.store,
                        severity="red",
                        metric="plan_pct",
                        value=float(row.plan_pct or 0),
                        comment="Недовыполнение плана требует быстрого разбора причин",
                    )
                )
            if (row.losses or 0) > row.revenue * (LOSS_PCT_YELLOW / 100.0):
                alerts.append(
                    AlertItem(
                        type="risk",
                        title="Высокие потери",
                        store=row.store,
                        severity="yellow",
                        metric="losses_pct",
                        value=self._losses_pct(row.revenue, row.losses or 0),
                        comment="Потери выше допустимого уровня",
                    )
                )
            if (row.own_production_share_pct or 0) < SP_SHARE_YELLOW:
                alerts.append(
                    AlertItem(
                        type="risk",
                        title="Просадка собственного производства",
                        store=row.store,
                        severity="red",
                        metric="own_share",
                        value=float(row.own_production_share_pct or 0),
                        comment="Низкая доля СП ухудшает экономику магазина",
                    )
                )
        if not plan_available:
            alerts.insert(
                0,
                AlertItem(
                    type="info",
                    title="План — не задан",
                    severity="blue",
                    metric="plan",
                    value=0,
                    comment="Плановые показатели не внесены в 1С — ранжирование и риск считаются без плана.",
                ),
            )
        if not ly_available:
            alerts.insert(
                0 if plan_available else 1,
                AlertItem(
                    type="info",
                    title="Нет данных за прошлый год",
                    severity="blue",
                    metric="yoy",
                    value=0,
                    comment="Сравнение год к году скрыто: в выгрузке нет продаж за аналогичный период прошлого года.",
                ),
            )

        drill_target_store = (
            summary_rows[0].store if len(summary_rows) == 1 else (bottom[0].store if bottom else summary_rows[0].store)
        )
        drill_summary = next(
            (r for r in (summary_rows + rank_source) if r.store == drill_target_store),
            summary_rows[0],
        )
        drilldown = self.build_drilldown_for_store(drill_target_store, summary_row=drill_summary, period=period)

        # Главный фокус: худший по композитному скору по всей сети (не по узкому фильтру).
        focus_pool = bottom or [r for r in rank_source if r not in insufficient] or rank_source
        focus_row = max(
            focus_pool,
            key=lambda r: self._risk_score(
                losses_pct=self._losses_pct(r.revenue, r.losses or 0),
                shop_av=r.shop_availability or 0,
                prod_av=r.production_availability or 0,
                own_share=r.own_production_share_pct or 0,
                shortage_pct=self._losses_pct(r.revenue, r.inventory_shortage or 0),
            ),
        )
        loss_pcts = sorted(self._losses_pct(r.revenue, r.losses or 0) for r in rank_source)
        median_loss = loss_pcts[len(loss_pcts) // 2] if loss_pcts else 0.0
        focus_loss = self._losses_pct(focus_row.revenue, focus_row.losses or 0)
        delta_pp = round(focus_loss - median_loss, 2)
        if abs(delta_pp) < 0.05 and len(rank_source) > 1:
            # Защита от ложного «фокуса» при равенстве медиане — берём max отклонение вверх.
            focus_row = max(
                rank_source,
                key=lambda r: self._losses_pct(r.revenue, r.losses or 0) - median_loss,
            )
            focus_loss = self._losses_pct(focus_row.revenue, focus_row.losses or 0)
            delta_pp = round(focus_loss - median_loss, 2)
        focus_text = (
            f"Главный фокус: {focus_row.store} — потери {focus_loss:.2f}% "
            f"(медиана сети {median_loss:.2f}%, отклонение {delta_pp:+.2f} п.п.), "
            f"риск: {focus_row.risk_level}"
        )

        losses_pct_chart = [
            {
                "store": r.store,
                "losses_pct": self._losses_pct(r.revenue, r.losses or 0),
                "status_color": r.status_color,
            }
            for r in summary_rows
        ]
        charts = {
            "plan_vs_store": (
                [{"store": r.store, "plan_pct": r.plan_pct, "status_color": r.status_color} for r in summary_rows]
                if plan_available
                else []
            ),
            "losses_pct_vs_store": losses_pct_chart,
            "losses_structure": [x.model_dump() for x in losses_breakdown],
            "stock_vs_plan": [{"store": r.store, "stock_fact": r.stock_fact, "stock_plan": r.stock_plan} for r in summary_rows],
            "own_prod_share": [{"store": r.store, "own_production_share_pct": r.own_production_share_pct} for r in summary_rows],
            "show_plan_chart": plan_available,
        }

        report_note = self.raw.get("_report_note") or ""
        custom = self._custom_bounds()
        last_update = str(
            (custom[1].strftime("%Y-%m-%d") if custom else None)
            or self.raw.get("_report_day")
            or self.meta.get("Текущий день", "—")
        )

        return DashboardResponse(
            period=period,
            scope="store" if store else "network",
            mode="sql",
            selection={"store": store, "region": None, "cluster": None},
            last_update=last_update,
            title=f"МегаМетрики — {'Сеть' if not store else store}",
            subtitle=f"{self.meta.get('Название сети', 'Зеленое Яблоко')} · {self._period_label_ru(period)}",
            kpis=kpis,
            alerts=alerts[:12],
            actions=actions,
            top_stores=top,
            bottom_stores=bottom,
            store_table=sorted(summary_rows, key=lambda x: x.revenue, reverse=True),
            losses=losses_breakdown,
            charts=charts,
            drilldown=drilldown,
            meta={
                "network": self.meta.get("Название сети", "Зеленое Яблоко"),
                "currency": self.meta.get("Валюта", "RUB"),
                "ranking_metric": RANKING_METRIC_LABEL,
                "ranking_help": RANKING_METRIC_HELP,
                "risk_legend": RISK_LEGEND,
                "plan_available": plan_available,
                "ly_available": ly_available,
                "report_note": report_note,
                "cache_note": "",
                "abbreviations": ABBREVIATIONS,
                "period_label": self._period_label_ru(period),
                "custom_from": custom[0].strftime("%Y-%m-%d") if custom else None,
                "custom_to": custom[1].strftime("%Y-%m-%d") if custom else None,
                "focus_text": focus_text,
                "focus_store": focus_row.store,
                "insufficient_stores": [r.store for r in insufficient],
                "rank_median_floor_pct": int(RANK_MEDIAN_FLOOR * 100),
                "coverage_label": (
                    f"{int(self.raw.get('_report_stores') or len(rank_source))} из "
                    f"{int(self.raw.get('_report_stores_max') or len(rank_source))} магазинов"
                    + (" — охват неполный" if self.raw.get("_report_incomplete") else " — полный охват")
                ),
                "report_incomplete": bool(self.raw.get("_report_incomplete")),
                "money_unit": self._money_unit_code(),
                "metric_profile": "pbi" if self._is_pbi_parity() else "legacy",
                "pbi_parity": self._is_pbi_parity(),
                "month_from": self.raw.get("_month_from"),
                "month_to": self.raw.get("_month_to"),
                "week_from": self.raw.get("_week_from"),
                "week_to": self.raw.get("_week_to"),
                **self._availability_meta(selected_store=store, drill_store=drill_target_store),
            },
        )
