"""DTO-схемы дашборда.

Реализованы на стандартных ``dataclasses`` (без внешних зависимостей), чтобы
Streamlit-деплой не требовал ``pydantic``/``pydantic-core`` (Rust-сборка, которая
ломается на новых Python в Streamlit Cloud). Метод ``model_dump()`` сохранён для
обратной совместимости — и FastAPI-роуты, и Streamlit-UI вызывают его как раньше.

Все поля — keyword-only (``kw_only=True``), поэтому порядок объявления не важен, а
``MetricsService`` создаёт объекты по именованным аргументам, как и прежде.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List, Literal, Optional

StatusColor = Literal['green', 'yellow', 'red', 'blue', 'neutral']
RiskLevel = Literal['low', 'medium', 'high', 'низкий', 'средний', 'высокий']
Period = Literal['day', 'week', 'month']
Scope = Literal['network', 'store']


class _Model:
    """Общий миксин: даёт ``model_dump()`` поверх ``dataclasses.asdict`` (рекурсивно)."""

    def model_dump(self) -> dict:
        return asdict(self)  # type: ignore[arg-type]


@dataclass(kw_only=True)
class KPI(_Model):
    code: str
    label: str
    value: float
    unit: str
    status_color: StatusColor
    plan: Optional[float] = None
    py: Optional[float] = None
    delta_abs: Optional[float] = None
    delta_pct: Optional[float] = None
    yoy: Optional[float] = None
    hint: Optional[str] = None


@dataclass(kw_only=True)
class AlertItem(_Model):
    type: str
    title: str
    severity: StatusColor
    metric: str
    value: float
    store: Optional[str] = None
    comment: Optional[str] = None


@dataclass(kw_only=True)
class ActionItem(_Model):
    priority: Literal['P1', 'P2', 'P3']
    title: str
    owner: str
    eta: str
    status_color: StatusColor
    rationale: str


@dataclass(kw_only=True)
class LossItem(_Model):
    group: str
    amount: float
    pct_rto: float
    status_color: StatusColor


@dataclass(kw_only=True)
class StoreRow(_Model):
    store: str
    revenue: float
    status_color: StatusColor
    risk_level: RiskLevel
    region: Optional[str] = None
    cluster: Optional[str] = None
    format: Optional[str] = None
    plan: Optional[float] = None
    py: Optional[float] = None
    plan_pct: Optional[float] = None
    yoy: Optional[float] = None
    avg_ticket: Optional[float] = None
    checks: Optional[float] = None
    own_production_share_pct: Optional[float] = None
    shop_availability: Optional[float] = None
    production_availability: Optional[float] = None
    stock_fact: Optional[float] = None
    stock_plan: Optional[float] = None
    losses: Optional[float] = None
    inventory_shortage: Optional[float] = None


@dataclass(kw_only=True)
class StoreDrilldown(_Model):
    store: str
    summary: StoreRow
    day_kpis: List[KPI]
    week_kpis: List[KPI]
    month_kpis: List[KPI]
    reasons: List[str]
    local_risks: List[AlertItem]
    actions: List[ActionItem]
    loss_drivers: Optional[List[LossItem]] = None
    network_context: Optional[List[str]] = None


@dataclass(kw_only=True)
class DashboardResponse(_Model):
    period: Period
    scope: Scope
    mode: str
    selection: dict
    last_update: str
    title: str
    subtitle: str
    kpis: List[KPI]
    alerts: List[AlertItem]
    actions: List[ActionItem]
    top_stores: List[StoreRow]
    bottom_stores: List[StoreRow]
    store_table: List[StoreRow]
    losses: List[LossItem]
    charts: dict
    meta: dict
    drilldown: Optional[StoreDrilldown] = None


@dataclass(kw_only=True)
class FiltersResponse(_Model):
    periods: List[str]
    stores: List[str]
    regions: List[str]
    clusters: List[str]
    formats: List[str]
