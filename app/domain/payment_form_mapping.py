"""Payment forms from shift-close VT2299 → _Reference89.

IMPORTANT (confirmed limitation):
- Individual retail checks (_Document156) do NOT expose payment type in SQL.
- Payment breakdown exists only in _Document119_VT2299 (shift close).
- War Room must label these metrics as «оплаты по закрытиям смен», not per-check payment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

# Human-readable names confirmed by business/IT (match _Reference89._Description).
CONFIRMED_PAYMENT_FORM_NAMES: frozenset[str] = frozenset(
    {
        "Наличные",
        "Eurocard/mastercard",
        "Sbercard",
        "American Express",
        "Подарочный сертификат",
        "Бонусы",
        "Сертификат УКМ",
        "Безналичный расчет",
    }
)

PAYMENT_CATEGORY_CASH = "cash"
PAYMENT_CATEGORY_CARDS = "cards"
PAYMENT_CATEGORY_CASHLESS = "cashless"
PAYMENT_CATEGORY_CERTIFICATES = "certificates"
PAYMENT_CATEGORY_BONUSES = "bonuses"
PAYMENT_CATEGORY_OTHER = "other"


@dataclass(frozen=True)
class PaymentFormInfo:
    ref_bytes: bytes
    description: str
    category: str
    it_confirmed_name: bool


def _category_from_description(desc: str) -> str:
    d = (desc or "").strip().lower()
    if "налич" in d:
        return PAYMENT_CATEGORY_CASH
    if any(x in d for x in ("eurocard", "mastercard", "sbercard", "american express", "card")):
        return PAYMENT_CATEGORY_CARDS
    if "безнал" in d:
        return PAYMENT_CATEGORY_CASHLESS
    if "сертификат" in d or "подароч" in d:
        return PAYMENT_CATEGORY_CERTIFICATES
    if "бонус" in d:
        return PAYMENT_CATEGORY_BONUSES
    return PAYMENT_CATEGORY_OTHER


def build_payment_form_map(ref89_df: pd.DataFrame) -> dict[bytes, PaymentFormInfo]:
    """Build bytes → PaymentFormInfo from SELECT on dbo._Reference89."""
    out: dict[bytes, PaymentFormInfo] = {}
    if ref89_df is None or ref89_df.empty:
        return out
    for _, row in ref89_df.iterrows():
        raw = row.get("_IDRRef") or row.get("ref_id")
        if raw is None:
            continue
        b = bytes(raw) if not isinstance(raw, bytes) else raw
        desc = str(row.get("descr") or row.get("_Description") or "").strip()
        out[b] = PaymentFormInfo(
            ref_bytes=b,
            description=desc,
            category=_category_from_description(desc),
            it_confirmed_name=desc in CONFIRMED_PAYMENT_FORM_NAMES,
        )
    return out


def payment_form_label(info: Optional[PaymentFormInfo]) -> str:
    if info is None:
        return "Неизвестная форма оплаты"
    return info.description or "Неизвестная форма оплаты"
