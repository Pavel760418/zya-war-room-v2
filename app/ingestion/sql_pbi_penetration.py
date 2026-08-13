"""Canonical SQL for PBI-parity check penetration (ucs.CASHSAIL).

Implements the grain of DAX:

    Трафик = COUNTROWS(SUMMARIZE(ДЧ Продажи, id1, id3, id4, Период))
    Пенетрация = DIVIDE(Трафик_filtered, Трафик_all, 0)

Join paths (confirmed from ТКПТ_пенетрация.pbix):

- CASHSAIL.SHOPINDEX  → _Reference64._Code          (store)
- CASHSAIL.CARDARTICU → _Reference58._Code          (SKU)
- _Reference58._Fld808RRef → _Reference93           (brand / марка)
- SP basket: hierarchy root name
  ``Производство Зеленого яблока`` (= folder code 00107646)

Parameters use ``:date_from`` / ``:date_to`` as inclusive calendar dates
(convert to exclusive upper bound in the caller if needed).

Not executed by sync/UI until implement command.
"""
from __future__ import annotations

SP_LEVEL1 = "Производство Зеленого яблока"
PASCUCCI_BRAND = "Паскуччи"

# 16 network stores from PBI '_Магазины сети' (text names must match _Reference64._Description)
NETWORK_STORES_SQL = ", ".join(
    f"N'{n}'"
    for n in (
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
)

# Hierarchy [1 уровень] as in PBI M (ТКПТ_СТ_Номенклатура) — root folder name match.
_SP_LEVEL1_CTE = f"""
nomen_hier AS (
  SELECT
    t1._IDRRef AS nomen_id,
    LTRIM(RTRIM(CAST(t1._Code AS nvarchar(50)))) AS sku_code,
    COALESCE(
      t8._Description, t7._Description, t6._Description,
      t5._Description, t4._Description, t3._Description,
      t2._Description, t1._Description
    ) AS level1
  FROM dbo._Reference58 AS t1
  LEFT JOIN dbo._Reference58 AS t2 ON t1._ParentIDRRef = t2._IDRRef
  LEFT JOIN dbo._Reference58 AS t3 ON t2._ParentIDRRef = t3._IDRRef
  LEFT JOIN dbo._Reference58 AS t4 ON t3._ParentIDRRef = t4._IDRRef
  LEFT JOIN dbo._Reference58 AS t5 ON t4._ParentIDRRef = t5._IDRRef
  LEFT JOIN dbo._Reference58 AS t6 ON t5._ParentIDRRef = t6._IDRRef
  LEFT JOIN dbo._Reference58 AS t7 ON t6._ParentIDRRef = t7._IDRRef
  LEFT JOIN dbo._Reference58 AS t8 ON t7._ParentIDRRef = t8._IDRRef
),
sp_sku AS (
  SELECT sku_code FROM nomen_hier
  WHERE level1 = N'{SP_LEVEL1}'
),
pas_sku AS (
  SELECT LTRIM(RTRIM(CAST(n._Code AS nvarchar(50)))) AS sku_code
  FROM dbo._Reference58 AS n
  INNER JOIN dbo._Reference93 AS b ON b._IDRRef = n._Fld808RRef
  WHERE LTRIM(RTRIM(CAST(b._Description AS nvarchar(255)))) = N'{PASCUCCI_BRAND}'
)
""".strip()

SQL_PENETRATION_DAILY = f"""
-- PBI-parity: SP + Pascucci check penetration by store/day from ucs.CASHSAIL
-- Requires: 3-part name or USE ucs; retail nomens via cross-db or staged sku lists.
-- Recommended sync shape: run against linked servers / same host with [ucs].[dbo].[CASHSAIL]
-- and [retail].[dbo].[_Reference*].
WITH {_SP_LEVEL1_CTE},
checks AS (
  SELECT DISTINCT
    CAST(cs.SDATEZ AS date) AS period_date,
    cs.SHOPINDEX AS shopindex,
    cs.CHECKNUMBE AS check_no,
    cs.CASHNUMBER AS cash_no,
    LTRIM(RTRIM(CAST(cs.CARDARTICU AS nvarchar(30)))) AS sku_code
  FROM [ucs].[dbo].[CASHSAIL] AS cs
  WHERE cs.SDATEZ >= CAST(:date_from AS datetime)
    AND cs.SDATEZ <  DATEADD(day, 1, CAST(:date_to AS datetime))
),
store_map AS (
  SELECT
    TRY_CAST(LTRIM(RTRIM(CAST(s._Code AS nvarchar(50)))) AS int) AS shopindex,
    LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) AS store_name
  FROM [retail].[dbo].[_Reference64] AS s
  WHERE LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) IN ({NETWORK_STORES_SQL})
),
check_flags AS (
  SELECT
    c.period_date,
    sm.store_name,
    c.shopindex,
    c.check_no,
    c.cash_no,
    MAX(CASE WHEN sp.sku_code IS NOT NULL THEN 1 ELSE 0 END) AS has_sp,
    MAX(CASE WHEN pa.sku_code IS NOT NULL THEN 1 ELSE 0 END) AS has_pas
  FROM checks AS c
  INNER JOIN store_map AS sm ON sm.shopindex = c.shopindex
  LEFT JOIN sp_sku AS sp ON sp.sku_code = c.sku_code
  LEFT JOIN pas_sku AS pa ON pa.sku_code = c.sku_code
  GROUP BY c.period_date, sm.store_name, c.shopindex, c.check_no, c.cash_no
)
SELECT
  period_date AS [Дата],
  store_name AS [Магазин],
  COUNT(*) AS [Чеков всего],
  SUM(has_sp) AS [Чеков с СП],
  SUM(has_pas) AS [Чеков с Паскуччи],
  CAST(SUM(has_sp) AS float) / NULLIF(COUNT(*), 0) AS [Пенетрация СП],
  CAST(SUM(has_pas) AS float) / NULLIF(COUNT(*), 0) AS [Пенетрация Паскуччи]
FROM check_flags
GROUP BY period_date, store_name
ORDER BY [Дата], [Магазин];
""".strip()

SQL_TRAFFIC_DAILY = """
-- PBI [Трафик] only (no nomenclature filter) — network stores
SELECT
  CAST(cs.SDATEZ AS date) AS [Дата],
  LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) AS [Магазин],
  COUNT(*) AS [Трафик]
FROM (
  SELECT DISTINCT
    SHOPINDEX, CHECKNUMBE, CASHNUMBER, CAST(SDATEZ AS date) AS SDATEZ
  FROM [ucs].[dbo].[CASHSAIL]
  WHERE SDATEZ >= CAST(:date_from AS datetime)
    AND SDATEZ <  DATEADD(day, 1, CAST(:date_to AS datetime))
) AS cs
INNER JOIN [retail].[dbo].[_Reference64] AS s
  ON TRY_CAST(LTRIM(RTRIM(CAST(s._Code AS nvarchar(50)))) AS int) = cs.SHOPINDEX
WHERE LTRIM(RTRIM(CAST(s._Description AS nvarchar(255)))) IN (
""" + NETWORK_STORES_SQL + """
)
GROUP BY CAST(cs.SDATEZ AS date), LTRIM(RTRIM(CAST(s._Description AS nvarchar(255))))
ORDER BY [Дата], [Магазин];
""".strip()
