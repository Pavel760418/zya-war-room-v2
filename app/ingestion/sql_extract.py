"""SQL extract layer: War Room sheets → MSSQL with **physical** 1C storage names.

Physical mapping source of truth:
  ``data/catalog/StrukturaKhraneniiaBazyDannykh.xlsx`` via ``metadata_catalog``.

Examples (logical → physical):
  РегистрНакопления.Продажи → ``_AccumRg6691``
  РегистрНакопления.ОстаткиТоваровКомпании / ТоварыНаСкладах → ``_AccumRg6601``
  Документ.БюджетПродаж → ``_Document107`` (+ ``_Document107_VT1803``)
  Документ.СписаниеТоваров → ``_Document172`` (+ ``_Document172_VT4675``)
  Документ.Инвентаризация → ``_Document124`` (+ ``_Document124_VT2532``)
  Документ.БюджетНакладныхРасходовИДоходов → ``_Document105`` (+ ``_Document105_VT1724``)
  Справочник.ПодразделенияКомпании (магазины) → ``_Reference64``
  Справочник.Номенклатура → ``_Reference58``

Target DBMS: Microsoft SQL Server (pymssql). Year offset for ``_Period`` / dates: 2000.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.ingestion.metadata_catalog import known_war_room_physicals, physical_table

__all__ = [
    "DBMS",
    "YEAR_OFFSET",
    "PARAM_NAMES",
    "SqlExtractQuery",
    "CATALOG_QUERIES",
    "PHYSICAL",
    "get_query",
    "list_target_sheets",
    "adapt_catalog_sql_to_mssql",
    "to_pymssql_params",
]

DBMS = "mssql"
YEAR_OFFSET = 2000

PARAM_NAMES = (
    "date_from",
    "date_to",
    "week_from",
    "week_to",
    "month_from",
    "month_to",
)

PHYSICAL = known_war_room_physicals()

# Short aliases used inside SQL builders
T_SALES = PHYSICAL["РегистрНакопления.Продажи"]  # _AccumRg6691
T_STOCK = PHYSICAL["ТоварыНаСкладах"]  # _AccumRg6601
T_BUDGET_SALES = PHYSICAL["Документ.БюджетПродаж"]
T_BUDGET_SALES_VT = PHYSICAL["Документ.БюджетПродаж.Товары"]
T_BUDGET_OPEX = PHYSICAL["Документ.БюджетНакладныхРасходовИДоходов"]
T_BUDGET_OPEX_VT = PHYSICAL["Документ.БюджетНакладныхРасходовИДоходов.РасходыИДоходы"]
T_WRITEOFF = PHYSICAL["Документ.СписаниеТоваров"]
T_WRITEOFF_VT = PHYSICAL["Документ.СписаниеТоваров.Товары"]
T_INV = PHYSICAL["Документ.Инвентаризация"]
T_INV_VT = PHYSICAL["Документ.Инвентаризация.Товары"]
T_STORE = PHYSICAL["Справочник.Магазины"]
T_NOMEN = PHYSICAL["Справочник.Номенклатура"]
T_PROFIT = PHYSICAL["ВыручкаИСебестоимостьПродаж"]  # same as sales register


@dataclass(frozen=True)
class SqlExtractQuery:
    target_sheet: str
    schema_key: str
    catalog_sheet: str
    title: str
    sql_mssql: str
    param_keys: tuple[str, ...]
    physical_tables: tuple[str, ...] = ()


def adapt_catalog_sql_to_mssql(sql: str) -> str:
    """Legacy helper kept for tests; physical queries below are already T-SQL."""
    out = sql
    out = out.replace(" = TRUE", " = 1").replace("= TRUE", "= 1")
    out = out.replace(" ILIKE ", " LIKE ")
    out = out.replace("::text", "")
    return out


def to_pymssql_params(sql: str) -> str:
    result = sql
    for name in sorted(PARAM_NAMES, key=len, reverse=True):
        result = result.replace(f":{name}", f"%({name})s")
    return result


_ISO_WEEK = (
    "CONCAT(YEAR({d}), '-W', "
    "RIGHT('0' + CAST(DATEPART(week, {d}) AS varchar(2)), 2))"
)
_SALE_DATE = f"CAST(DATEADD(year, -{YEAR_OFFSET}, t._Period) AS date)"
_DOC_DATE = f"CAST(DATEADD(year, -{YEAR_OFFSET}, d._Date_Time) AS date)"


# --- sales (Продажи = _AccumRg6691; магазины = _Reference64) ---
_SQL_SALES_DAY = f"""
-- продажи_день | РегистрНакопления.Продажи → {T_SALES}
-- Справочник.Магазины → {T_STORE} | БюджетПродаж → {T_BUDGET_SALES}/{T_BUDGET_SALES_VT}
SELECT
    {_SALE_DATE} AS [Дата],
    LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) AS [Магазин],
    SUM(CAST(t._Fld6704 AS float)) AS [Выручка факт],
    CAST(0 AS float) AS [Выручка план],
    COUNT(DISTINCT t._RecorderRRef) AS [Количество чеков]
FROM [dbo].[{T_SALES}] AS t
INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = t._Fld6692RRef
WHERE t._Active = 0x01
  AND t._Period >= DATEADD(year, {YEAR_OFFSET}, CAST(:date_from AS datetime))
  AND t._Period <  DATEADD(year, {YEAR_OFFSET}, CAST(:date_to AS datetime))
  AND s._Marked = 0x00
GROUP BY {_SALE_DATE}, LTRIM(RTRIM(CAST(s._Description AS nvarchar(255))))
ORDER BY [Дата], [Магазин];
""".strip()

_SQL_SALES_WEEK = f"""
-- продажи_неделя | {T_SALES} + {T_STORE}
SELECT
    {_ISO_WEEK.format(d=_SALE_DATE)} AS [Неделя],
    LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) AS [Магазин],
    SUM(CAST(t._Fld6704 AS float)) AS [Выручка факт],
    CAST(0 AS float) AS [Выручка план],
    COUNT(DISTINCT t._RecorderRRef) AS [Количество чеков]
FROM [dbo].[{T_SALES}] AS t
INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = t._Fld6692RRef
WHERE t._Active = 0x01
  AND t._Period >= DATEADD(year, {YEAR_OFFSET}, CAST(:week_from AS datetime))
  AND t._Period <  DATEADD(year, {YEAR_OFFSET}, CAST(:week_to AS datetime))
  AND s._Marked = 0x00
GROUP BY {_ISO_WEEK.format(d=_SALE_DATE)}, LTRIM(RTRIM(CAST(s._Description AS nvarchar(255))))
ORDER BY [Неделя], [Магазин];
""".strip()

_SQL_SALES_MONTH = f"""
-- продажи_месяц | {T_SALES} + {T_STORE}
SELECT
    FORMAT({_SALE_DATE}, 'yyyy-MM') AS [Месяц],
    LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) AS [Магазин],
    SUM(CAST(t._Fld6704 AS float)) AS [Выручка факт],
    CAST(0 AS float) AS [Выручка план],
    COUNT(DISTINCT t._RecorderRRef) AS [Количество чеков]
FROM [dbo].[{T_SALES}] AS t
INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = t._Fld6692RRef
WHERE t._Active = 0x01
  AND t._Period >= DATEADD(year, {YEAR_OFFSET}, CAST(:month_from AS datetime))
  AND t._Period <  DATEADD(year, {YEAR_OFFSET}, CAST(:month_to AS datetime))
  AND s._Marked = 0x00
GROUP BY FORMAT({_SALE_DATE}, 'yyyy-MM'), LTRIM(RTRIM(CAST(s._Description AS nvarchar(255))))
ORDER BY [Месяц], [Магазин];
""".strip()

_SQL_AVAILABILITY = f"""
-- доступность_неделя | остатки {T_STOCK} (ТоварыНаСкладах → ОстаткиТоваровКомпании)
-- Полноценная матрица ТЗ/СП в метаданных отсутствует — отдаём покрытие остатков > 0.
SELECT
    {_ISO_WEEK.format(d=f'CAST(DATEADD(year, -{YEAR_OFFSET}, t._Period) AS date)')} AS [Неделя],
    LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) AS [Магазин],
    COUNT(DISTINCT t._Fld6602RRef) AS [Топ ТЗ всего позиций],
    COUNT(DISTINCT CASE WHEN CAST(t._Fld6607 AS float) > 0 THEN t._Fld6602RRef END) AS [Топ ТЗ доступно позиций],
    COUNT(DISTINCT t._Fld6602RRef) AS [Топ СП всего позиций],
    COUNT(DISTINCT CASE WHEN CAST(t._Fld6607 AS float) > 0 THEN t._Fld6602RRef END) AS [Топ СП доступно позиций]
FROM [dbo].[{T_STOCK}] AS t
INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = t._Fld6604RRef
WHERE t._Active = 0x01
  AND t._Period >= DATEADD(year, {YEAR_OFFSET}, CAST(:week_from AS datetime))
  AND t._Period <  DATEADD(year, {YEAR_OFFSET}, CAST(:week_to AS datetime))
GROUP BY {_ISO_WEEK.format(d=f'CAST(DATEADD(year, -{YEAR_OFFSET}, t._Period) AS date)')},
         LTRIM(RTRIM(CAST(s._Description AS nvarchar(255))))
ORDER BY [Неделя], [Магазин];
""".strip()

_SQL_PENETRATION = f"""
-- пенетрация_неделя | {T_SALES} + {T_NOMEN}
SELECT
    {_ISO_WEEK.format(d=_SALE_DATE)} AS [Неделя],
    LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) AS [Магазин],
    COUNT(DISTINCT t._RecorderRRef) AS [Чеков всего],
    COUNT(DISTINCT CASE
        WHEN LOWER(CAST(n._Description AS nvarchar(255))) LIKE N'%производ%'
          OR LOWER(CAST(n._Description AS nvarchar(255))) LIKE N'%сп %'
        THEN t._RecorderRRef END) AS [Чеков с СП],
    COUNT(DISTINCT CASE
        WHEN LOWER(CAST(n._Description AS nvarchar(255))) LIKE N'%pasqucci%'
          OR LOWER(CAST(n._Description AS nvarchar(255))) LIKE N'%паскуччи%'
        THEN t._RecorderRRef END) AS [Чеков с Паскуччи]
FROM [dbo].[{T_SALES}] AS t
INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = t._Fld6692RRef
LEFT JOIN [dbo].[{T_NOMEN}] AS n ON n._IDRRef = t._Fld6693RRef
WHERE t._Active = 0x01
  AND t._Period >= DATEADD(year, {YEAR_OFFSET}, CAST(:week_from AS datetime))
  AND t._Period <  DATEADD(year, {YEAR_OFFSET}, CAST(:week_to AS datetime))
  AND s._Marked = 0x00
GROUP BY {_ISO_WEEK.format(d=_SALE_DATE)}, LTRIM(RTRIM(CAST(s._Description AS nvarchar(255))))
ORDER BY [Неделя], [Магазин];
""".strip()

_SQL_WRITEOFF = f"""
-- списания_неделя | Документ.СписаниеТоваров → {T_WRITEOFF} / {T_WRITEOFF_VT}
SELECT
    {_ISO_WEEK.format(d=_DOC_DATE)} AS [Неделя],
    LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) AS [Магазин],
    CAST(0 AS float) AS [ФРОФ],
    CAST(0 AS float) AS [Пасскучи],
    CAST(0 AS float) AS [Производство],
    CAST(0 AS float) AS [Потеря потребительских свойств],
    SUM(CAST(vt._Fld4685 AS float)) AS [Итого]
FROM [dbo].[{T_WRITEOFF}] AS d
INNER JOIN [dbo].[{T_WRITEOFF_VT}] AS vt ON vt._Document172_IDRRef = d._IDRRef
LEFT JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = d._Fld4656RRef
WHERE d._Posted = 0x01
  AND d._Date_Time >= DATEADD(year, {YEAR_OFFSET}, CAST(:week_from AS datetime))
  AND d._Date_Time <  DATEADD(year, {YEAR_OFFSET}, CAST(:week_to AS datetime))
GROUP BY {_ISO_WEEK.format(d=_DOC_DATE)}, LTRIM(RTRIM(CAST(s._Description AS nvarchar(255))))
ORDER BY [Неделя], [Магазин];
""".strip()

_SQL_LOSSES = f"""
-- потери_месяц | списания {T_WRITEOFF} + инвентаризация {T_INV}
SELECT
    FORMAT(base.[Период], 'yyyy-MM') AS [Месяц],
    base.[Магазин] AS [Магазин],
    base.[ВидПотерь] AS [Вид потерь],
    SUM(base.[Сумма]) AS [Сумма]
FROM (
    SELECT {_DOC_DATE} AS [Период],
           LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) AS [Магазин],
           N'Списания' AS [ВидПотерь],
           CAST(vt._Fld4685 AS float) AS [Сумма]
    FROM [dbo].[{T_WRITEOFF}] AS d
    INNER JOIN [dbo].[{T_WRITEOFF_VT}] AS vt ON vt._Document172_IDRRef = d._IDRRef
    LEFT JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = d._Fld4656RRef
    WHERE d._Posted = 0x01

    UNION ALL

    SELECT CAST(DATEADD(year, -{YEAR_OFFSET}, d._Date_Time) AS date) AS [Период],
           LTRIM(RTRIM(CAST(s2._Description AS nvarchar(255)))) AS [Магазин],
           N'Инвентаризация' AS [ВидПотерь],
           ABS(CAST(vt2._Fld2540 AS float)) AS [Сумма]
    FROM [dbo].[{T_INV}] AS d
    INNER JOIN [dbo].[{T_INV_VT}] AS vt2 ON vt2._Document124_IDRRef = d._IDRRef
    LEFT JOIN [dbo].[{T_STORE}] AS s2 ON s2._IDRRef = d._Fld2511RRef
    WHERE d._Posted = 0x01
) AS base
WHERE base.[Период] >= CAST(:month_from AS date)
  AND base.[Период] <  CAST(:month_to AS date)
GROUP BY FORMAT(base.[Период], 'yyyy-MM'), base.[Магазин], base.[ВидПотерь]
ORDER BY [Месяц], [Магазин], [Вид потерь];
""".strip()

_SQL_EXPENSES = f"""
-- расходы_месяц | БюджетНакладных → {T_BUDGET_OPEX} / {T_BUDGET_OPEX_VT}
SELECT
    FORMAT(CAST(DATEADD(year, -{YEAR_OFFSET}, d._Date_Time) AS date), 'yyyy-MM') AS [Месяц],
    LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) AS [Магазин],
    SUM(CAST(vt._Fld1727 AS float)) AS [ФОТ],
    CAST(0 AS float) AS [Коммунальные],
    CAST(0 AS float) AS [Маркетинг],
    CAST(0 AS float) AS [Логистика],
    CAST(0 AS float) AS [Прочие OPEX]
FROM [dbo].[{T_BUDGET_OPEX}] AS d
INNER JOIN [dbo].[{T_BUDGET_OPEX_VT}] AS vt ON vt._Document105_IDRRef = d._IDRRef
LEFT JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = d._Fld1712RRef
WHERE d._Posted = 0x01
  AND d._Date_Time >= DATEADD(year, {YEAR_OFFSET}, CAST(:month_from AS datetime))
  AND d._Date_Time <  DATEADD(year, {YEAR_OFFSET}, CAST(:month_to AS datetime))
GROUP BY FORMAT(CAST(DATEADD(year, -{YEAR_OFFSET}, d._Date_Time) AS date), 'yyyy-MM'),
         LTRIM(RTRIM(CAST(s._Description AS nvarchar(255))))
ORDER BY [Месяц], [Магазин];
""".strip()

_SQL_PROFIT = f"""
-- прибыль_месяц | ВыручкаИСебестоимостьПродаж → {T_PROFIT} (= {T_SALES})
SELECT
    FORMAT({_SALE_DATE}, 'yyyy-MM') AS [Месяц],
    LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) AS [Магазин],
    SUM(CAST(t._Fld6704 AS float) - CAST(t._Fld6708 AS float)) AS [Валовая прибыль общая],
    SUM(CAST(t._Fld6704 AS float) - CAST(t._Fld6708 AS float)) AS [Валовая прибыль ТЗ],
    CAST(0 AS float) AS [Валовая прибыль СП]
FROM [dbo].[{T_PROFIT}] AS t
INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = t._Fld6692RRef
WHERE t._Active = 0x01
  AND t._Period >= DATEADD(year, {YEAR_OFFSET}, CAST(:month_from AS datetime))
  AND t._Period <  DATEADD(year, {YEAR_OFFSET}, CAST(:month_to AS datetime))
  AND s._Marked = 0x00
GROUP BY FORMAT({_SALE_DATE}, 'yyyy-MM'), LTRIM(RTRIM(CAST(s._Description AS nvarchar(255))))
ORDER BY [Месяц], [Магазин];
""".strip()

_SQL_SP = f"""
-- сп_месяц | фильтр по номенклатуре на {T_SALES}+{T_NOMEN}
SELECT
    FORMAT({_SALE_DATE}, 'yyyy-MM') AS [Месяц],
    LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) AS [Магазин],
    SUM(CAST(t._Fld6704 AS float)) AS [Выручка СП],
    SUM(CAST(t._Fld6704 AS float) - CAST(t._Fld6708 AS float)) AS [Валовая прибыль СП]
FROM [dbo].[{T_SALES}] AS t
INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = t._Fld6692RRef
INNER JOIN [dbo].[{T_NOMEN}] AS n ON n._IDRRef = t._Fld6693RRef
WHERE t._Active = 0x01
  AND (
        LOWER(CAST(n._Description AS nvarchar(255))) LIKE N'%производ%'
     OR LOWER(CAST(n._Description AS nvarchar(255))) LIKE N'%паскуччи%'
      )
  AND t._Period >= DATEADD(year, {YEAR_OFFSET}, CAST(:month_from AS datetime))
  AND t._Period <  DATEADD(year, {YEAR_OFFSET}, CAST(:month_to AS datetime))
  AND s._Marked = 0x00
GROUP BY FORMAT({_SALE_DATE}, 'yyyy-MM'), LTRIM(RTRIM(CAST(s._Description AS nvarchar(255))))
ORDER BY [Месяц], [Магазин];
""".strip()

_SQL_STOCK = f"""
-- остатки_месяц | ТоварыНаСкладах → {T_STOCK}
SELECT
    FORMAT(CAST(DATEADD(year, -{YEAR_OFFSET}, t._Period) AS date), 'yyyy-MM') AS [Месяц],
    LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) AS [Магазин],
    SUM(CAST(t._Fld6608 AS float)) AS [Остатки на конец месяца факт],
    CAST(0 AS float) AS [Остатки на конец месяца план]
FROM [dbo].[{T_STOCK}] AS t
LEFT JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = t._Fld6604RRef
WHERE t._Active = 0x01
  AND t._Period >= DATEADD(year, {YEAR_OFFSET}, CAST(:month_from AS datetime))
  AND t._Period <  DATEADD(year, {YEAR_OFFSET}, CAST(:month_to AS datetime))
GROUP BY FORMAT(CAST(DATEADD(year, -{YEAR_OFFSET}, t._Period) AS date), 'yyyy-MM'),
         LTRIM(RTRIM(CAST(s._Description AS nvarchar(255))))
ORDER BY [Месяц], [Магазин];
""".strip()


def _q(
    target_sheet: str,
    schema_key: str,
    catalog_sheet: str,
    title: str,
    sql: str,
    params: tuple[str, ...],
    physical: tuple[str, ...] = (),
) -> SqlExtractQuery:
    return SqlExtractQuery(
        target_sheet=target_sheet,
        schema_key=schema_key,
        catalog_sheet=catalog_sheet,
        title=title,
        sql_mssql=sql,
        param_keys=params,
        physical_tables=physical,
    )


CATALOG_QUERIES: dict[str, SqlExtractQuery] = {
    "продажи_день": _q(
        "продажи_день",
        "sales_day",
        "SQL_Продажи",
        "Выручка/чеки за день",
        _SQL_SALES_DAY,
        ("date_from", "date_to"),
        (T_SALES, T_STORE, T_BUDGET_SALES, T_BUDGET_SALES_VT),
    ),
    "продажи_неделя": _q(
        "продажи_неделя",
        "sales_week",
        "SQL_Продажи",
        "Выручка/чеки за неделю",
        _SQL_SALES_WEEK,
        ("week_from", "week_to"),
        (T_SALES, T_STORE),
    ),
    "продажи_месяц": _q(
        "продажи_месяц",
        "sales_month",
        "SQL_Продажи",
        "Выручка/чеки за месяц",
        _SQL_SALES_MONTH,
        ("month_from", "month_to"),
        (T_SALES, T_STORE),
    ),
    "доступность_неделя": _q(
        "доступность_неделя",
        "availability_week",
        "SQL_Доступность_Пенетрация",
        "Доступность топ ТЗ/СП",
        _SQL_AVAILABILITY,
        ("week_from", "week_to"),
        (T_STOCK, T_STORE),
    ),
    "пенетрация_неделя": _q(
        "пенетрация_неделя",
        "penetration_week",
        "SQL_Доступность_Пенетрация",
        "Пенетрация СП и Паскуччи",
        _SQL_PENETRATION,
        ("week_from", "week_to"),
        (T_SALES, T_STORE, T_NOMEN),
    ),
    "списания_неделя": _q(
        "списания_неделя",
        "writeoff_week",
        "SQL_Списания_Потери",
        "Списания по причинам",
        _SQL_WRITEOFF,
        ("week_from", "week_to"),
        (T_WRITEOFF, T_WRITEOFF_VT, T_STORE),
    ),
    "потери_месяц": _q(
        "потери_месяц",
        "losses_month",
        "SQL_Списания_Потери",
        "Потери: списания + инвентаризация",
        _SQL_LOSSES,
        ("month_from", "month_to"),
        (T_WRITEOFF, T_WRITEOFF_VT, T_INV, T_INV_VT, T_STORE),
    ),
    "расходы_месяц": _q(
        "расходы_месяц",
        "expenses_month",
        "SQL_Финансы",
        "OPEX по статьям",
        _SQL_EXPENSES,
        ("month_from", "month_to"),
        (T_BUDGET_OPEX, T_BUDGET_OPEX_VT, T_STORE),
    ),
    "прибыль_месяц": _q(
        "прибыль_месяц",
        "profit_month",
        "SQL_Финансы",
        "Валовая прибыль общая/ТЗ/СП",
        _SQL_PROFIT,
        ("month_from", "month_to"),
        (T_PROFIT, T_STORE),
    ),
    "сп_месяц": _q(
        "сп_месяц",
        "sp_month",
        "SQL_Финансы",
        "Выручка и ВП СП",
        _SQL_SP,
        ("month_from", "month_to"),
        (T_SALES, T_STORE, T_NOMEN),
    ),
    "остатки_месяц": _q(
        "остатки_месяц",
        "stock_month",
        "SQL_Финансы",
        "Остатки конец месяца",
        _SQL_STOCK,
        ("month_from", "month_to"),
        (T_STOCK, T_STORE),
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
    key = target_sheet.strip()
    if key not in CATALOG_QUERIES:
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


# Ensure module import resolves catalog without silent logical stubs.
assert physical_table("РегистрНакопления.Продажи") == T_SALES
assert "_AccumRg" in T_SALES or T_SALES.startswith("_Accum")
assert "РегистрНакопления_Продажи" not in _SQL_SALES_DAY
assert T_SALES in _SQL_SALES_DAY
