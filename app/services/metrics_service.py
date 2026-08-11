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
        return {"green": "low", "yellow": "medium", "red": "high"}.get(status, "medium")

    def _demo_rows(self):
        rows = []
        for item in self.raw["stores"]:
            status = status_plan_pct(item["plan_pct"])
            if item["own_production_share_pct"] < 30:
                status = "red" if item["own_production_share_pct"] < 28 else "yellow"
            rows.append(
                StoreRow(
                    store=item["store"],
                    region=item["region"],
                    cluster=item["cluster"],
                    format=item["format"],
                    revenue=item["revenue"],
                    plan=item["plan"],
                    py=item["py"],
                    plan_pct=item["plan_pct"],
                    yoy=item["yoy"],
                    avg_ticket=item["avg_ticket"],
                    checks=item["checks"],
                    own_production_share_pct=item["own_production_share_pct"],
                    shop_availability=item["shop_availability"],
                    production_availability=item["production_availability"],
                    stock_fact=item["stock_fact"],
                    stock_plan=item["stock_plan"],
                    losses=item["losses"],
                    inventory_shortage=item["inventory_shortage"],
                    status_color=status,
                    risk_level=self._risk(status),
                )
            )
        return rows

    @staticmethod
    def _row_dict(df: pd.DataFrame, store: str) -> dict:
        if df is None or getattr(df, "empty", True) or "Магазин" not in df.columns:
            return {}
        hit = df[df["Магазин"].astype(str) == store]
        if hit.empty:
            return {}
        return hit.iloc[0].to_dict()

    def _inventory_shortage_mln(self, losses: pd.DataFrame, store: str) -> float:
        """M29: SUM(Сумма) where Вид потерь = Инвентаризация (млн руб)."""
        if losses is None or getattr(losses, "empty", True):
            return 0.0
        store_ls = losses[losses["Магазин"].astype(str) == store] if "Магазин" in losses.columns else losses
        if store_ls.empty:
            return 0.0
        if "Вид потерь" in store_ls.columns:
            mask = store_ls["Вид потерь"].astype(str).str.contains("инвентар", case=False, na=False)
            return float(store_ls.loc[mask, "Сумма"].sum()) / 1_000_000 if "Сумма" in store_ls.columns else 0.0
        return 0.0

    def _losses_mln(self, losses: pd.DataFrame, store: str) -> float:
        """M28+M29 total abs losses for store (млн). Prefer all rows; catalog losses_month."""
        if losses is None or getattr(losses, "empty", True) or "Магазин" not in losses.columns:
            return 0.0
        store_ls = losses[losses["Магазин"].astype(str) == store]
        if store_ls.empty or "Сумма" not in store_ls.columns:
            return 0.0
        return float(store_ls["Сумма"].sum()) / 1_000_000

    def _penetration_for_store(self, store: str) -> tuple[float, float]:
        """M08 / M09 from пенетрация_неделя when present; else (0, 0)."""
        pen = self.raw.get("penetration_week")
        row = self._row_dict(pen, store) if pen is not None else {}
        if not row:
            return 0.0, 0.0
        total = float(row.get("Чеков всего", 0) or 0)
        sp = penetration_pct(row.get("Чеков с СП", 0), total)
        pas = penetration_pct(row.get("Чеков с Паскуччи", 0), total)
        return sp, pas

    def _excel_rows(self, period: str = "month"):
        sheet_key = {"day": "sales_day", "week": "sales_week", "month": "sales_month"}.get(period, "sales_month")
        sales_month = self.raw.get(sheet_key)
        if sales_month is None or getattr(sales_month, "empty", True):
            sales_month = self.raw["sales_month"]
        availability = self.raw.get("availability_week", pd.DataFrame())
        sp_month = self.raw.get("sp_month", pd.DataFrame())
        stock = self.raw.get("stock_month", pd.DataFrame())
        losses = self.raw.get("losses_month", pd.DataFrame())
        rows = []
        for store in sorted(sales_month["Магазин"].dropna().astype(str).unique().tolist()):
            m = sales_month[sales_month["Магазин"].astype(str) == store].iloc[0].to_dict()
            a = self._row_dict(availability, store)
            sp = self._row_dict(sp_month, store)
            st = self._row_dict(stock, store)
            revenue_rub = float(m.get("Выручка факт", 0) or 0)
            plan_rub = float(m.get("Выручка план", 0) or 0)
            checks_abs = float(m.get("Количество чеков", 0) or 0)
            revenue = revenue_rub / 1_000_000
            plan = plan_rub / 1_000_000
            py = revenue / 1.056 if revenue else 0
            checks = checks_abs / 1000
            # M05
            ticket = round(avg_ticket(revenue_rub, checks_abs)) if checks_abs else 0
            # SP share vs RTO
            own_share = own_production_share_pct(float(sp.get("Выручка СП", 0) or 0), revenue_rub) if revenue_rub else 0
            # M06 / M07
            shop_av = availability_pct(a.get("Топ ТЗ доступно позиций", 0), a.get("Топ ТЗ всего позиций", 0)) if a else 0
            prod_av = availability_pct(a.get("Топ СП доступно позиций", 0), a.get("Топ СП всего позиций", 0)) if a else 0
            # M03
            plan_pct = plan_completion_pct(revenue_rub, plan_rub)
            status = status_plan_pct(plan_pct) if plan_rub else "blue"
            ls = self._losses_mln(losses, store)
            inv = self._inventory_shortage_mln(losses, store)
            rows.append(
                StoreRow(
                    store=store,
                    region="Дагестан",
                    cluster="Пилот",
                    format="Супермаркет",
                    revenue=round(revenue, 2),
                    plan=round(plan, 2),
                    py=round(py, 2),
                    plan_pct=round(plan_pct, 1),
                    yoy=round((revenue / py - 1) * 100, 1) if py else 0,
                    avg_ticket=ticket,
                    checks=round(checks, 4),
                    own_production_share_pct=round(own_share, 1),
                    shop_availability=round(shop_av, 1),
                    production_availability=round(prod_av, 1),
                    stock_fact=round(float(st.get("Остатки на конец месяца факт", 0) or 0) / 1_000_000, 2) if st else 0,
                    stock_plan=round(float(st.get("Остатки на конец месяца план", 0) or 0) / 1_000_000, 2) if st else 0,
                    losses=round(ls, 2),
                    inventory_shortage=round(inv, 2),
                    status_color=status,
                    risk_level=self._risk(status),
                )
            )
        return rows

    def rows(self, period: str = "month"):
        return self._demo_rows() if self.mode == "demo" else self._excel_rows(period)

    def filters(self):
        rows = self.rows("month")
        return {
            "periods": ["day", "week", "month"],
            "stores": [r.store for r in rows],
            "regions": sorted({r.region for r in rows if r.region}),
            "clusters": sorted({r.cluster for r in rows if r.cluster}),
            "formats": sorted({r.format for r in rows if r.format}),
        }

    def build_actions(self, row: StoreRow):
        actions = []
        if (row.shop_availability or 0) < 90:
            actions.append(
                ActionItem(
                    priority="P1",
                    title="Проверить availability ТЗ",
                    owner="Управляющий магазином",
                    eta="24 часа",
                    status_color="red",
                    rationale="Низкая доступность ТЗ ограничивает продажи и искажает выполнение плана",
                )
            )
        if (row.production_availability or 0) < 85:
            actions.append(
                ActionItem(
                    priority="P1",
                    title="Разобрать availability производства",
                    owner="Руководитель производства",
                    eta="24 часа",
                    status_color="red",
                    rationale="Низкая доступность СП бьет по доле собственного производства и среднему чеку",
                )
            )
        if (row.own_production_share_pct or 0) < 30:
            actions.append(
                ActionItem(
                    priority="P1",
                    title="Поднять вес собственного производства",
                    owner="Операционный руководитель",
                    eta="48 часов",
                    status_color="red",
                    rationale="Доля СП ниже управленческого порога, теряется валовая прибыль и уникальность предложения",
                )
            )
        if (row.stock_fact or 0) > (row.stock_plan or 0) * 1.05:
            actions.append(
                ActionItem(
                    priority="P2",
                    title="Разобрать рост остатков",
                    owner="Категорийный менеджер / магазин",
                    eta="72 часа",
                    status_color="yellow",
                    rationale="Избыточные остатки сигнализируют о перетарке, слабой оборачиваемости или ошибке заказа",
                )
            )
        if (row.losses or 0) > row.revenue * 0.012:
            actions.append(
                ActionItem(
                    priority="P1",
                    title="Провести разбор списаний по группам",
                    owner="Операционный контур + магазин",
                    eta="48 часов",
                    status_color="red",
                    rationale="Потери выше порога, нужен разбор ФРОВ, Паскуччи, Производства и прочих групп",
                )
            )
        # Catalog M03: red below 98–99 band → treat <99 as plan risk action
        if (row.plan_pct or 0) < 99:
            actions.append(
                ActionItem(
                    priority="P1",
                    title="Разобрать недовыполнение плана",
                    owner="Территориальный руководитель",
                    eta="24 часа",
                    status_color="red",
                    rationale="Нужно проверить трафик, availability, промо, выкладку и локальные причины просадки",
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

    def build_drilldown(self, row: StoreRow):
        day = [
            KPI(
                code="day_revenue",
                label="Выручка день",
                value=round(row.revenue / 30, 2),
                unit="mln_rub",
                plan=round((row.plan or 0) / 30, 2),
                delta_pct=round((row.plan_pct or 0) - 100, 1),
                status_color=row.status_color,
                hint="Факт vs план",
            ),
            KPI(
                code="day_checks",
                label="Чеки день",
                value=round((row.checks or 0) * 1000 / 30, 0),
                unit="checks",
                status_color="blue",
                hint="Операционный ритм магазина",
            ),
            KPI(
                code="day_avg_ticket",
                label="Средний чек день",
                value=float(row.avg_ticket or 0),
                unit="rub",
                status_color="blue",
                hint="Сигнал mix и качества предложения",
            ),
        ]
        week = [
            KPI(
                code="week_plan",
                label="Выполнение плана неделя",
                value=float(row.plan_pct or 0),
                unit="pct",
                py=(row.yoy or 0),
                status_color=row.status_color,
                hint="Недельный статус магазина",
            ),
            KPI(
                code="week_shop_av",
                label="Доступность ТЗ",
                value=float(row.shop_availability or 0),
                unit="pct",
                status_color=self._status(row.shop_availability or 0, 95, 90),
                hint="Топовые позиции ТЗ",
            ),
            KPI(
                code="week_prod_av",
                label="Доступность СП",
                value=float(row.production_availability or 0),
                unit="pct",
                status_color=self._status(row.production_availability or 0, 92, 85),
                hint="Топовые позиции производства",
            ),
        ]
        month = [
            KPI(
                code="month_revenue",
                label="Выручка месяц",
                value=float(row.revenue),
                unit="mln_rub",
                plan=float(row.plan or 0),
                py=float(row.py or 0),
                yoy=float(row.yoy or 0),
                status_color=row.status_color,
                hint="Главный итог месяца",
            ),
            KPI(
                code="month_share",
                label="Вес СП",
                value=float(row.own_production_share_pct or 0),
                unit="pct",
                status_color=(
                    "green"
                    if (row.own_production_share_pct or 0) > 33
                    else "yellow"
                    if (row.own_production_share_pct or 0) >= 30
                    else "red"
                ),
                hint="Структура РТО",
            ),
            KPI(
                code="month_losses",
                label="Потери",
                value=float(row.losses or 0),
                unit="mln_rub",
                delta_pct=round((row.losses or 0) / max(row.revenue, 0.01) * 100, 2),
                status_color=self._status((row.losses or 0) / max(row.revenue, 0.01) * 100, 0.8, 1.2, reverse=True),
                hint="Абсолют и % к выручке",
            ),
            KPI(
                code="month_stock",
                label="Остатки",
                value=float(row.stock_fact or 0),
                unit="mln_rub",
                plan=float(row.stock_plan or 0),
                delta_abs=round((row.stock_fact or 0) - (row.stock_plan or 0), 2),
                status_color=self._status((row.stock_fact or 0) / max((row.stock_plan or 1), 1) * 100, 100, 105, reverse=True),
                hint="Факт vs план",
            ),
        ]
        reasons = []
        if (row.plan_pct or 0) < 99:
            reasons.append("Недовыполнение плана связано с просадкой availability, доли СП и/или трафика.")
        if (row.shop_availability or 0) < 90:
            reasons.append("Низкая доступность ТЗ ограничивает базовые продажи по топовым позициям.")
        if (row.production_availability or 0) < 85:
            reasons.append("Низкая доступность производства ослабляет роль собственного производства в выручке.")
        if (row.stock_fact or 0) > (row.stock_plan or 0) * 1.05:
            reasons.append("Рост остатков указывает на риск перетарки и снижения оборачиваемости.")
        if (row.losses or 0) > row.revenue * 0.012:
            reasons.append("Потери выше порога и требуют разбора по статьям и ответственным.")
        local_risks = []
        if (row.plan_pct or 0) < 99:
            local_risks.append(
                AlertItem(
                    type="risk",
                    title="План под риском",
                    store=row.store,
                    severity="red",
                    metric="plan_pct",
                    value=float(row.plan_pct or 0),
                    comment="Магазин ниже порога выполнения плана (каталог M03)",
                )
            )
        if (row.own_production_share_pct or 0) < 30:
            local_risks.append(
                AlertItem(
                    type="risk",
                    title="Низкий вес СП",
                    store=row.store,
                    severity="red",
                    metric="own_production_share_pct",
                    value=float(row.own_production_share_pct or 0),
                    comment="СП ниже минимального управленческого порога",
                )
            )
        if (row.losses or 0) > row.revenue * 0.012:
            local_risks.append(
                AlertItem(
                    type="risk",
                    title="Высокие потери",
                    store=row.store,
                    severity="yellow",
                    metric="losses_pct",
                    value=round((row.losses or 0) / max(row.revenue, 0.01) * 100, 2),
                    comment="Потери выше допустимого уровня",
                )
            )
        return StoreDrilldown(
            store=row.store,
            summary=row,
            day_kpis=day,
            week_kpis=week,
            month_kpis=month,
            reasons=reasons or ["Существенных отклонений не выявлено."],
            local_risks=local_risks,
            actions=self.build_actions(row),
        )

    def _network_penetration(self, summary_rows: list[StoreRow]) -> tuple[float, float]:
        """Aggregate M08/M09; fall back to 0 if penetration sheet empty."""
        pen = self.raw.get("penetration_week")
        if pen is not None and not getattr(pen, "empty", True) and "Чеков всего" in getattr(pen, "columns", []):
            total = float(pd.to_numeric(pen["Чеков всего"], errors="coerce").fillna(0).sum())
            sp_c = float(pd.to_numeric(pen.get("Чеков с СП", 0), errors="coerce").fillna(0).sum()) if "Чеков с СП" in pen.columns else 0.0
            pas_c = (
                float(pd.to_numeric(pen.get("Чеков с Паскуччи", 0), errors="coerce").fillna(0).sum())
                if "Чеков с Паскуччи" in pen.columns
                else 0.0
            )
            return round(penetration_pct(sp_c, total), 1), round(penetration_pct(pas_c, total), 1)
        # No sheet → do not invent proxy from own_share (catalog forbids)
        return 0.0, 0.0

    def _losses_breakdown(self, revenue: float) -> list[LossItem]:
        """M10–M14 from списания_неделя when present."""
        wo = self.raw.get("writeoff_week")
        if wo is not None and not getattr(wo, "empty", True):
            def _sum(col: str) -> float:
                if col not in wo.columns:
                    return 0.0
                return float(pd.to_numeric(wo[col], errors="coerce").fillna(0).sum()) / 1_000_000

            groups = [
                ("ФРОФ", _sum("ФРОФ")),
                ("Паскуччи", _sum("Пасскучи")),
                ("Производство", _sum("Производство")),
                ("Потеря потр. свойств", _sum("Потеря потребительских свойств")),
            ]
            # remainder / other if Итого larger
            total = _sum("Итого")
            known = sum(a for _, a in groups)
            if total > known + 1e-9:
                groups.append(("Прочие", round(total - known, 2)))
            out = []
            for name, amount in groups:
                if amount <= 0:
                    continue
                out.append(
                    LossItem(
                        group=name,
                        amount=round(amount, 2),
                        pct_rto=round(amount / max(revenue, 0.01) * 100, 2),
                        status_color=self._status(amount / max(revenue, 0.01) * 100, 0.8, 1.2, reverse=True),
                    )
                )
            if out:
                return out
        # Empty writeoff sheet — keep structure empty rather than fake shares
        return []

    def build_dashboard(self, period="month", store: Optional[str] = None):
        rows = self.rows(period)
        if store:
            rows = [r for r in rows if r.store == store]
        summary_rows = rows if rows else self.rows(period)
        revenue = round(sum(r.revenue for r in summary_rows), 2)
        plan = round(sum((r.plan or 0) for r in summary_rows), 2)
        py = round(sum((r.py or 0) for r in summary_rows), 2)
        own_share = round(
            sum((r.revenue * (r.own_production_share_pct or 0) / 100) for r in summary_rows) / max(revenue, 0.01) * 100,
            1,
        )
        losses = round(sum((r.losses or 0) for r in summary_rows), 2)
        inventory = round(sum((r.inventory_shortage or 0) for r in summary_rows), 2)
        stock_fact = round(sum((r.stock_fact or 0) for r in summary_rows), 2)
        stock_plan = round(sum((r.stock_plan or 0) for r in summary_rows), 2)
        checks_abs = round(sum((r.checks or 0) for r in summary_rows) * 1000, 0)
        avg_ticket_v = round(sum((r.avg_ticket or 0) for r in summary_rows) / max(len(summary_rows), 1), 0)
        day_rev = revenue if period == "day" else round(revenue / 30, 2)
        day_plan = plan if period == "day" else round(plan / 30, 2)
        day_checks = checks_abs if period == "day" else round(checks_abs / 30, 0)
        week_rev = revenue if period == "week" else round(revenue / 4.3, 2)
        week_py = py if period == "week" else round(py / 4.3, 2)
        plan_pct_net = plan_completion_pct(revenue, plan) if plan else 0
        sp_pen, pas_pen = self._network_penetration(summary_rows)
        kpis = {
            "day": [
                KPI(
                    code="revenue_day",
                    label="Выручка за день",
                    value=day_rev,
                    unit="mln_rub",
                    plan=day_plan,
                    delta_pct=round((revenue / plan - 1) * 100, 1) if plan else 0,
                    status_color=status_plan_pct(plan_pct_net) if plan else "blue",
                    hint="Факт vs план",
                ),
                KPI(code="checks_day", label="Чеки", value=day_checks, unit="checks", status_color="blue", hint="Дневной поток"),
                KPI(
                    code="avg_ticket_day",
                    label="Средний чек",
                    value=avg_ticket_v,
                    unit="rub",
                    status_color="blue",
                    hint="Средний чек сети / магазина",
                ),
                KPI(
                    code="shop_availability",
                    label="Доступность ТЗ",
                    value=round(sum((r.shop_availability or 0) for r in summary_rows) / max(len(summary_rows), 1), 1),
                    unit="pct",
                    status_color=self._status(
                        sum((r.shop_availability or 0) for r in summary_rows) / max(len(summary_rows), 1), 95, 90
                    ),
                    hint="Топовые позиции ТЗ",
                ),
                KPI(
                    code="production_availability",
                    label="Доступность СП",
                    value=round(sum((r.production_availability or 0) for r in summary_rows) / max(len(summary_rows), 1), 1),
                    unit="pct",
                    status_color=self._status(
                        sum((r.production_availability or 0) for r in summary_rows) / max(len(summary_rows), 1), 92, 85
                    ),
                    hint="Топовые позиции производства",
                ),
            ],
            "week": [
                KPI(
                    code="revenue_week",
                    label="Выручка за неделю",
                    value=week_rev,
                    unit="mln_rub",
                    py=week_py,
                    yoy=round((revenue / py - 1) * 100, 1) if py else 0,
                    status_color=self._status(revenue / py * 100 if py else 0, 102, 97),
                    hint="Факт vs LY",
                ),
                KPI(
                    code="sp_penetration",
                    label="Пенетрация СП",
                    value=sp_pen,
                    unit="pct",
                    status_color=self._status(sp_pen, 33, 28),
                    hint="Чеков с СП / чеков всего (M08)",
                ),
                KPI(
                    code="pascucci_penetration",
                    label="Пенетрация Паскуччи",
                    value=pas_pen,
                    unit="pct",
                    status_color=self._status(pas_pen, 7, 5),
                    hint="Чеков с Паскуччи / чеков всего (M09)",
                ),
                KPI(
                    code="writeoff_pct",
                    label="Списания, % к РТО",
                    value=round(losses / max(revenue, 0.01) * 100, 2),
                    unit="pct",
                    status_color=self._status(losses / max(revenue, 0.01) * 100, 0.8, 1.2, reverse=True),
                    hint="Все группы потерь",
                ),
                KPI(
                    code="inventory_shortage",
                    label="Недостачи",
                    value=inventory,
                    unit="mln_rub",
                    status_color=self._status(inventory / max(revenue, 0.01) * 100, 0.15, 0.3, reverse=True),
                    hint="M29 Инвентаризация",
                ),
            ],
            "month": [
                KPI(
                    code="revenue_month",
                    label="Выручка за месяц",
                    value=revenue,
                    unit="mln_rub",
                    plan=plan,
                    py=py,
                    delta_abs=round(revenue - plan, 2),
                    delta_pct=round((revenue / plan - 1) * 100, 1) if plan else 0,
                    yoy=round((revenue / py - 1) * 100, 1) if py else 0,
                    status_color=status_plan_pct(plan_pct_net) if plan else "blue",
                    hint="Факт vs план vs LY",
                ),
                KPI(
                    code="own_production_share",
                    label="СП в РТО",
                    value=own_share,
                    unit="pct",
                    status_color=("green" if own_share > 33 else "yellow" if own_share >= 30 else "red"),
                    hint="Зеленый > 33%, желтый 30–33%, красный < 30%",
                ),
                KPI(
                    code="stock_end_month",
                    label="Остатки",
                    value=stock_fact,
                    unit="mln_rub",
                    plan=stock_plan,
                    delta_abs=round(stock_fact - stock_plan, 2),
                    delta_pct=round((stock_fact / stock_plan - 1) * 100, 1) if stock_plan else 0,
                    status_color=self._status(stock_fact / max(stock_plan, 0.01) * 100, 100, 105, reverse=True),
                    hint="Факт vs план",
                ),
                KPI(
                    code="losses_month",
                    label="Потери и списания",
                    value=losses,
                    unit="mln_rub",
                    delta_pct=round(losses / max(revenue, 0.01) * 100, 2),
                    status_color=self._status(losses / max(revenue, 0.01) * 100, 0.8, 1.2, reverse=True),
                    hint="Абсолют и % к РТО",
                ),
                KPI(
                    code="inventory_shortage_month",
                    label="Инвентаризационные недостачи",
                    value=inventory,
                    unit="mln_rub",
                    delta_pct=round(inventory / max(revenue, 0.01) * 100, 2),
                    status_color=self._status(inventory / max(revenue, 0.01) * 100, 0.15, 0.3, reverse=True),
                    hint="M29",
                ),
            ],
        }[period]
        losses_breakdown = self._losses_breakdown(revenue)
        sorted_rows = sorted(summary_rows, key=lambda r: (r.plan_pct or 0, -(r.losses or 0)), reverse=True)
        top = sorted_rows[:5]
        bottom = sorted(summary_rows, key=lambda r: ((r.plan_pct or 0), (r.losses or 0)))[:5]
        actions = []
        for row in bottom[:3]:
            actions.extend(self.build_actions(row)[:2])
        actions = actions[:6]
        alerts = []
        for row in summary_rows:
            if (row.plan_pct or 0) < 99:
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
            if (row.losses or 0) > row.revenue * 0.012:
                alerts.append(
                    AlertItem(
                        type="risk",
                        title="Высокие потери",
                        store=row.store,
                        severity="yellow",
                        metric="losses_pct",
                        value=round((row.losses or 0) / max(row.revenue, 0.01) * 100, 2),
                        comment="Потери выше допустимого уровня",
                    )
                )
            if (row.own_production_share_pct or 0) < 30:
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
        drill_target = summary_rows[0] if len(summary_rows) == 1 else (bottom[0] if bottom else None)
        drilldown = self.build_drilldown(drill_target) if drill_target else None
        charts = {
            "plan_vs_store": [{"store": r.store, "plan_pct": r.plan_pct, "status_color": r.status_color} for r in summary_rows],
            "losses_structure": [x.model_dump() for x in losses_breakdown],
            "stock_vs_plan": [{"store": r.store, "stock_fact": r.stock_fact, "stock_plan": r.stock_plan} for r in summary_rows],
            "own_prod_share": [{"store": r.store, "own_production_share_pct": r.own_production_share_pct} for r in summary_rows],
        }
        return DashboardResponse(
            period=period,
            scope="store" if store else "network",
            mode=self.mode,
            selection={"store": store, "region": None, "cluster": None},
            last_update=str(self.meta.get("Текущий день", "2026-06-22")),
            title=f"Operational Cockpit — {'Сеть' if not store else store}",
            subtitle=f"{self.meta.get('Название сети', 'Зеленое Яблоко')} · {period} · {self.mode}",
            kpis=kpis,
            alerts=alerts[:10],
            actions=actions,
            top_stores=top,
            bottom_stores=bottom,
            store_table=sorted(summary_rows, key=lambda x: x.revenue, reverse=True),
            losses=losses_breakdown,
            charts=charts,
            drilldown=drilldown,
            meta={"network": self.meta.get("Название сети", "Зеленое Яблоко"), "currency": self.meta.get("Валюта", "RUB")},
        )
