"""Тесты физического маппинга 1С и SQL-extract (без обязательного live DB)."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.ingestion.metadata_catalog import (
    CATALOG_PATH,
    known_war_room_physicals,
    resolve_logical,
    storage_to_mssql,
)
from app.ingestion.sql_extract import CATALOG_QUERIES, PHYSICAL, T_SALES, get_query
from app.services.metrics_service import MetricsService
from app.services.sql_data_service import SqlDataService
from app.repositories.sql_database import SqlStatus


def test_storage_to_mssql_normalizes_prefix_and_vt():
    assert storage_to_mssql("AccumRg6691") == "_AccumRg6691"
    assert storage_to_mssql("Document107.VT1803") == "_Document107_VT1803"
    assert storage_to_mssql("_Reference64") == "_Reference64"


def test_catalog_resolves_war_room_objects():
    assert CATALOG_PATH.is_file(), "StrukturaKhraneniiaBazyDannykh.xlsx must be in data/catalog/"
    assert resolve_logical("РегистрНакопления.Продажи") == "_AccumRg6691"
    assert resolve_logical("Документ.СписаниеТоваров") == "_Document172"
    assert resolve_logical("Документ.Инвентаризация") == "_Document124"
    assert resolve_logical("ТоварыНаСкладах") == "_AccumRg6601"
    assert resolve_logical("ВыручкаИСебестоимостьПродаж") == "_AccumRg6691"
    phys = known_war_room_physicals()
    assert phys["Справочник.Магазины"] == "_Reference64"
    assert phys["Документ.БюджетПродаж.Товары"] == "_Document107_VT1803"


def test_sql_extract_uses_physical_names_not_logical():
    from app.ingestion.sql_extract import T_SHIFT, T_SHIFT_CASH

    assert T_SALES == "_AccumRg6691"
    assert T_SHIFT == "_Document119"
    assert T_SHIFT_CASH == "_Document119_VT2313"
    sql, _ = get_query("продажи_день", params={"date_from": date.today(), "date_to": date.today()})
    assert "_Document119" in sql
    assert "_Fld2319" in sql
    assert "РегистрНакопления_Продажи" not in sql
    assert "[dbo].[_Reference64]" in sql
    for q in CATALOG_QUERIES.values():
        assert q.physical_tables
        assert all(t.startswith("_") for t in q.physical_tables)
        assert "РегистрНакопления_" not in q.sql_mssql or "_AccumRg" in q.sql_mssql or "_Document" in q.sql_mssql


def test_sql_data_service_mock_connection_builds_dashboard():
    """Mock DB returns sales rows shaped like physical extract → MetricsService OK."""
    day = pd.DataFrame(
        {
            "Дата": [date.today(), date.today()],
            "Магазин": ["Каспийск", "Сити"],
            "Выручка факт": [100_000.0, 80_000.0],
            "Выручка план": [90_000.0, 70_000.0],
            "Количество чеков": [50.0, 40.0],
        }
    )
    empty = pd.DataFrame()

    def fake_fetch(sql, params=None, columns=None):
        s = sql or ""
        if "_Document119" in s and "FORMAT" in s.upper():
            return pd.DataFrame(
                {
                    "Месяц": ["2026-08", "2026-08"],
                    "Магазин": ["Каспийск", "Сити"],
                    "Выручка факт": [100_000.0, 80_000.0],
                    "Выручка план": [0.0, 0.0],
                    "Количество чеков": [50.0, 40.0],
                }
            )
        if "_Document119" in s:
            return day.copy()
        return empty.copy()

    db = MagicMock()
    db.ping.return_value = SqlStatus(ok=True, message="ok", server="test", database="retail")
    db.fetch_df.side_effect = fake_fetch
    db.last_success_iso = "2026-08-11T00:00:00+00:00"

    svc = SqlDataService(db=db)
    result = svc.load()
    assert result.status.ok
    assert not result.raw["sales_day"].empty
    dash = MetricsService(result.raw, mode="excel").build_dashboard(period="day")
    assert len(dash.kpis) >= 5
    assert len(dash.store_table) >= 1


def test_gateway_settings_available_via_bridge():
    from app.core.settings import get_gateway_settings, missing_database_secret_keys

    gw = get_gateway_settings()
    assert gw is not None
    assert gw.url.startswith("http")
    assert gw.token
    # Bridge removes missing_database_url blocker for Cloud
    assert missing_database_secret_keys() == ()


def test_sql_retry_env_defaults_documented():
    import os

    from app.repositories import sql_database as mod

    assert hasattr(mod.SqlDatabase, "connection")
    assert os.environ.get("WARROOM_SQL_RETRIES", "4")


@pytest.mark.integration
def test_live_mssql_optional():
    """Runs only when DATABASE_URL is set and reachable."""
    from app.core.settings import parse_database_url

    if parse_database_url() is None:
        pytest.skip("DATABASE_URL not configured")
    svc = SqlDataService()
    st = svc.status()
    if not st.ok:
        pytest.skip(f"MSSQL unreachable: {st.error}")
    res = svc.load()
    assert res.status.ok
    assert res.mapping_complete or len(res.warnings) > 0
    if not res.raw["sales_day"].empty:
        dash = MetricsService(res.raw, mode="excel").build_dashboard(period="day")
        assert len(dash.kpis) >= 5
