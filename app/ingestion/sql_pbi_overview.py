"""PBI-parity SQL for Обзор cards (ТКПТ_обзор) + shared network store list.

``date_from`` / ``date_to`` — как в sql_extract: date_to exclusive (календарная дата).
"""
from __future__ import annotations

from app.metrics.loss_articles import COMMODITY_WRITEOFF_ARTICLES, EXPENSE_ARTICLES

NETWORK_STORES = (
    "Автодом",
    "Акушинка",
    "Апельсин",
    "БКК",
    "Каспийск",
    "Ленинград",
    "Молоток",
    "Пирамида",
    "Северный",
    "Сити",
    "Шамиля 10",
    "Энгельса",
    "Яблоко 101",
    "Яблоко 104",
    "Яблоко 107",
    "Яблоко 109",
)

NETWORK_STORES_SQL = ", ".join(f"N'{n}'" for n in NETWORK_STORES)
SP_LEVEL1 = "Производство Зеленого яблока"
SP_FOLDER_CODE = "00107646"
PASCUCCI_BRAND = "Паскуччи"
WRITEOFF_ARTICLES_SQL = ", ".join(f"N'{n}'" for n in COMMODITY_WRITEOFF_ARTICLES)
EXPENSE_ARTICLES_SQL = ", ".join(f"N'{n}'" for n in EXPENSE_ARTICLES)

# SP basket by folder code (same folder as level1 name «Производство Зеленого яблока»)
_SP_SKU_CTE = f"""
roots AS (
  SELECT _IDRRef FROM dbo._Reference58
  WHERE LTRIM(RTRIM(CAST(_Code AS nvarchar(50)))) = N'{SP_FOLDER_CODE}'
),
lvl1 AS (
  SELECT c._IDRRef FROM dbo._Reference58 c
  INNER JOIN roots r ON c._ParentIDRRef = r._IDRRef WHERE c._Marked = 0x00
),
lvl2 AS (
  SELECT c._IDRRef FROM dbo._Reference58 c
  INNER JOIN lvl1 r ON c._ParentIDRRef = r._IDRRef WHERE c._Marked = 0x00
),
lvl3 AS (
  SELECT c._IDRRef FROM dbo._Reference58 c
  INNER JOIN lvl2 r ON c._ParentIDRRef = r._IDRRef WHERE c._Marked = 0x00
),
lvl4 AS (
  SELECT c._IDRRef FROM dbo._Reference58 c
  INNER JOIN lvl3 r ON c._ParentIDRRef = r._IDRRef WHERE c._Marked = 0x00
),
sp_nomen AS (
  SELECT _IDRRef FROM roots
  UNION SELECT _IDRRef FROM lvl1
  UNION SELECT _IDRRef FROM lvl2
  UNION SELECT _IDRRef FROM lvl3
  UNION SELECT _IDRRef FROM lvl4
),
sp_sku AS (
  SELECT LTRIM(RTRIM(CAST(_Code AS nvarchar(50)))) AS sku_code
  FROM dbo._Reference58
  WHERE _IDRRef IN (SELECT _IDRRef FROM sp_nomen)
),
pas_sku AS (
  SELECT LTRIM(RTRIM(CAST(n._Code AS nvarchar(50)))) AS sku_code
  FROM dbo._Reference58 AS n
  INNER JOIN dbo._Reference93 AS b ON b._IDRRef = n._Fld808RRef
  WHERE LTRIM(RTRIM(CAST(b._Description AS nvarchar(255)))) = N'{PASCUCCI_BRAND}'
)
""".strip()

SQL_PBI_RTO_DAILY = f"""
WITH {_SP_SKU_CTE}
SELECT
  CAST(DATEADD(year, -2000, t._Period) AS date) AS [Дата],
  LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) AS [Магазин],
  SUM(CAST(t._Fld6707 AS float)) AS [Выручка факт],
  SUM(
    CASE WHEN sp._IDRRef IS NOT NULL THEN CAST(t._Fld6707 AS float) ELSE 0 END
  ) AS [Выручка СП]
FROM dbo._AccumRg6691 AS t
INNER JOIN dbo._Reference64 AS s ON s._IDRRef = t._Fld6692RRef
LEFT JOIN sp_nomen AS sp ON sp._IDRRef = t._Fld6693RRef
WHERE t._Period >= DATEADD(year, 2000, CAST(%(date_from)s AS datetime))
  AND t._Period <  DATEADD(year, 2000, CAST(%(date_to)s AS datetime))
  AND LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) IN ({NETWORK_STORES_SQL})
GROUP BY
  CAST(DATEADD(year, -2000, t._Period) AS date),
  LTRIM(RTRIM(CAST(s._Description AS nvarchar(255))))
ORDER BY [Дата], [Магазин];
""".strip()

# 1РТО С (Обзор): только товарные статьи — без обедов/представительских.
SQL_PBI_WRITEOFF_DAILY = f"""
SELECT
  CAST(DATEADD(year, -2000, rg._Period) AS date) AS [Дата],
  LTRIM(RTRIM(CAST(st._Description AS nvarchar(255)))) AS [Магазин],
  LTRIM(RTRIM(CAST(a._Description AS nvarchar(255)))) AS [Статья списания],
  SUM(CAST(rg._Fld6638 AS float)) AS [Сумма]
FROM dbo._AccumRg6630 AS rg
INNER JOIN dbo._Reference76 AS wh ON wh._IDRRef = rg._Fld6631RRef
INNER JOIN dbo._Reference64 AS st ON st._IDRRef = wh._Fld1140RRef
INNER JOIN dbo._Document172 AS d ON d._IDRRef = rg._RecorderRRef
INNER JOIN dbo._Reference82 AS a ON a._IDRRef = d._Fld4669RRef
WHERE rg._Period >= DATEADD(year, 2000, CAST(%(date_from)s AS datetime))
  AND rg._Period <  DATEADD(year, 2000, CAST(%(date_to)s AS datetime))
  AND a._Description IN ({WRITEOFF_ARTICLES_SQL})
  AND LTRIM(RTRIM(CAST(st._Description AS nvarchar(255)))) IN ({NETWORK_STORES_SQL})
GROUP BY
  CAST(DATEADD(year, -2000, rg._Period) AS date),
  LTRIM(RTRIM(CAST(st._Description AS nvarchar(255)))),
  LTRIM(RTRIM(CAST(a._Description AS nvarchar(255))))
ORDER BY [Дата], [Магазин], [Статья списания];
""".strip()

# Все статьи Document172 с ненулевой связью СТ Статьи С (= DAX РТО С: RELATED Операция <> BLANK).
SQL_PBI_WRITEOFF_ALL_ARTICLES_DAILY = f"""
SELECT
  CAST(DATEADD(year, -2000, rg._Period) AS date) AS [Дата],
  LTRIM(RTRIM(CAST(st._Description AS nvarchar(255)))) AS [Магазин],
  LTRIM(RTRIM(CAST(a._Description AS nvarchar(255)))) AS [Статья списания],
  SUM(CAST(rg._Fld6638 AS float)) AS [Сумма]
FROM dbo._AccumRg6630 AS rg
INNER JOIN dbo._Reference76 AS wh ON wh._IDRRef = rg._Fld6631RRef
INNER JOIN dbo._Reference64 AS st ON st._IDRRef = wh._Fld1140RRef
INNER JOIN dbo._Document172 AS d ON d._IDRRef = rg._RecorderRRef
INNER JOIN dbo._Reference82 AS a ON a._IDRRef = d._Fld4669RRef
WHERE rg._Period >= DATEADD(year, 2000, CAST(%(date_from)s AS datetime))
  AND rg._Period <  DATEADD(year, 2000, CAST(%(date_to)s AS datetime))
  AND a._Description IS NOT NULL
  AND LTRIM(RTRIM(CAST(a._Description AS nvarchar(255)))) <> N''
  AND LTRIM(RTRIM(CAST(st._Description AS nvarchar(255)))) IN ({NETWORK_STORES_SQL})
GROUP BY
  CAST(DATEADD(year, -2000, rg._Period) AS date),
  LTRIM(RTRIM(CAST(st._Description AS nvarchar(255)))),
  LTRIM(RTRIM(CAST(a._Description AS nvarchar(255))))
ORDER BY [Дата], [Магазин], [Статья списания];
""".strip()

# Расходы (Обед / Представительские) — отдельно от товарных списаний.
SQL_PBI_EXPENSE_DAILY = f"""
SELECT
  CAST(DATEADD(year, -2000, rg._Period) AS date) AS [Дата],
  LTRIM(RTRIM(CAST(st._Description AS nvarchar(255)))) AS [Магазин],
  LTRIM(RTRIM(CAST(a._Description AS nvarchar(255)))) AS [Статья списания],
  SUM(CAST(rg._Fld6638 AS float)) AS [Сумма]
FROM dbo._AccumRg6630 AS rg
INNER JOIN dbo._Reference76 AS wh ON wh._IDRRef = rg._Fld6631RRef
INNER JOIN dbo._Reference64 AS st ON st._IDRRef = wh._Fld1140RRef
INNER JOIN dbo._Document172 AS d ON d._IDRRef = rg._RecorderRRef
INNER JOIN dbo._Reference82 AS a ON a._IDRRef = d._Fld4669RRef
WHERE rg._Period >= DATEADD(year, 2000, CAST(%(date_from)s AS datetime))
  AND rg._Period <  DATEADD(year, 2000, CAST(%(date_to)s AS datetime))
  AND a._Description IN ({EXPENSE_ARTICLES_SQL})
  AND LTRIM(RTRIM(CAST(st._Description AS nvarchar(255)))) IN ({NETWORK_STORES_SQL})
GROUP BY
  CAST(DATEADD(year, -2000, rg._Period) AS date),
  LTRIM(RTRIM(CAST(st._Description AS nvarchar(255)))),
  LTRIM(RTRIM(CAST(a._Description AS nvarchar(255))))
ORDER BY [Дата], [Магазин], [Статья списания];
""".strip()

SQL_PBI_INVENTORY_DAILY = f"""
SELECT
  CAST(DATEADD(year, -2000, rg._Period) AS date) AS [Дата],
  LTRIM(RTRIM(CAST(st._Description AS nvarchar(255)))) AS [Магазин],
  SUM(
    CASE
      WHEN rg._RecordKind = 1 THEN CAST(rg._Fld6638 AS float)
      WHEN rg._RecordKind = 0 THEN -CAST(rg._Fld6638 AS float)
      ELSE 0
    END
  ) AS [Сумма]
FROM dbo._AccumRg6630 AS rg
INNER JOIN dbo._Reference76 AS wh ON wh._IDRRef = rg._Fld6631RRef
INNER JOIN dbo._Reference64 AS st ON st._IDRRef = wh._Fld1140RRef
INNER JOIN dbo._Reference97 AS op ON op._IDRRef = rg._Fld6641RRef
WHERE rg._Period >= DATEADD(year, 2000, CAST(%(date_from)s AS datetime))
  AND rg._Period <  DATEADD(year, 2000, CAST(%(date_to)s AS datetime))
  AND op._Description = N'Инвентаризация товаров'
  AND LTRIM(RTRIM(CAST(st._Description AS nvarchar(255)))) IN ({NETWORK_STORES_SQL})
GROUP BY
  CAST(DATEADD(year, -2000, rg._Period) AS date),
  LTRIM(RTRIM(CAST(st._Description AS nvarchar(255))))
ORDER BY [Дата], [Магазин];
""".strip()

# DAX РТО ОИ — «Закрытие смены (оприходование излишков)», тот же знак по _RecordKind.
SQL_PBI_SURPLUS_DAILY = f"""
SELECT
  CAST(DATEADD(year, -2000, rg._Period) AS date) AS [Дата],
  LTRIM(RTRIM(CAST(st._Description AS nvarchar(255)))) AS [Магазин],
  SUM(
    CASE
      WHEN rg._RecordKind = 1 THEN CAST(rg._Fld6638 AS float)
      WHEN rg._RecordKind = 0 THEN -CAST(rg._Fld6638 AS float)
      ELSE 0
    END
  ) AS [Сумма]
FROM dbo._AccumRg6630 AS rg
INNER JOIN dbo._Reference76 AS wh ON wh._IDRRef = rg._Fld6631RRef
INNER JOIN dbo._Reference64 AS st ON st._IDRRef = wh._Fld1140RRef
INNER JOIN dbo._Reference97 AS op ON op._IDRRef = rg._Fld6641RRef
WHERE rg._Period >= DATEADD(year, 2000, CAST(%(date_from)s AS datetime))
  AND rg._Period <  DATEADD(year, 2000, CAST(%(date_to)s AS datetime))
  AND op._Description = N'Закрытие смены (оприходование излишков)'
  AND LTRIM(RTRIM(CAST(st._Description AS nvarchar(255)))) IN ({NETWORK_STORES_SQL})
GROUP BY
  CAST(DATEADD(year, -2000, rg._Period) AS date),
  LTRIM(RTRIM(CAST(st._Description AS nvarchar(255))))
ORDER BY [Дата], [Магазин];
""".strip()

SQL_PBI_TRAFFIC_PEN_DAILY = f"""
WITH {_SP_SKU_CTE},
store_map AS (
  SELECT
    TRY_CAST(LTRIM(RTRIM(CAST(s._Code AS nvarchar(50)))) AS int) AS shopindex,
    LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) AS store_name
  FROM dbo._Reference64 AS s
  WHERE LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) IN ({NETWORK_STORES_SQL})
),
lines AS (
  SELECT
    CAST(cs.SDATEZ AS date) AS period_date,
    cs.SHOPINDEX AS shopindex,
    cs.CHECKNUMBE AS check_no,
    cs.CASHNUMBER AS cash_no,
    LTRIM(RTRIM(CAST(cs.CARDARTICU AS nvarchar(30)))) AS sku_code
  FROM [ucs].[dbo].[CASHSAIL] AS cs
  WHERE cs.SDATEZ >= CAST(%(date_from)s AS datetime)
    AND cs.SDATEZ <  CAST(%(date_to)s AS datetime)
),
check_flags AS (
  SELECT
    l.period_date,
    sm.store_name,
    l.shopindex,
    l.check_no,
    l.cash_no,
    MAX(CASE WHEN sp.sku_code IS NOT NULL THEN 1 ELSE 0 END) AS has_sp,
    MAX(CASE WHEN pa.sku_code IS NOT NULL THEN 1 ELSE 0 END) AS has_pas
  FROM lines AS l
  INNER JOIN store_map AS sm ON sm.shopindex = l.shopindex
  LEFT JOIN sp_sku AS sp ON sp.sku_code = l.sku_code
  LEFT JOIN pas_sku AS pa ON pa.sku_code = l.sku_code
  GROUP BY l.period_date, sm.store_name, l.shopindex, l.check_no, l.cash_no
)
SELECT
  period_date AS [Дата],
  store_name AS [Магазин],
  COUNT(*) AS [Количество чеков],
  SUM(has_sp) AS [Чеков с СП],
  SUM(has_pas) AS [Чеков с Паскуччи]
FROM check_flags
GROUP BY period_date, store_name
ORDER BY [Дата], [Магазин];
""".strip()
