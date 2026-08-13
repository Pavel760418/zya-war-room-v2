"""SQL extract layer: War Room sheets → MSSQL with **physical** 1C storage names.

Physical mapping source of truth:
  ``data/catalog/StrukturaKhraneniiaBazyDannykh.xlsx`` via ``metadata_catalog``.

Confirmed mappings (catalog + live SELECT):
  РегистрНакопления.Продажи → ``_AccumRg6691`` (номенклатурная выручка / СП%)
  Розничные чеки/выручка смены → ``_Document119`` + ``_Document119_VT2313``
    (Документ.ЗакрытиеСмены.СнятыеКассы: ``_Fld2319``=число чеков, ``_Fld6977``=выручка кассы;
     магазин ``_Fld2267RRef``→``_Reference64``)
  НЕ использовать ``_Document156`` для чеков — это ПоступлениеТоваров (REJECTED)
  Статьи списания → ``_Document172._Fld4669RRef``→``_Reference82``
  Остатки → ``_AccumRg6601`` (склад ``_Fld6603RRef``→``_Reference76``)
  Свойства номенклатуры → ``_InfoRg5758`` + ``_Chrc339``
  Списание → ``_Document172`` / ``_Document172_VT4675``
  Инвентаризация → ``_Document124`` / ``_Document124_VT2532``
  Папка СП → ``_Reference58`` код ``00107646`` («Производство Зеленого яблока»)

Target DBMS: Microsoft SQL Server (pymssql). Year offset: 2000.
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
    "SP_FOLDER_CODE",
    "PROP_TZ",
    "PROP_SP",
    "NON_STORE_NAMES",
]

DBMS = "mssql"
YEAR_OFFSET = 2000
SP_FOLDER_CODE = "00107646"
PROP_TZ = "Корзина Топ 200"
PROP_SP = "Корзина Производство"
NON_STORE_NAMES = (
    "РЦ",
    "Ритейл",
    "Ритейл (мини)",
    "Все товары",
    "Фабрика-кухня",
)

PARAM_NAMES = (
    "date_from",
    "date_to",
    "week_from",
    "week_to",
    "month_from",
    "month_to",
)

PHYSICAL = known_war_room_physicals()

T_SALES = PHYSICAL["РегистрНакопления.Продажи"]
T_STOCK = PHYSICAL["ТоварыНаСкладах"]
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
T_PROFIT = PHYSICAL["ВыручкаИСебестоимостьПродаж"]
T_SHIFT = PHYSICAL.get("Документ.ЗакрытиеСмены", "_Document119")
T_SHIFT_CASH = PHYSICAL.get("Документ.ЗакрытиеСмены.СнятыеКассы", "_Document119_VT2313")
T_SHIFT_GOODS = PHYSICAL.get("Документ.ЗакрытиеСмены.Товары", "_Document119_VT2284")
T_CHECKS = T_SHIFT  # alias for sales/check extract
T_EXPENSE_ITEMS = PHYSICAL.get("Справочник.СтатьиДоходовИРасходов", "_Reference82")
T_WAREHOUSE = PHYSICAL.get("Справочник.Склады", "_Reference76")
T_PROPS = PHYSICAL.get("РегистрСведений.ЗначенияСвойствОбъектов", "_InfoRg5758")
T_PROP_KINDS = PHYSICAL.get("ПланВидовХарактеристик.СвойстваОбъектов", "_Chrc339")
T_STOCK_TOTALS = PHYSICAL.get(
    "РегистрНакопления.ОстаткиТоваровКомпании.Остатки",
    "_AccumRgT6616",
)


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
_CHECK_DATE = f"CAST(DATEADD(year, -{YEAR_OFFSET}, d._Date_Time) AS date)"
_STORE_FROM_CHECK = "LTRIM(RTRIM(CAST(s._Description AS nvarchar(255))))"
_STORE_FILTER = (
    f"AND s._Marked = 0x00 "
    f"AND {_STORE_FROM_CHECK} NOT IN ("
    + ", ".join(f"N'{n}'" for n in NON_STORE_NAMES)
    + ") "
    f"AND {_STORE_FROM_CHECK} NOT LIKE N'РЦ %' "
    f"AND {_STORE_FROM_CHECK} NOT LIKE N'не исп%'"
)
_WH_TO_STORE = (
    "LTRIM(RTRIM(CAST(s._Description AS nvarchar(255))))"
)
# Склад → магазин через _Reference76._Fld1140RRef (подтверждено SELECT)
_WH_JOIN_STORE = f"""
INNER JOIN [dbo].[{T_WAREHOUSE}] AS w ON w._IDRRef = t._Fld6603RRef
INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = w._Fld1140RRef
""".strip()
_SP_NOMEN_CTE = f"""
roots AS (
  SELECT _IDRRef FROM [dbo].[{T_NOMEN}]
  WHERE LTRIM(RTRIM(CAST(_Code AS nvarchar(50)))) = N'{SP_FOLDER_CODE}'
),
lvl1 AS (
  SELECT c._IDRRef FROM [dbo].[{T_NOMEN}] c
  INNER JOIN roots r ON c._ParentIDRRef = r._IDRRef WHERE c._Marked = 0x00
),
lvl2 AS (
  SELECT c._IDRRef FROM [dbo].[{T_NOMEN}] c
  INNER JOIN lvl1 r ON c._ParentIDRRef = r._IDRRef WHERE c._Marked = 0x00
),
lvl3 AS (
  SELECT c._IDRRef FROM [dbo].[{T_NOMEN}] c
  INNER JOIN lvl2 r ON c._ParentIDRRef = r._IDRRef WHERE c._Marked = 0x00
),
sp_nomen AS (
  SELECT _IDRRef FROM roots
  UNION SELECT _IDRRef FROM lvl1
  UNION SELECT _IDRRef FROM lvl2
  UNION SELECT _IDRRef FROM lvl3
)
""".strip()

_SQL_SALES_DAY = f"""
-- продажи_день | ЗакрытиеСмены {T_SHIFT} + СнятыеКассы {T_SHIFT_CASH}
-- _Fld2319 = число чеков кассы (VERIFIED), _Fld6977 = выручка кассы
-- магазин = _Fld2267RRef → {T_STORE}
SELECT
    {_CHECK_DATE} AS [Дата],
    {_STORE_FROM_CHECK} AS [Магазин],
    SUM(CAST(vt._Fld6977 AS float)) AS [Выручка факт],
    CAST(0 AS float) AS [Выручка план],
    SUM(CAST(vt._Fld2319 AS float)) AS [Количество чеков]
FROM [dbo].[{T_SHIFT}] AS d
INNER JOIN [dbo].[{T_SHIFT_CASH}] AS vt ON vt._Document119_IDRRef = d._IDRRef
INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = d._Fld2267RRef
WHERE d._Posted = 0x01
  AND d._Date_Time >= DATEADD(year, {YEAR_OFFSET}, CAST(:date_from AS datetime))
  AND d._Date_Time <  DATEADD(year, {YEAR_OFFSET}, CAST(:date_to AS datetime))
  {_STORE_FILTER}
GROUP BY {_CHECK_DATE}, {_STORE_FROM_CHECK}
ORDER BY [Дата], [Магазин];
""".strip()

_SQL_SALES_WEEK = f"""
SELECT
    {_ISO_WEEK.format(d=_CHECK_DATE)} AS [Неделя],
    {_STORE_FROM_CHECK} AS [Магазин],
    SUM(CAST(vt._Fld6977 AS float)) AS [Выручка факт],
    CAST(0 AS float) AS [Выручка план],
    SUM(CAST(vt._Fld2319 AS float)) AS [Количество чеков]
FROM [dbo].[{T_SHIFT}] AS d
INNER JOIN [dbo].[{T_SHIFT_CASH}] AS vt ON vt._Document119_IDRRef = d._IDRRef
INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = d._Fld2267RRef
WHERE d._Posted = 0x01
  AND d._Date_Time >= DATEADD(year, {YEAR_OFFSET}, CAST(:week_from AS datetime))
  AND d._Date_Time <  DATEADD(year, {YEAR_OFFSET}, CAST(:week_to AS datetime))
  {_STORE_FILTER}
GROUP BY {_ISO_WEEK.format(d=_CHECK_DATE)}, {_STORE_FROM_CHECK}
ORDER BY [Неделя], [Магазин];
""".strip()

_SQL_SALES_MONTH = f"""
SELECT
    FORMAT({_CHECK_DATE}, 'yyyy-MM') AS [Месяц],
    {_STORE_FROM_CHECK} AS [Магазин],
    SUM(CAST(vt._Fld6977 AS float)) AS [Выручка факт],
    CAST(0 AS float) AS [Выручка план],
    SUM(CAST(vt._Fld2319 AS float)) AS [Количество чеков]
FROM [dbo].[{T_SHIFT}] AS d
INNER JOIN [dbo].[{T_SHIFT_CASH}] AS vt ON vt._Document119_IDRRef = d._IDRRef
INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = d._Fld2267RRef
WHERE d._Posted = 0x01
  AND d._Date_Time >= DATEADD(year, {YEAR_OFFSET}, CAST(:month_from AS datetime))
  AND d._Date_Time <  DATEADD(year, {YEAR_OFFSET}, CAST(:month_to AS datetime))
  {_STORE_FILTER}
GROUP BY FORMAT({_CHECK_DATE}, 'yyyy-MM'), {_STORE_FROM_CHECK}
ORDER BY [Месяц], [Магазин];
""".strip()

_NON = ", ".join(f"N'{n}'" for n in NON_STORE_NAMES)
# Нетто-остаток ниже порога = шум float / встречные движения, не «есть на полке».
_AVAIL_QTY_EPS = "0.001"
_AVAIL_STORE_OK = (
    f"{_WH_TO_STORE} NOT IN ({_NON}) "
    f"AND {_WH_TO_STORE} NOT LIKE N'РЦ%' "
    f"AND {_WH_TO_STORE} NOT LIKE N'не исп%' "
    f"AND s._Marked = 0x00"
)
_AVAIL_CTE = f"""
basket_tz AS (
  SELECT DISTINCT r._Fld5759_RRRef AS nomen
  FROM [dbo].[{T_PROPS}] AS r
  INNER JOIN [dbo].[{T_PROP_KINDS}] AS p ON p._IDRRef = r._Fld5760RRef
  WHERE p._Description = N'{PROP_TZ}' AND CAST(r._Fld5761_L AS int) = 1
),
basket_sp AS (
  SELECT DISTINCT r._Fld5759_RRRef AS nomen
  FROM [dbo].[{T_PROPS}] AS r
  INNER JOIN [dbo].[{T_PROP_KINDS}] AS p ON p._IDRRef = r._Fld5760RRef
  WHERE p._Description = N'{PROP_SP}' AND CAST(r._Fld5761_L AS int) = 1
),
basket AS (
  SELECT nomen, N'ТЗ' AS basket FROM basket_tz
  UNION
  SELECT nomen, N'СП' FROM basket_sp
),
wh AS (
  SELECT
    w._IDRRef AS warehouse,
    {_WH_TO_STORE} AS store_name
  FROM [dbo].[{T_WAREHOUSE}] AS w
  INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = w._Fld1140RRef
  WHERE {_AVAIL_STORE_OK}
),
bal AS (
  SELECT
    t._Fld6602RRef AS nomen,
    t._Fld6603RRef AS warehouse,
    SUM(CASE WHEN t._RecordKind = 0 THEN CAST(t._Fld6607 AS float)
             ELSE -CAST(t._Fld6607 AS float) END) AS qty
  FROM [dbo].[{T_STOCK}] AS t
  WHERE t._Active = 0x01
    AND t._Period < DATEADD(year, {YEAR_OFFSET}, CAST(:week_to AS datetime))
    AND t._Period >= DATEADD(year, {YEAR_OFFSET}, DATEADD(day, -120, CAST(:week_to AS datetime)))
    AND t._Fld6602RRef IN (SELECT nomen FROM basket)
  GROUP BY t._Fld6602RRef, t._Fld6603RRef
),
store_qty AS (
  SELECT
    wh.store_name,
    bal.nomen,
    SUM(bal.qty) AS qty
  FROM wh
  INNER JOIN bal ON bal.warehouse = wh.warehouse
  GROUP BY wh.store_name, bal.nomen
),
sold_sp AS (
  SELECT
    {_WH_TO_STORE} AS store_name,
    t._Fld6693RRef AS nomen,
    SUM(CAST(t._Fld6707 AS float)) AS amt
  FROM [dbo].[{T_SALES}] AS t
  INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = t._Fld6692RRef
  WHERE {_AVAIL_STORE_OK}
    AND t._Period >= DATEADD(year, {YEAR_OFFSET}, CAST(:week_from AS datetime))
    AND t._Period <  DATEADD(year, {YEAR_OFFSET}, CAST(:week_to AS datetime))
    AND t._Fld6693RRef IN (SELECT nomen FROM basket_sp)
  GROUP BY {_WH_TO_STORE}, t._Fld6693RRef
  HAVING SUM(CAST(t._Fld6707 AS float)) > {_AVAIL_QTY_EPS}
)
""".strip()

_SQL_AVAILABILITY = f"""
-- ТЗ: SKU корзины с нетто-остатком на конец периода > {_AVAIL_QTY_EPS}.
-- СП: SKU корзины с продажами за период (week_from…week_to).
WITH {_AVAIL_CTE},
avail_stores AS (
  SELECT DISTINCT store_name FROM store_qty
  UNION
  SELECT DISTINCT store_name FROM sold_sp
)
SELECT
    {_ISO_WEEK.format(d='CAST(DATEADD(day, -1, CAST(:week_to AS date)) AS date)')} AS [Неделя],
    a.store_name AS [Магазин],
    (SELECT COUNT(*) FROM basket_tz) AS [Топ ТЗ всего позиций],
    (
      SELECT COUNT(DISTINCT sq.nomen)
      FROM store_qty AS sq
      INNER JOIN basket_tz AS tz ON tz.nomen = sq.nomen
      WHERE sq.store_name = a.store_name AND sq.qty > {_AVAIL_QTY_EPS}
    ) AS [Топ ТЗ доступно позиций],
    (SELECT COUNT(*) FROM basket_sp) AS [Топ СП всего позиций],
    (
      SELECT COUNT(DISTINCT ssp.nomen)
      FROM sold_sp AS ssp
      WHERE ssp.store_name = a.store_name
    ) AS [Топ СП доступно позиций]
FROM avail_stores AS a
ORDER BY [Магазин];
""".strip()

_SQL_AVAILABILITY_SKU = f"""
-- ТЗ: флаг по остатку. СП: флаг по продажам за период.
WITH {_AVAIL_CTE},
stores AS (
  SELECT {_WH_TO_STORE} AS store_name
  FROM [dbo].[{T_STORE}] AS s
  WHERE {_AVAIL_STORE_OK}
)
SELECT
    stores.store_name AS [Магазин],
    LTRIM(RTRIM(CAST(n._Code AS nvarchar(50)))) AS [Артикул],
    LTRIM(RTRIM(CAST(n._Description AS nvarchar(255)))) AS [Номенклатура],
    basket.basket AS [Корзина],
    CAST(ISNULL(store_qty.qty, 0) AS float) AS [Остаток],
    CAST(ISNULL(sold_sp.amt, 0) AS float) AS [Продажи],
    CAST(
      CASE
        WHEN basket.basket = N'ТЗ' AND ISNULL(store_qty.qty, 0) > {_AVAIL_QTY_EPS} THEN 1
        WHEN basket.basket = N'СП' AND ISNULL(sold_sp.amt, 0) > {_AVAIL_QTY_EPS} THEN 1
        ELSE 0
      END AS int
    ) AS [В наличии]
FROM stores
CROSS JOIN basket
LEFT JOIN [dbo].[{T_NOMEN}] AS n ON n._IDRRef = basket.nomen
LEFT JOIN store_qty
  ON store_qty.store_name = stores.store_name
 AND store_qty.nomen = basket.nomen
LEFT JOIN sold_sp
  ON sold_sp.store_name = stores.store_name
 AND sold_sp.nomen = basket.nomen
ORDER BY [Магазин], [Корзина], [Номенклатура];
""".strip()

_SQL_AVAILABILITY_SP_DAY = f"""
-- Ежедневные продажи SKU корзины СП — для пересчёта доступности СП в выбранном периоде.
WITH basket_sp AS (
  SELECT DISTINCT r._Fld5759_RRRef AS nomen
  FROM [dbo].[{T_PROPS}] AS r
  INNER JOIN [dbo].[{T_PROP_KINDS}] AS p ON p._IDRRef = r._Fld5760RRef
  WHERE p._Description = N'{PROP_SP}' AND CAST(r._Fld5761_L AS int) = 1
)
SELECT
    CAST(DATEADD(year, -{YEAR_OFFSET}, t._Period) AS date) AS [Дата],
    {_WH_TO_STORE} AS [Магазин],
    LTRIM(RTRIM(CAST(n._Code AS nvarchar(50)))) AS [Артикул],
    LTRIM(RTRIM(CAST(n._Description AS nvarchar(255)))) AS [Номенклатура],
    SUM(CAST(t._Fld6707 AS float)) AS [Продажи]
FROM [dbo].[{T_SALES}] AS t
INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = t._Fld6692RRef
INNER JOIN basket_sp AS b ON b.nomen = t._Fld6693RRef
INNER JOIN [dbo].[{T_NOMEN}] AS n ON n._IDRRef = t._Fld6693RRef
WHERE {_AVAIL_STORE_OK}
  AND t._Period >= DATEADD(year, {YEAR_OFFSET}, CAST(:date_from AS datetime))
  AND t._Period <  DATEADD(year, {YEAR_OFFSET}, CAST(:date_to AS datetime))
GROUP BY
    CAST(DATEADD(year, -{YEAR_OFFSET}, t._Period) AS date),
    {_WH_TO_STORE},
    LTRIM(RTRIM(CAST(n._Code AS nvarchar(50)))),
    LTRIM(RTRIM(CAST(n._Description AS nvarchar(255))))
HAVING SUM(CAST(t._Fld6707 AS float)) > {_AVAIL_QTY_EPS}
ORDER BY [Дата], [Магазин], [Артикул];
""".strip()

_SQL_PENETRATION = f"""
-- M08/M09: чеки из СнятыеКассы; доля СП/Паскуччи по Товары смены (_Document119_VT2284)
-- Прямой COUNT DISTINCT чеков с Паскуччи НЕВОЗМОЖЕН: VT2284 = агрегат SKU за смену, без ID чека.
-- Оценка: checks_total * (sum_amt_pas / sum_amt_all) по _Fld2295 (= кассовая выручка смены).
WITH {_SP_NOMEN_CTE},
pas_nomen AS (
  SELECT _IDRRef FROM [dbo].[{T_NOMEN}]
  WHERE _Description LIKE N'%Паскучч%' OR _Description LIKE N'%Pascucc%'
),
shift_docs AS (
  SELECT
    d._IDRRef AS doc_ref,
    {_CHECK_DATE} AS sale_date,
    {_STORE_FROM_CHECK} AS store_name,
    SUM(CAST(vt._Fld2319 AS float)) AS checks_total
  FROM [dbo].[{T_SHIFT}] AS d
  INNER JOIN [dbo].[{T_SHIFT_CASH}] AS vt ON vt._Document119_IDRRef = d._IDRRef
  INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = d._Fld2267RRef
  WHERE d._Posted = 0x01
    AND d._Date_Time >= DATEADD(year, {YEAR_OFFSET}, CAST(:date_from AS datetime))
    AND d._Date_Time <  DATEADD(year, {YEAR_OFFSET}, CAST(:date_to AS datetime))
    {_STORE_FILTER}
  GROUP BY d._IDRRef, {_CHECK_DATE}, {_STORE_FROM_CHECK}
),
goods AS (
  SELECT
    g._Document119_IDRRef AS doc_ref,
    SUM(CAST(g._Fld2295 AS float)) AS rev_total,
    SUM(CASE WHEN sp._IDRRef IS NOT NULL THEN CAST(g._Fld2295 AS float) ELSE 0 END) AS rev_sp,
    SUM(CASE WHEN pas._IDRRef IS NOT NULL THEN CAST(g._Fld2295 AS float) ELSE 0 END) AS rev_pas
  FROM [dbo].[{T_SHIFT_GOODS}] AS g
  INNER JOIN shift_docs AS sd ON sd.doc_ref = g._Document119_IDRRef
  LEFT JOIN sp_nomen AS sp ON sp._IDRRef = g._Fld2286RRef
  LEFT JOIN pas_nomen AS pas ON pas._IDRRef = g._Fld2286RRef
  GROUP BY g._Document119_IDRRef
)
SELECT
    c.sale_date AS [Дата],
    {_ISO_WEEK.format(d='c.sale_date')} AS [Неделя],
    c.store_name AS [Магазин],
    CAST(SUM(c.checks_total) AS float) AS [Чеков всего],
    CAST(ROUND(SUM(c.checks_total * CASE WHEN g.rev_total > 0 THEN g.rev_sp / g.rev_total ELSE 0 END), 0) AS float)
      AS [Чеков с СП],
    CAST(ROUND(SUM(c.checks_total * CASE WHEN g.rev_total > 0 THEN g.rev_pas / g.rev_total ELSE 0 END), 0) AS float)
      AS [Чеков с Паскуччи]
FROM shift_docs AS c
LEFT JOIN goods AS g ON g.doc_ref = c.doc_ref
GROUP BY c.sale_date, c.store_name
ORDER BY [Дата], [Магазин];
""".strip()


# Магазин списания: _Fld4658RRef→_Reference64 (VERIFIED; _Fld4656RRef не магазин)
_SQL_WRITEOFF = f"""
-- списания по статьям _Reference82 (_Fld4669RRef), по дням
SELECT
    {_DOC_DATE} AS [Дата],
    {_STORE_FROM_CHECK} AS [Магазин],
    LTRIM(RTRIM(CAST(a._Description AS nvarchar(255)))) AS [Статья списания],
    SUM(CAST(vt._Fld4685 AS float)) AS [Сумма]
FROM [dbo].[{T_WRITEOFF}] AS d
INNER JOIN [dbo].[{T_WRITEOFF_VT}] AS vt ON vt._Document172_IDRRef = d._IDRRef
INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = d._Fld4658RRef
LEFT JOIN [dbo].[{T_EXPENSE_ITEMS}] AS a ON a._IDRRef = d._Fld4669RRef
WHERE d._Posted = 0x01
  AND d._Marked = 0x00
  AND d._Date_Time >= DATEADD(year, {YEAR_OFFSET}, CAST(:date_from AS datetime))
  AND d._Date_Time <  DATEADD(year, {YEAR_OFFSET}, CAST(:date_to AS datetime))
  {_STORE_FILTER}
GROUP BY {_DOC_DATE}, {_STORE_FROM_CHECK},
         LTRIM(RTRIM(CAST(a._Description AS nvarchar(255))))
ORDER BY [Дата], [Магазин], [Сумма] DESC;
""".strip()

# Инвентаризация: магазин _Fld2513RRef; недостача = ABS(_Fld2523) один раз на документ
_SQL_LOSSES = f"""
-- Без задвоения: списания = SUM(VT) на документ (статья в шапке); недостачи = hdr без JOIN VT
SELECT
    base.[Период] AS [Дата],
    base.[Магазин] AS [Магазин],
    base.[ВидПотерь] AS [Вид потерь],
    SUM(base.[Сумма]) AS [Сумма]
FROM (
    SELECT {_DOC_DATE} AS [Период],
           {_STORE_FROM_CHECK} AS [Магазин],
           LTRIM(RTRIM(CAST(a._Description AS nvarchar(255)))) AS [ВидПотерь],
           (
             SELECT SUM(CAST(vt._Fld4685 AS float))
             FROM [dbo].[{T_WRITEOFF_VT}] AS vt
             WHERE vt._Document172_IDRRef = d._IDRRef
           ) AS [Сумма]
    FROM [dbo].[{T_WRITEOFF}] AS d
    INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = d._Fld4658RRef
    LEFT JOIN [dbo].[{T_EXPENSE_ITEMS}] AS a ON a._IDRRef = d._Fld4669RRef
    WHERE d._Posted = 0x01
      AND d._Marked = 0x00
      AND d._Date_Time >= DATEADD(year, {YEAR_OFFSET}, CAST(:date_from AS datetime))
      AND d._Date_Time <  DATEADD(year, {YEAR_OFFSET}, CAST(:date_to AS datetime))
      {_STORE_FILTER}

    UNION ALL

    SELECT CAST(DATEADD(year, -{YEAR_OFFSET}, d._Date_Time) AS date) AS [Период],
           LTRIM(RTRIM(CAST(s2._Description AS nvarchar(255)))) AS [Магазин],
           N'Инвентаризация' AS [ВидПотерь],
           CASE WHEN CAST(d._Fld2523 AS float) < 0
                THEN ABS(CAST(d._Fld2523 AS float)) ELSE 0 END AS [Сумма]
    FROM [dbo].[{T_INV}] AS d
    INNER JOIN [dbo].[{T_STORE}] AS s2 ON s2._IDRRef = d._Fld2513RRef
    WHERE d._Posted = 0x01
      AND d._Marked = 0x00
      AND d._Date_Time >= DATEADD(year, {YEAR_OFFSET}, CAST(:date_from AS datetime))
      AND d._Date_Time <  DATEADD(year, {YEAR_OFFSET}, CAST(:date_to AS datetime))
      AND s2._Marked = 0x00
      AND LTRIM(RTRIM(CAST(s2._Description AS nvarchar(255)))) NOT IN ({_NON})
      AND LTRIM(RTRIM(CAST(s2._Description AS nvarchar(255)))) NOT LIKE N'РЦ%'
) AS base
WHERE base.[Магазин] IS NOT NULL
  AND base.[Сумма] IS NOT NULL
  AND base.[Сумма] <> 0
GROUP BY base.[Период], base.[Магазин], base.[ВидПотерь]
ORDER BY [Дата], [Магазин], [Вид потерь];
""".strip()

_SQL_EXPENSES = f"""
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
WITH {_SP_NOMEN_CTE}
SELECT
    FORMAT({_SALE_DATE}, 'yyyy-MM') AS [Месяц],
    LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) AS [Магазин],
    SUM(CASE WHEN sp._IDRRef IS NOT NULL THEN CAST(t._Fld6704 AS float) ELSE 0 END) AS [Выручка СП],
    SUM(CAST(t._Fld6704 AS float)) AS [Выручка всего],
    SUM(CASE WHEN sp._IDRRef IS NOT NULL THEN CAST(t._Fld6704 AS float) - CAST(t._Fld6708 AS float) ELSE 0 END)
      AS [Валовая прибыль СП]
FROM [dbo].[{T_SALES}] AS t
INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = t._Fld6692RRef
LEFT JOIN sp_nomen AS sp ON sp._IDRRef = t._Fld6693RRef
WHERE t._Active = 0x01
  AND t._Period >= DATEADD(year, {YEAR_OFFSET}, CAST(:month_from AS datetime))
  AND t._Period <  DATEADD(year, {YEAR_OFFSET}, CAST(:month_to AS datetime))
  AND s._Marked = 0x00
GROUP BY FORMAT({_SALE_DATE}, 'yyyy-MM'), LTRIM(RTRIM(CAST(s._Description AS nvarchar(255))))
ORDER BY [Месяц], [Магазин];
""".strip()

_SQL_STOCK = f"""
-- Снимок из итогов _AccumRgT6616 (не net-flow за 120 дней по _AccumRg6601)
SELECT
    FORMAT(DATEADD(day, -1, CAST(:month_to AS date)), 'yyyy-MM') AS [Месяц],
    {_WH_TO_STORE} AS [Магазин],
    SUM(CAST(t._Fld6608 AS float)) AS [Остатки на конец месяца факт],
    CAST(0 AS float) AS [Остатки на конец месяца план]
FROM [dbo].[{T_STOCK_TOTALS}] AS t
INNER JOIN [dbo].[{T_WAREHOUSE}] AS w ON w._IDRRef = t._Fld6603RRef
INNER JOIN [dbo].[{T_STORE}] AS s ON s._IDRRef = w._Fld1140RRef
WHERE t._Period = DATEADD(
        year,
        {YEAR_OFFSET},
        CAST(DATEFROMPARTS(
          YEAR(CAST(:month_to AS date)),
          MONTH(CAST(:month_to AS date)),
          1
        ) AS datetime)
      )
  AND {_WH_TO_STORE} NOT IN ({_NON})
  AND {_WH_TO_STORE} NOT LIKE N'РЦ%'
  AND s._Marked = 0x00
GROUP BY {_WH_TO_STORE}
ORDER BY [Магазин];
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
        (T_SHIFT, T_SHIFT_CASH, T_STORE),
    ),
    "продажи_неделя": _q(
        "продажи_неделя",
        "sales_week",
        "SQL_Продажи",
        "Выручка/чеки за неделю",
        _SQL_SALES_WEEK,
        ("week_from", "week_to"),
        (T_SHIFT, T_SHIFT_CASH, T_STORE),
    ),
    "продажи_месяц": _q(
        "продажи_месяц",
        "sales_month",
        "SQL_Продажи",
        "Выручка/чеки за месяц",
        _SQL_SALES_MONTH,
        ("month_from", "month_to"),
        (T_SHIFT, T_SHIFT_CASH, T_STORE),
    ),
    "доступность_неделя": _q(
        "доступность_неделя",
        "availability_week",
        "SQL_Доступность_Пенетрация",
        "Доступность: ТЗ от остатка, СП от продаж",
        _SQL_AVAILABILITY,
        ("week_from", "week_to"),
        (T_STOCK, T_WAREHOUSE, T_PROPS, T_PROP_KINDS, T_SALES, T_STORE),
    ),
    "доступность_sku": _q(
        "доступность_sku",
        "availability_sku",
        "SQL_Доступность_Пенетрация",
        "SKU: ТЗ по остатку, СП по продажам периода",
        _SQL_AVAILABILITY_SKU,
        ("week_from", "week_to"),
        (T_STOCK, T_WAREHOUSE, T_PROPS, T_PROP_KINDS, T_NOMEN, T_STORE, T_SALES),
    ),
    "доступность_сп_день": _q(
        "доступность_сп_день",
        "availability_sp_day",
        "SQL_Доступность_Пенетрация",
        "Ежедневные продажи SKU корзины СП",
        _SQL_AVAILABILITY_SP_DAY,
        ("date_from", "date_to"),
        (T_SALES, T_STORE, T_PROPS, T_PROP_KINDS, T_NOMEN),
    ),
    "пенетрация_неделя": _q(
        "пенетрация_неделя",
        "penetration_week",
        "SQL_Доступность_Пенетрация",
        "Пенетрация СП и Паскуччи",
        _SQL_PENETRATION,
        ("date_from", "date_to"),
        (T_SHIFT, T_SHIFT_CASH, T_SHIFT_GOODS, T_STORE, T_NOMEN),
    ),
    "списания_неделя": _q(
        "списания_неделя",
        "writeoff_week",
        "SQL_Списания_Потери",
        "Списания по статьям",
        _SQL_WRITEOFF,
        ("date_from", "date_to"),
        (T_WRITEOFF, T_WRITEOFF_VT, T_STORE, T_EXPENSE_ITEMS),
    ),
    "потери_месяц": _q(
        "потери_месяц",
        "losses_month",
        "SQL_Списания_Потери",
        "Потери: статьи списания + инвентаризация",
        _SQL_LOSSES,
        ("date_from", "date_to"),
        (T_WRITEOFF, T_WRITEOFF_VT, T_INV, T_STORE, T_EXPENSE_ITEMS),
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
        (T_STOCK_TOTALS, T_WAREHOUSE, T_STORE),
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
assert T_SHIFT in _SQL_SALES_DAY
assert T_SHIFT_CASH in _SQL_SALES_DAY
assert "_Fld2319" in _SQL_SALES_DAY
assert "_Fld6977" in _SQL_SALES_DAY
assert "_Document156" not in _SQL_SALES_DAY
assert "_Fld4669RRef" in _SQL_LOSSES
