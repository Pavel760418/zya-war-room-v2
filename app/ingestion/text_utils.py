"""Утилиты нормализации текста для сопоставления имён листов и колонок.

Нормализация делает матчинг устойчивым к регистру, лишним пробелам, переносам
строк, спецсимволам и разным разделителям (`_`, `-`, пробел).
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

__all__ = ["normalize", "similarity", "best_match"]

_NON_ALNUM = re.compile(r"[^0-9a-zа-яё]+", re.IGNORECASE)


def normalize(value: object) -> str:
    """Привести произвольную строку к канонической форме для сравнения.

    Пример: ``"  Выручка\\nФАКТ "`` -> ``"выручкафакт"``.
    """
    if value is None:
        return ""
    text = str(value)
    # NFKC схлопывает совместимые символы (например, неразрывные пробелы).
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("ё", "е").replace("Ё", "Е")
    text = text.strip().lower()
    text = _NON_ALNUM.sub("", text)
    return text


def similarity(a: str, b: str) -> float:
    """Похожесть двух уже нормализованных строк в диапазоне ``0..1``."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def best_match(target: str, candidates: dict[str, str], threshold: float = 0.82):
    """Найти ключ в ``candidates`` (map normalized->original), наиболее похожий на target.

    Возвращает кортеж ``(original_value, score)`` или ``(None, 0.0)`` если ниже порога.
    """
    norm_target = normalize(target)
    if not norm_target:
        return None, 0.0
    best_key, best_score = None, 0.0
    for norm_candidate, original in candidates.items():
        score = similarity(norm_target, norm_candidate)
        if score > best_score:
            best_key, best_score = original, score
    if best_score >= threshold:
        return best_key, best_score
    return None, 0.0
