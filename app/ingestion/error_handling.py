"""Слой обработки ошибок и структуры диагностических отчётов.

Идея: любой шаг ingestion может частично сломаться, но не должен ронять
приложение. Проблемы копятся в отчёте (``SheetReport`` / ``IngestionReport``),
который затем показывается пользователю в блоке диагностики.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, TypeVar

T = TypeVar("T")

__all__ = [
    "Severity",
    "Message",
    "ColumnResolution",
    "SheetReport",
    "IngestionReport",
    "safe_call",
]


class Severity(str, Enum):
    """Уровень сообщения диагностики."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class Message:
    """Одно диагностическое сообщение."""

    severity: Severity
    text: str


@dataclass
class ColumnResolution:
    """Как канонической колонке сопоставили колонку из файла."""

    canonical: str
    matched_source: Optional[str] = None
    method: str = "missing"  # 'exact' | 'alias' | 'fuzzy' | 'missing' | 'default'
    score: float = 0.0
    coerced: int = 0  # сколько значений пришлось привести к нужному типу
    filled_default: int = 0  # сколько пропусков заполнено значением по умолчанию

    @property
    def recovered(self) -> bool:
        return self.method in {"alias", "fuzzy"}

    @property
    def found(self) -> bool:
        return self.matched_source is not None


@dataclass
class SheetReport:
    """Диагностика по одному листу."""

    canonical: str
    matched_source: Optional[str] = None
    match_method: str = "missing"  # 'exact' | 'alias' | 'fuzzy' | 'missing'
    match_score: float = 0.0
    header_row: Optional[int] = None
    rows_in: int = 0
    rows_out: int = 0
    dropped_rows: int = 0
    columns: list[ColumnResolution] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.matched_source is not None

    @property
    def recovered_columns(self) -> list[ColumnResolution]:
        return [c for c in self.columns if c.recovered]

    @property
    def missing_columns(self) -> list[ColumnResolution]:
        return [c for c in self.columns if not c.found]

    def add(self, severity: Severity, text: str) -> None:
        self.messages.append(Message(severity, text))

    @property
    def status(self) -> Severity:
        if not self.found:
            return Severity.ERROR
        if any(m.severity == Severity.ERROR for m in self.messages):
            return Severity.ERROR
        if self.missing_columns or self.recovered_columns or any(
            m.severity == Severity.WARNING for m in self.messages
        ):
            return Severity.WARNING
        return Severity.SUCCESS


@dataclass
class IngestionReport:
    """Итоговый отчёт по загрузке файла."""

    filename: Optional[str] = None
    sheets_found: list[str] = field(default_factory=list)
    sheets: list[SheetReport] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    fatal: bool = False

    def add(self, severity: Severity, text: str) -> None:
        self.messages.append(Message(severity, text))

    def sheet(self, canonical: str) -> Optional[SheetReport]:
        return next((s for s in self.sheets if s.canonical == canonical), None)

    @property
    def status(self) -> Severity:
        if self.fatal:
            return Severity.ERROR
        statuses = [s.status for s in self.sheets]
        if statuses and all(s == Severity.SUCCESS for s in statuses) and not any(
            m.severity in {Severity.WARNING, Severity.ERROR} for m in self.messages
        ):
            return Severity.SUCCESS
        if any(s == Severity.ERROR for s in statuses) or any(
            m.severity == Severity.ERROR for m in self.messages
        ):
            return Severity.WARNING if not self.fatal else Severity.ERROR
        return Severity.WARNING

    @property
    def headline(self) -> str:
        """Короткий человекочитаемый статус для верхней плашки."""
        if self.fatal:
            return "Файл не удалось прочитать"
        status = self.status
        if status == Severity.SUCCESS:
            return "Файл прочитан успешно"
        return "Файл прочитан частично"


def safe_call(func: Callable[..., T], *args, default: T = None, **kwargs):
    """Выполнить ``func`` и вернуть ``(result, error_or_None)`` без исключений.

    Универсальная защитная обёртка для потенциально падающих операций.
    """
    try:
        return func(*args, **kwargs), None
    except Exception as exc:  # noqa: BLE001 — намеренно ловим всё, деградируем мягко
        return default, exc
