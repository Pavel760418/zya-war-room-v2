"""Устойчивый слой загрузки, маппинга и валидации Excel для War Room.

Модули:
- ``schema``         — централизованный словарь канонических листов/колонок и алиасов.
- ``error_handling`` — структуры отчётов и безопасные обёртки.
- ``excel_loader``   — data_loading: открытие workbook, поиск заголовков, чистка.
- ``data_mapping``   — сопоставление листов и колонок по алиасам.
- ``data_validation``— приведение типов, проверка обязательных полей, quality-report.
- ``pipeline``       — оркестратор, возвращает ``raw`` dict (совместим с ``MetricsService``) + отчёт.
- ``sample_inputs``  — генерация тестовых/битых фикстур.
"""

from app.ingestion.pipeline import ingest_excel, IngestionResult

__all__ = ["ingest_excel", "IngestionResult"]
