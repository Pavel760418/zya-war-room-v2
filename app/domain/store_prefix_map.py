"""Store resolution from retail receipt / shift-close document numbers.

Confirmed rule: prefix is taken from dbo._Document*._Number (nchar), before digits.
Do not duplicate long CASE chains in SQL — normalize in Python after SELECT.
"""

from __future__ import annotations

import re
from typing import Optional

# IT-confirmed prefix → display name (War Room).
STORE_PREFIX_TO_NAME: dict[str, str] = {
    "АВ": "Акушинка",
    "АК": "Акушинка",
    "ЗЯ": "БКК",
    "КС": "Каспийский",
    "ЛЕ": "Ленинград",
    "МТ": "Молоток",
    "ПИ": "Пятерочка",
    "СВ": "Северный",
    "СТ": "Сити",
    "ШМ": "Шахан 10",
    "ЭК": "Склад 107",
    "ЭН": "Экспресса",
    "РЦ": "РЦ",
}

_NAME_TO_PREFIXES: dict[str, list[str]] = {}
for _pfx, _name in STORE_PREFIX_TO_NAME.items():
    _NAME_TO_PREFIXES.setdefault(_name, []).append(_pfx)

_PREFIX_RE = re.compile(r"^([A-ZА-ЯЁ]{2})")


def extract_store_prefix(document_number: Optional[str]) -> Optional[str]:
    """Return two-letter Cyrillic/Latin prefix from 1C document number."""
    if document_number is None:
        return None
    text = str(document_number).strip()
    if not text:
        return None
    m = _PREFIX_RE.match(text.upper().replace("Ё", "Е"))
    if not m:
        return None
    return m.group(1)


def store_name_from_document_number(document_number: Optional[str]) -> str:
    """Map document number to store label; unknown prefixes are explicit."""
    prefix = extract_store_prefix(document_number)
    if not prefix:
        return "Неизвестный магазин / требуется mapping"
    known = STORE_PREFIX_TO_NAME.get(prefix)
    if known:
        return known
    return "Неизвестный магазин / требуется mapping"


def prefixes_for_store_name(store_name: str) -> list[str]:
    """Resolve filter: human store name → document number prefixes."""
    key = (store_name or "").strip()
    if not key:
        return []
    if key in _NAME_TO_PREFIXES:
        return list(_NAME_TO_PREFIXES[key])
    # Allow passing raw prefix
    if key in STORE_PREFIX_TO_NAME:
        return [key]
    return []
