from __future__ import annotations
from pathlib import Path
import pandas as pd
from .base import BaseDataRepository


class ExcelRepository(BaseDataRepository):
    def __init__(self, excel_path: Path):
        self.excel_path = excel_path

    def _read(self, sheet: str) -> pd.DataFrame:
        return pd.read_excel(self.excel_path, sheet_name=sheet)

    def load(self) -> dict:
        data = {
            "meta": self._read("meta"),
            "sales_day": self._read("продажи_день"),
            "sales_week": self._read("продажи_неделя"),
            "sales_month": self._read("продажи_месяц"),
            "availability_week": self._read("доступность_неделя"),
            "penetration_week": self._read("пенетрация_неделя"),
            "writeoff_week": self._read("списания_неделя"),
            "sp_month": self._read("сп_месяц"),
            "stock_month": self._read("остатки_месяц"),
            "expenses_month": self._read("расходы_месяц"),
            "profit_month": self._read("прибыль_месяц"),
            "losses_month": self._read("потери_месяц"),
            "targets": self._read("цели"),
        }
        return data
