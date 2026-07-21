from __future__ import annotations
import random
from datetime import date

class DemoRepository:
    def __init__(self, seed: int = 42, stores_count: int = 24):
        self.random = random.Random(seed)
        self.stores_count = stores_count

    def load(self) -> dict:
        stores = []
        for i in range(1, self.stores_count + 1):
            tier = 'flagship' if i <= 3 else 'stable' if i <= 9 else 'mid' if i <= 17 else 'problem' if i <= 22 else 'critical'
            base = {
                'flagship': (150, 104, 35, 96, 93, 0.75, 58),
                'stable': (110, 101, 32, 94, 90, 0.95, 46),
                'mid': (88, 98, 30, 92, 87, 1.15, 38),
                'problem': (63, 93, 27, 88, 82, 1.55, 29),
                'critical': (44, 86, 24, 84, 76, 2.10, 20),
            }[tier]
            revenue, plan_pct, own_share, shop_av, prod_av, losses_pct, stock = base
            revenue *= self.random.uniform(0.88, 1.12)
            plan_pct += self.random.uniform(-3.8, 3.5)
            own_share += self.random.uniform(-3.5, 3.2)
            shop_av += self.random.uniform(-4.5, 3.0)
            prod_av += self.random.uniform(-5.0, 3.0)
            losses_pct += self.random.uniform(-0.22, 0.26)
            stock *= self.random.uniform(0.9, 1.15)
            plan = revenue / max(plan_pct / 100, 0.01)
            py = revenue / self.random.uniform(0.95, 1.09)
            checks = revenue * self.random.uniform(930, 1220)
            avg_ticket = revenue * 1_000_000 / checks
            stores.append({
                'store': f'Магазин {i:02d}',
                'region': 'Дагестан',
                'cluster': f'Кластер {1 + (i-1)//6}',
                'format': 'Супермаркет',
                'revenue': round(revenue, 2),
                'plan': round(plan, 2),
                'py': round(py, 2),
                'plan_pct': round(plan_pct, 1),
                'yoy': round((revenue / py - 1) * 100, 1),
                'checks': round(checks / 1000, 1),
                'avg_ticket': round(avg_ticket),
                'own_production_share_pct': round(own_share, 1),
                'shop_availability': round(shop_av, 1),
                'production_availability': round(prod_av, 1),
                'stock_fact': round(stock, 2),
                'stock_plan': round(stock * self.random.uniform(0.9, 1.0), 2),
                'losses': round(revenue * losses_pct / 100, 2),
                'inventory_shortage': round(revenue * losses_pct / 100 * self.random.uniform(0.18, 0.32), 2),
            })
        return {
            'meta': {'Название сети': 'Зеленое Яблоко', 'Текущий день': str(date(2026, 6, 22)), 'Валюта': 'RUB'},
            'stores': stores
        }
