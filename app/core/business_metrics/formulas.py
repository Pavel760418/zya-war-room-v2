"""KPI formulas from War-Room_Katalog_Metrik_SQL.xlsx → лист «Метрики» (M01–M29).

Single source of truth for calculation / traffic-light thresholds used by
``app.services.metrics_service.MetricsService``. Do not fork formulas in UI.
"""
from __future__ import annotations

__all__ = [
    "METRIC_CATALOG",
    "plan_completion_pct",
    "avg_ticket",
    "availability_pct",
    "penetration_pct",
    "gross_margin_pct",
    "own_production_share_pct",
    "status_plan_pct",
    "status_higher_is_better",
    "status_lower_is_better",
    "PLAN_GREEN",
    "PLAN_YELLOW",
    "GROSS_MARGIN_GREEN",
]


# M03 traffic light from catalog: green ≥100%, yellow ≥99%, red <98%
PLAN_GREEN = 100.0
PLAN_YELLOW = 99.0

# M27: green ≥30%, red <0% (цель 30%)
GROSS_MARGIN_GREEN = 30.0

METRIC_CATALOG: dict[str, dict[str, str]] = {
    "M01": {"name": "Выручка факт", "formula": "SUM(Выручка_факт)"},
    "M02": {"name": "Выручка план", "formula": "из бюджета продаж (План)"},
    "M03": {"name": "Выполнение плана продаж, %", "formula": "Выручка_факт / Выручка_план"},
    "M04": {"name": "Количество чеков", "formula": "COUNT(чеков)"},
    "M05": {"name": "Средний чек", "formula": "Выручка_факт / Количество_чеков"},
    "M06": {"name": "Доступность Топ ТЗ, %", "formula": "Топ_ТЗ_доступно / Топ_ТЗ_всего"},
    "M07": {"name": "Доступность Топ СП, %", "formula": "Топ_СП_доступно / Топ_СП_всего"},
    "M08": {"name": "Пенетрация СП, %", "formula": "Чеков_с_СП / Чеков_всего"},
    "M09": {"name": "Пенетрация Паскуччи, %", "formula": "Чеков_с_Паскуччи / Чеков_всего"},
    "M10": {"name": "Списания ФРОФ", "formula": "SUM(Списания) ФРОФ"},
    "M11": {"name": "Списания СП (Паскуччи)", "formula": "SUM(Списания) Пасскучи"},
    "M12": {"name": "Списания Производство", "formula": "SUM(Списания) Производство"},
    "M13": {"name": "Потеря потребительских свойств", "formula": "SUM по причине"},
    "M14": {"name": "Итого списания", "formula": "SUM всех причин"},
    "M15": {"name": "Выручка СП (месяц)", "formula": "SUM(Выручка_СП)"},
    "M16": {"name": "Валовая прибыль СП", "formula": "SUM(Выручка_СП) - SUM(Себестоимость_СП)"},
    "M17": {"name": "Остатки факт", "formula": "SUM(Остатки)"},
    "M18": {"name": "Остатки план", "formula": "из бюджета остатков"},
    "M19": {"name": "ФОТ", "formula": "SUM(Расходы) вид=ФОТ"},
    "M20": {"name": "Коммунальные", "formula": "SUM(Расходы) вид=Коммунальные"},
    "M21": {"name": "Маркетинг", "formula": "SUM(Расходы) вид=Маркетинг"},
    "M22": {"name": "Логистика", "formula": "SUM(Расходы) вид=Логистика"},
    "M23": {"name": "Прочие OPEX", "formula": "SUM(Расходы) вид=Прочие"},
    "M24": {"name": "Валовая прибыль общая", "formula": "Выручка_общая - Себестоимость_общая"},
    "M25": {"name": "Валовая прибыль ТЗ", "formula": "ВП_общая - ВП_СП"},
    "M26": {"name": "Валовая прибыль СП", "formula": "из сп_месяц"},
    "M27": {"name": "Валовая прибыль, %", "formula": "Валовая_прибыль_общая / Выручка_общая"},
    "M28": {"name": "Потери: Списания", "formula": "SUM вид=Списания"},
    "M29": {"name": "Потери: Инвентаризация", "formula": "SUM вид=Инвентаризация"},
}


def _f(x: object, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def plan_completion_pct(revenue_fact: float, revenue_plan: float) -> float:
    """M03: Выручка_факт / Выручка_план * 100."""
    plan = _f(revenue_plan)
    if plan <= 0:
        return 0.0
    return _f(revenue_fact) / plan * 100.0


def avg_ticket(revenue_fact: float, checks: float) -> float:
    """M05: Выручка_факт / Количество_чеков."""
    c = _f(checks)
    if c <= 0:
        return 0.0
    return _f(revenue_fact) / c


def availability_pct(available: float, total: float) -> float:
    """M06 / M07."""
    t = _f(total)
    if t <= 0:
        return 0.0
    return _f(available) / t * 100.0


def penetration_pct(checks_with: float, checks_total: float) -> float:
    """M08 / M09."""
    t = _f(checks_total)
    if t <= 0:
        return 0.0
    return _f(checks_with) / t * 100.0


def gross_margin_pct(gross_profit: float, revenue: float) -> float:
    """M27."""
    r = _f(revenue)
    if r <= 0:
        return 0.0
    return _f(gross_profit) / r * 100.0


def own_production_share_pct(sp_revenue: float, total_revenue: float) -> float:
    """Share of SP in RTO (dashboard weight metric; related to M15/M01)."""
    r = _f(total_revenue)
    if r <= 0:
        return 0.0
    return _f(sp_revenue) / r * 100.0


def status_plan_pct(value: float) -> str:
    """Catalog M03: green ≥100, yellow ≥99, else red."""
    v = _f(value)
    if v >= PLAN_GREEN:
        return "green"
    if v >= PLAN_YELLOW:
        return "yellow"
    return "red"


def status_higher_is_better(value: float, green: float, yellow: float) -> str:
    v = _f(value)
    if v >= green:
        return "green"
    if v >= yellow:
        return "yellow"
    return "red"


def status_lower_is_better(value: float, green: float, yellow: float) -> str:
    v = _f(value)
    if v <= green:
        return "green"
    if v <= yellow:
        return "yellow"
    return "red"
