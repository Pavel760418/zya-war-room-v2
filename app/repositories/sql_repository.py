from .base import BaseDataRepository


class SqlRepository(BaseDataRepository):
    def load(self) -> dict:
        raise NotImplementedError("SQL / 1С repository подключается тем же контрактом, что и ExcelRepository")
