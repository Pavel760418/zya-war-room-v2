"""Классификация статей списания по эталону ТКПТ_потери.pbix / ТКПТ_обзор.pbix.

СТ Статьи С (имена как в отчёте PBI) → группы War Room.
"""
from __future__ import annotations

# Обзор KPI «1РТО С» / карточка Списания — только эти две статьи (DAX IN {...}).
COMMODITY_WRITEOFF_ARTICLES: tuple[str, ...] = (
    "Потеря потребительских свойств",
    "Списание овощи и фрукты",
)

# Явно исключены из «Списаний» (товарных) → блок «Расходы».
EXPENSE_ARTICLES: tuple[str, ...] = (
    "Обед персонала",
    "Представительские расходы",
)

# Полный справочник СТ Статьи С из ТКПТ_потери.pbix (порядок как в модели).
ALL_WRITEOFF_ARTICLES: tuple[str, ...] = (
    "Потеря потребительских свойств",
    "Обед персонала",
    "Представительские расходы",
    "Списание за счет виновных лиц",
    "Списание КД",
    "Перетаривание и перевод в сырьё",
    "БРАК",
    "Форс-мажор",
    "Списание овощи и фрукты",
    "Списание по нормам естественной убыли",
    "Дегустация (бракераж)",
    "Списание обнаруженной недостачи ТМЦ",
    "Спецакции и Мероприятия",
    "Проработка",
    "Хоз нужды",
)

GROUP_COMMODITY = "Списания"
GROUP_EXPENSE = "Расходы"
GROUP_OTHER = "Прочие статьи списания"
GROUP_INVENTORY = "Недостачи (инвентаризация)"
GROUP_SURPLUS = "Оприходование излишков"
GROUP_RTO_S = "РТО С"  # все статьи списания (колонка Спи в ТКПТ)


def classify_article(article: str) -> str:
    name = (article or "").strip()
    if name in COMMODITY_WRITEOFF_ARTICLES:
        return GROUP_COMMODITY
    if name in EXPENSE_ARTICLES:
        return GROUP_EXPENSE
    if name:
        return GROUP_OTHER
    return GROUP_OTHER


def is_commodity_writeoff(article: str) -> bool:
    return (article or "").strip() in COMMODITY_WRITEOFF_ARTICLES


def is_expense(article: str) -> bool:
    return (article or "").strip() in EXPENSE_ARTICLES
