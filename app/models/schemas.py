from typing import List, Optional, Literal
from pydantic import BaseModel

StatusColor = Literal['green','yellow','red','blue','neutral']
RiskLevel = Literal['low','medium','high']
Period = Literal['day','week','month']
Scope = Literal['network','store']

class KPI(BaseModel):
    code: str
    label: str
    value: float
    unit: str
    plan: Optional[float] = None
    py: Optional[float] = None
    delta_abs: Optional[float] = None
    delta_pct: Optional[float] = None
    yoy: Optional[float] = None
    status_color: StatusColor
    hint: Optional[str] = None

class AlertItem(BaseModel):
    type: str
    title: str
    store: Optional[str] = None
    severity: StatusColor
    metric: str
    value: float
    comment: Optional[str] = None

class ActionItem(BaseModel):
    priority: Literal['P1','P2','P3']
    title: str
    owner: str
    eta: str
    status_color: StatusColor
    rationale: str

class LossItem(BaseModel):
    group: str
    amount: float
    pct_rto: float
    status_color: StatusColor

class StoreRow(BaseModel):
    store: str
    region: Optional[str] = None
    cluster: Optional[str] = None
    format: Optional[str] = None
    revenue: float
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
    status_color: StatusColor
    risk_level: RiskLevel

class StoreDrilldown(BaseModel):
    store: str
    summary: StoreRow
    day_kpis: List[KPI]
    week_kpis: List[KPI]
    month_kpis: List[KPI]
    reasons: List[str]
    local_risks: List[AlertItem]
    actions: List[ActionItem]

class DashboardResponse(BaseModel):
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
    drilldown: Optional[StoreDrilldown] = None
    meta: dict

class FiltersResponse(BaseModel):
    periods: List[str]
    stores: List[str]
    regions: List[str]
    clusters: List[str]
    formats: List[str]
