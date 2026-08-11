"""SQL extract layer from War-Room_Katalog_Metrik_SQL.xlsx (sheets SQL_*).

Target DBMS: **Microsoft SQL Server** (pymssql), not the catalog's mixed
PostgreSQL/generic dialect. Catalog queries use logical 1C names; this module
adapts dialect + documents physical-table TODOs for Rarus/ТКПТ retail.

Parameters (bind via ``SqlDatabase.fetch_df`` / pymssql ``%s`` or named):
  :date_from / :date_to     — sales_day window [from, to)
  :week_from / :week_to     — ISO-week sheets
  :month_from / :month_to   — month sheets

Source of truth: ``War-Room_Katalog_Metrik_SQL.xlsx`` (do not invent formulas).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

__all__ = [
    "DBMS",
    "PARAM_NAMES",
    "SqlExtractQuery",
    "CATALOG_QUERIES",
    "get_query",
    "list_target_sheets",
    "adapt_catalog_sql_to_mssql",
    "to_pymssql_params",
]

# Actual project DBMS (Streamlit SQL mode / analytics).
DBMS = "mssql"

PARAM_NAMES = (
    "date_from",
    "date_to",
    "week_from",
    "week_to",
    "month_from",
    "month_to",
)


@dataclass(frozen=True)
class SqlExtractQuery:
    """One catalog query adapted for the project DBMS."""

    target_sheet: str  # Excel template / SCHEMA russian or english key
    schema_key: str  # SCHEMA canonical (sales_day, …)
    catalog_sheet: str  # SQL_Продажи | …
    title: str
    sql_mssql: str
    param_keys: tuple[str, ...]
    # Physical 1C storage names that IT must confirm against TDSheet / live DB.
    verify_1c: tuple[str, ...] = ()


def adapt_catalog_sql_to_mssql(sql: str) -> str:
    """Best-effort PG/generic → T-SQL transforms for catalog templates.

    Does **not** rewrite logical 1C object names into ``_DocumentNNN`` —
    that mapping is intentional and marked with TODO comments in each query.
    """
    out = sql
    # Boolean / ILIKE
    out = out.replace(" = TRUE", " = 1").replace("= TRUE", "= 1")
    out = out.replace(" ILIKE ", " LIKE ")
    # Postgres cast ::text inside LPAD — strip before broader rewrites
    out = out.replace("::text", "")
    # Common PG helpers → T-SQL (order matters)
    replacements = (
        ("DATE_TRUNC('week', ", "DATEADD(day, 1 - DATEPART(weekday, "),
        ("TO_CHAR(", "FORMAT("),
        (", 'YYYY-MM')", ", 'yyyy-MM')"),
        (", 'YYYY-MM'", ", 'yyyy-MM'"),
    )
    for a, b in replacements:
        out = out.replace(a, b)
    # ISO week label: keep as expression using DATEPART (catalog used EXTRACT/LPAD)
    # Callers should prefer the baked CATALOG_QUERIES below rather than raw adapt.
    return out


def to_pymssql_params(sql: str) -> str:
    """Convert ``:name`` placeholders to ``%(name)s`` for pymssql."""
    result = sql
    for name in sorted(PARAM_NAMES, key=len, reverse=True):
        result = result.replace(f":{name}", f"%({name})s")
    return result


# ---------------------------------------------------------------------------
# Adapted queries (MSSQL). Logical names kept; physical mapping = TODO.
# ---------------------------------------------------------------------------

_ISO_WEEK = (
    "CONCAT(DATEPART(isoyear, {d}), '-W', "
    "RIGHT('0' + CAST(DATEPART(isoww, {d}) AS varchar(2)), 2))"
)

# --- sales ---
_SQL_SALES_DAY = f"""
-- Лист: продажи_день (каталог SQL_Продажи)
-- TODO: verify against real 1C metadata — РегистрНакопления.Продажи
--   physical candidate in this DB: dbo._AccumRg6691 (Продажи) OR checks dbo._Document156
-- TODO: verify against real 1C metadata — Справочник.Магазины → dbo._Reference64
-- TODO: verify against real 1C metadata — Документ.БюджетПродаж / Document107.VT1803
SELECT
    CAST(p.[Дата] AS date) AS [Дата],
    s.[Наименование] AS [Магазин],
    SUM(p.[Сумма]) AS [Выручка факт],
    SUM(pb.[СуммаПлан]) AS [Выручка план],
    COUNT(DISTINCT p.[НомерЧека]) AS [Количество чеков]
FROM [РегистрНакопления_Продажи] AS p
INNER JOIN [Справочник_Магазины] AS s ON s.[Ссылка] = p.[Магазин]
LEFT JOIN [БюджетПродаж_Товары] AS pb
       ON pb.[Магазин] = p.[Магазин]
      AND pb.[Период] = CAST(p.[Дата] AS date)
WHERE p.[Дата] >= :date_from AND p.[Дата] < :date_to
GROUP BY CAST(p.[Дата] AS date), s.[Наименование]
ORDER BY [Дата], [Магазин];
""".strip()

_SQL_SALES_WEEK = f"""
-- Лист: продажи_неделя (каталог SQL_Продажи)
-- TODO: verify against real 1C metadata — same objects as продажи_день
SELECT
    {_ISO_WEEK.format(d='p.[Дата]')} AS [Неделя],
    s.[Наименование] AS [Магазин],
    SUM(p.[Сумма]) AS [Выручка факт],
    SUM(pb.[СуммаПлан]) AS [Выручка план],
    COUNT(DISTINCT p.[НомерЧека]) AS [Количество чеков]
FROM [РегистрНакопления_Продажи] AS p
INNER JOIN [Справочник_Магазины] AS s ON s.[Ссылка] = p.[Магазин]
LEFT JOIN [БюджетПродаж_Товары] AS pb
       ON pb.[Магазин] = p.[Магазин]
      AND DATEPART(isoyear, pb.[Период]) = DATEPART(isoyear, p.[Дата])
      AND DATEPART(isoww, pb.[Период]) = DATEPART(isoww, p.[Дата])
WHERE p.[Дата] >= :week_from AND p.[Дата] < :week_to
GROUP BY {_ISO_WEEK.format(d='p.[Дата]')}, s.[Наименование]
ORDER BY [Неделя], [Магазин];
""".strip()

_SQL_SALES_MONTH = """
-- Лист: продажи_месяц (каталог SQL_Продажи)
-- TODO: verify against real 1C metadata — Document107 БюджетПродаж for plan side
SELECT
    FORMAT(p.[Дата], 'yyyy-MM') AS [Месяц],
    s.[Наименование] AS [Магазин],
    SUM(p.[Сумма]) AS [Выручка факт],
    SUM(pb.[СуммаПлан]) AS [Выручка план],
    COUNT(DISTINCT p.[НомерЧека]) AS [Количество чеков]
FROM [РегистрНакопления_Продажи] AS p
INNER JOIN [Справочник_Магазины] AS s ON s.[Ссылка] = p.[Магазин]
LEFT JOIN [БюджетПродаж_Товары] AS pb
       ON pb.[Магазин] = p.[Магазин]
      AND FORMAT(pb.[Период], 'yyyy-MM') = FORMAT(p.[Дата], 'yyyy-MM')
WHERE p.[Дата] >= :month_from AND p.[Дата] < :month_to
GROUP BY FORMAT(p.[Дата], 'yyyy-MM'), s.[Наименование]
ORDER BY [Месяц], [Магазин];
""".strip()

_SQL_AVAILABILITY = f"""
-- Лист: доступность_неделя (каталог SQL_Доступность_Пенетрация)
-- TODO: verify against real 1C metadata — ассортиментная матрица / топ-листы ТЗ и СП
-- TODO: verify against real 1C metadata — РегистрНакопления.ТоварыНаСкладах
--   physical candidate: dbo._AccumRg6601 (ОстаткиТоваровКомпании)
WITH top_tz AS (
    SELECT [Номенклатура]
    FROM [Справочник_АссортиментнаяМатрица]
    WHERE [Группа] = N'ТЗ_Топ'
),
top_sp AS (
    SELECT [Номенклатура]
    FROM [Справочник_АссортиментнаяМатрица]
    WHERE [Группа] = N'СП_Топ'
)
SELECT
    {_ISO_WEEK.format(d='r.[Период]')} AS [Неделя],
    s.[Наименование] AS [Магазин],
    (SELECT COUNT(*) FROM top_tz) AS [Топ ТЗ всего позиций],
    COUNT(DISTINCT CASE
        WHEN r.[Номенклатура] IN (SELECT [Номенклатура] FROM top_tz)
         AND r.[КоличествоОстаток] > 0 THEN r.[Номенклатура] END) AS [Топ ТЗ доступно позиций],
    (SELECT COUNT(*) FROM top_sp) AS [Топ СП всего позиций],
    COUNT(DISTINCT CASE
        WHEN r.[Номенклатура] IN (SELECT [Номенклатура] FROM top_sp)
         AND r.[КоличествоОстаток] > 0 THEN r.[Номенклатура] END) AS [Топ СП доступно позиций]
FROM [РегистрНакопления_ТоварыНаСкладах] AS r
INNER JOIN [Справочник_Магазины] AS s ON s.[Ссылка] = r.[Магазин]
WHERE r.[Период] >= :week_from AND r.[Период] < :week_to
GROUP BY {_ISO_WEEK.format(d='r.[Период]')}, s.[Наименование]
ORDER BY [Неделя], [Магазин];
""".strip()

_SQL_PENETRATION = f"""
-- Лист: пенетрация_неделя (каталог SQL_Доступность_Пенетрация)
-- M08 = Чеков_с_СП / Чеков_всего; M09 = Чеков_с_Паскуччи / Чеков_всего
-- TODO: verify against real 1C metadata — НоменклатурнаяГруппа 'Собственное производство'
-- TODO: verify against real 1C metadata — filter Pasqucci / Паскуччи on nomenclature
SELECT
    {_ISO_WEEK.format(d='p.[Дата]')} AS [Неделя],
    s.[Наименование] AS [Магазин],
    COUNT(DISTINCT p.[НомерЧека]) AS [Чеков всего],
    COUNT(DISTINCT CASE
        WHEN n.[НоменклатурнаяГруппа] = N'Собственное производство'
        THEN p.[НомерЧека] END) AS [Чеков с СП],
    COUNT(DISTINCT CASE
        WHEN LOWER(n.[Наименование]) LIKE N'%pasqucci%'
          OR LOWER(n.[Наименование]) LIKE N'%паскуччи%'
        THEN p.[НомерЧека] END) AS [Чеков с Паскуччи]
FROM [РегистрНакопления_Продажи] AS p
INNER JOIN [Справочник_Магазины] AS s ON s.[Ссылка] = p.[Магазин]
INNER JOIN [Справочник_Номенклатура] AS n ON n.[Ссылка] = p.[Номенклатура]
WHERE p.[Дата] >= :week_from AND p.[Дата] < :week_to
GROUP BY {_ISO_WEEK.format(d='p.[Дата]')}, s.[Наименование]
ORDER BY [Неделя], [Магазин];
""".strip()

_SQL_WRITEOFF = f"""
-- Лист: списания_неделя (каталог SQL_Списания_Потери)
-- TODO: verify against real 1C metadata — Document172 + VT4675 (confirmed candidate)
-- TODO: verify against real 1C metadata — реквизит ПричинаСписания / справочник причин
SELECT
    {_ISO_WEEK.format(d='d.[Дата]')} AS [Неделя],
    s.[Наименование] AS [Магазин],
    SUM(CASE WHEN d.[ПричинаСписания] = N'ФРОФ' THEN t.[Сумма] END) AS [ФРОФ],
    SUM(CASE WHEN d.[ПричинаСписания] = N'Паскуччи' THEN t.[Сумма] END) AS [Пасскучи],
    SUM(CASE WHEN d.[ПричинаСписания] = N'Производство' THEN t.[Сумма] END) AS [Производство],
    SUM(CASE WHEN d.[ПричинаСписания] = N'ПотеряПотребительскихСвойств'
             THEN t.[Сумма] END) AS [Потеря потребительских свойств],
    SUM(t.[Сумма]) AS [Итого]
FROM [Документ_СписаниеТоваров] AS d
INNER JOIN [Документ_СписаниеТоваров_Товары] AS t ON t.[Ссылка] = d.[Ссылка]
INNER JOIN [Справочник_Магазины] AS s ON s.[Ссылка] = d.[Магазин]
WHERE d.[Дата] >= :week_from AND d.[Дата] < :week_to
  AND d.[Проведен] = 1
GROUP BY {_ISO_WEEK.format(d='d.[Дата]')}, s.[Наименование]
ORDER BY [Неделя], [Магазин];
""".strip()

_SQL_LOSSES = """
-- Лист: потери_месяц (каталог SQL_Списания_Потери)
-- M28 вид='Списания'; M29 вид='Инвентаризация'
-- TODO: verify against real 1C metadata — Document172 СписаниеТоваров
-- TODO: verify against real 1C metadata — Document124 ИнвентаризацияТоваров (не DocumentChngR*)
SELECT
    FORMAT(base.[Период], 'yyyy-MM') AS [Месяц],
    base.[Магазин] AS [Магазин],
    base.[ВидПотерь] AS [Вид потерь],
    SUM(base.[Сумма]) AS [Сумма]
FROM (
    SELECT d.[Дата] AS [Период], s.[Наименование] AS [Магазин],
           N'Списания' AS [ВидПотерь], t.[Сумма] AS [Сумма]
    FROM [Документ_СписаниеТоваров] AS d
    INNER JOIN [Документ_СписаниеТоваров_Товары] AS t ON t.[Ссылка] = d.[Ссылка]
    INNER JOIN [Справочник_Магазины] AS s ON s.[Ссылка] = d.[Магазин]
    WHERE d.[Проведен] = 1

    UNION ALL

    SELECT inv.[Дата] AS [Период], s2.[Наименование] AS [Магазин],
           N'Инвентаризация' AS [ВидПотерь], inv.[СуммаОтклонения] AS [Сумма]
    FROM [Документ_ИнвентаризацияТоваров] AS inv
    INNER JOIN [Справочник_Магазины] AS s2 ON s2.[Ссылка] = inv.[Магазин]
    WHERE inv.[Проведен] = 1
) AS base
WHERE base.[Период] >= :month_from AND base.[Период] < :month_to
GROUP BY FORMAT(base.[Период], 'yyyy-MM'), base.[Магазин], base.[ВидПотерь]
ORDER BY [Месяц], [Магазин], [Вид потерь];
""".strip()

_SQL_EXPENSES = """
-- Лист: расходы_месяц (каталог SQL_Финансы) — M19..M23
-- TODO: verify against real 1C metadata — Document105 БюджетНакладныхРасходовИДоходов + VT1724
SELECT
    FORMAT(b.[Период], 'yyyy-MM') AS [Месяц],
    s.[Наименование] AS [Магазин],
    SUM(CASE WHEN a.[СтатьяРасхода] = N'ФОТ' THEN ri.[Сумма] END) AS [ФОТ],
    SUM(CASE WHEN a.[СтатьяРасхода] = N'Коммунальные' THEN ri.[Сумма] END) AS [Коммунальные],
    SUM(CASE WHEN a.[СтатьяРасхода] = N'Маркетинг' THEN ri.[Сумма] END) AS [Маркетинг],
    SUM(CASE WHEN a.[СтатьяРасхода] = N'Логистика' THEN ri.[Сумма] END) AS [Логистика],
    SUM(CASE WHEN a.[СтатьяРасхода] NOT IN (N'ФОТ', N'Коммунальные', N'Маркетинг', N'Логистика')
             THEN ri.[Сумма] END) AS [Прочие OPEX]
FROM [Документ_БюджетНакладныхРасходовИДоходов] AS b
INNER JOIN [Документ_БюджетНакладныхРасходовИДоходов_РасходыИДоходы] AS ri
        ON ri.[Ссылка] = b.[Ссылка]
INNER JOIN [Справочник_СтатьиРасходов] AS a ON a.[Ссылка] = ri.[СтатьяРасхода]
INNER JOIN [Справочник_Магазины] AS s ON s.[Ссылка] = b.[Магазин]
WHERE b.[Период] >= :month_from AND b.[Период] < :month_to
GROUP BY FORMAT(b.[Период], 'yyyy-MM'), s.[Наименование]
ORDER BY [Месяц], [Магазин];
""".strip()

_SQL_PROFIT = """
-- Лист: прибыль_месяц (каталог SQL_Финансы) — M24..M26
-- TODO: verify against real 1C metadata — РегистрНакопления.ВыручкаИСебестоимостьПродаж
--   physical candidate: dbo._AccumRg6691 (_Fld6704 revenue, _Fld6708 COGS)
SELECT
    FORMAT(v.[Период], 'yyyy-MM') AS [Месяц],
    s.[Наименование] AS [Магазин],
    SUM(v.[Выручка] - v.[Себестоимость]) AS [Валовая прибыль общая],
    SUM(CASE WHEN n.[НоменклатурнаяГруппа] <> N'Собственное производство'
             THEN v.[Выручка] - v.[Себестоимость] END) AS [Валовая прибыль ТЗ],
    SUM(CASE WHEN n.[НоменклатурнаяГруппа] = N'Собственное производство'
             THEN v.[Выручка] - v.[Себестоимость] END) AS [Валовая прибыль СП]
FROM [РегистрНакопления_ВыручкаИСебестоимостьПродаж] AS v
INNER JOIN [Справочник_Магазины] AS s ON s.[Ссылка] = v.[Магазин]
INNER JOIN [Справочник_Номенклатура] AS n ON n.[Ссылка] = v.[Номенклатура]
WHERE v.[Период] >= :month_from AND v.[Период] < :month_to
GROUP BY FORMAT(v.[Период], 'yyyy-MM'), s.[Наименование]
ORDER BY [Месяц], [Магазин];
""".strip()

_SQL_SP = """
-- Лист: сп_месяц (каталог SQL_Финансы) — M15, M16
-- TODO: verify against real 1C metadata — filter НоменклатурнаяГруппа = 'Собственное производство'
SELECT
    FORMAT(v.[Период], 'yyyy-MM') AS [Месяц],
    s.[Наименование] AS [Магазин],
    SUM(v.[Выручка]) AS [Выручка СП],
    SUM(v.[Выручка] - v.[Себестоимость]) AS [Валовая прибыль СП]
FROM [РегистрНакопления_ВыручкаИСебестоимостьПродаж] AS v
INNER JOIN [Справочник_Магазины] AS s ON s.[Ссылка] = v.[Магазин]
INNER JOIN [Справочник_Номенклатура] AS n ON n.[Ссылка] = v.[Номенклатура]
WHERE n.[НоменклатурнаяГруппа] = N'Собственное производство'
  AND v.[Период] >= :month_from AND v.[Период] < :month_to
GROUP BY FORMAT(v.[Период], 'yyyy-MM'), s.[Наименование]
ORDER BY [Месяц], [Магазин];
""".strip()

_SQL_STOCK = """
-- Лист: остатки_месяц (каталог SQL_Финансы) — M17, M18
-- TODO: verify against real 1C metadata — РегистрНакопления.ТоварыНаСкладах → dbo._AccumRg6601
-- TODO: verify against real 1C metadata — БюджетОстатков (optional plan)
SELECT
    FORMAT(r.[Период], 'yyyy-MM') AS [Месяц],
    s.[Наименование] AS [Магазин],
    SUM(r.[СуммаОстаток]) AS [Остатки на конец месяца факт],
    SUM(pb.[СуммаПлан]) AS [Остатки на конец месяца план]
FROM [РегистрНакопления_ТоварыНаСкладах] AS r
INNER JOIN [Справочник_Магазины] AS s ON s.[Ссылка] = r.[Магазин]
LEFT JOIN [БюджетОстатков] AS pb
       ON pb.[Магазин] = r.[Магазин]
      AND FORMAT(pb.[Период], 'yyyy-MM') = FORMAT(r.[Период], 'yyyy-MM')
WHERE r.[Период] = (
    SELECT MAX(r2.[Период])
    FROM [РегистрНакопления_ТоварыНаСкладах] AS r2
    WHERE FORMAT(r2.[Период], 'yyyy-MM') = FORMAT(r.[Период], 'yyyy-MM')
)
GROUP BY FORMAT(r.[Период], 'yyyy-MM'), s.[Наименование]
ORDER BY [Месяц], [Магазин];
""".strip()


def _q(
    target_sheet: str,
    schema_key: str,
    catalog_sheet: str,
    title: str,
    sql: str,
    params: tuple[str, ...],
    verify: tuple[str, ...] = (),
) -> SqlExtractQuery:
    return SqlExtractQuery(
        target_sheet=target_sheet,
        schema_key=schema_key,
        catalog_sheet=catalog_sheet,
        title=title,
        sql_mssql=sql,
        param_keys=params,
        verify_1c=verify,
    )


CATALOG_QUERIES: dict[str, SqlExtractQuery] = {
    "продажи_день": _q(
        "продажи_день",
        "sales_day",
        "SQL_Продажи",
        "Выручка/чеки за день",
        _SQL_SALES_DAY,
        ("date_from", "date_to"),
        ("РегистрНакопления.Продажи", "Document107 БюджетПродаж", "Справочник.Магазины"),
    ),
    "продажи_неделя": _q(
        "продажи_неделя",
        "sales_week",
        "SQL_Продажи",
        "Выручка/чеки за неделю",
        _SQL_SALES_WEEK,
        ("week_from", "week_to"),
        ("РегистрНакопления.Продажи", "Document107 БюджетПродаж"),
    ),
    "продажи_месяц": _q(
        "продажи_месяц",
        "sales_month",
        "SQL_Продажи",
        "Выручка/чеки за месяц",
        _SQL_SALES_MONTH,
        ("month_from", "month_to"),
        ("РегистрНакопления.Продажи", "Document107 БюджетПродаж"),
    ),
    "доступность_неделя": _q(
        "доступность_неделя",
        "availability_week",
        "SQL_Доступность_Пенетрация",
        "Доступность топ ТЗ/СП",
        _SQL_AVAILABILITY,
        ("week_from", "week_to"),
        ("АссортиментнаяМатрица", "ТоварыНаСкладах/_AccumRg6601"),
    ),
    "пенетрация_неделя": _q(
        "пенетрация_неделя",
        "penetration_week",
        "SQL_Доступность_Пенетрация",
        "Пенетрация СП и Паскуччи",
        _SQL_PENETRATION,
        ("week_from", "week_to"),
        ("НоменклатурнаяГруппа СП", "фильтр Паскуччи"),
    ),
    "списания_неделя": _q(
        "списания_неделя",
        "writeoff_week",
        "SQL_Списания_Потери",
        "Списания по причинам",
        _SQL_WRITEOFF,
        ("week_from", "week_to"),
        ("Document172/VT4675", "ПричинаСписания"),
    ),
    "потери_месяц": _q(
        "потери_месяц",
        "losses_month",
        "SQL_Списания_Потери",
        "Потери: списания + инвентаризация",
        _SQL_LOSSES,
        ("month_from", "month_to"),
        ("Document172", "Document124 ИнвентаризацияТоваров", "СуммаОтклонения"),
    ),
    "расходы_месяц": _q(
        "расходы_месяц",
        "expenses_month",
        "SQL_Финансы",
        "OPEX по статьям",
        _SQL_EXPENSES,
        ("month_from", "month_to"),
        ("Document105/VT1724", "СтатьиРасходов"),
    ),
    "прибыль_месяц": _q(
        "прибыль_месяц",
        "profit_month",
        "SQL_Финансы",
        "Валовая прибыль общая/ТЗ/СП",
        _SQL_PROFIT,
        ("month_from", "month_to"),
        ("ВыручкаИСебестоимостьПродаж/_AccumRg6691",),
    ),
    "сп_месяц": _q(
        "сп_месяц",
        "sp_month",
        "SQL_Финансы",
        "Выручка и ВП СП",
        _SQL_SP,
        ("month_from", "month_to"),
        ("фильтр Собственное производство",),
    ),
    "остатки_месяц": _q(
        "остатки_месяц",
        "stock_month",
        "SQL_Финансы",
        "Остатки конец месяца",
        _SQL_STOCK,
        ("month_from", "month_to"),
        ("ТоварыНаСкладах/_AccumRg6601", "БюджетОстатков"),
    ),
}


def list_target_sheets() -> list[str]:
    return list(CATALOG_QUERIES.keys())


def get_query(
    target_sheet: str,
    *,
    params: Optional[dict[str, Any]] = None,
    pymssql_style: bool = True,
) -> tuple[str, dict[str, Any]]:
    """Return ``(sql, bind_params)`` for a War Room template sheet.

    Raises ``KeyError`` if ``target_sheet`` is unknown.
    """
    key = target_sheet.strip()
    if key not in CATALOG_QUERIES:
        # Allow SCHEMA english keys
        for q in CATALOG_QUERIES.values():
            if q.schema_key == key:
                key = q.target_sheet
                break
    query = CATALOG_QUERIES[key]
    sql = query.sql_mssql
    if pymssql_style:
        sql = to_pymssql_params(sql)
    bind = {k: (params or {}).get(k) for k in query.param_keys}
    return sql, bind
