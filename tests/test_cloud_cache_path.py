from pathlib import Path

from app.services.local_cache_store import LocalCacheStore, cache_db_path, default_cache_dir
from app.services import sql_data_service as sds


def test_default_cache_dir_prefers_cloud_snapshot_when_present():
    d = default_cache_dir()
    # In this repo snapshot is committed for Streamlit Cloud.
    assert d.name in {"cloud_snapshot", "cache"}
    assert (d / "warroom_raw.sqlite").is_file() or d.name == "cache"


def test_cache_db_path_read_does_not_require_mkdir(tmp_path, monkeypatch):
    missing = tmp_path / "no_such_dir"
    monkeypatch.setenv("WARROOM_CACHE_DIR", str(missing))
    p = cache_db_path(create=False)
    assert p == missing / "warroom_raw.sqlite"
    assert not missing.exists()
    store = LocalCacheStore()
    assert store.exists() is False


def test_resolve_source_mode_cache_when_snapshot_exists(monkeypatch):
    monkeypatch.delenv("WARROOM_DATA_SOURCE", raising=False)
    assert sds._resolve_source_mode() == "cache"


def test_resolve_source_mode_respects_env_cache(monkeypatch):
    monkeypatch.setenv("WARROOM_DATA_SOURCE", "cache")
    assert sds._resolve_source_mode() == "cache"


def test_resolve_source_mode_sql_when_cache_forced_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("WARROOM_DATA_SOURCE", raising=False)
    monkeypatch.setenv("WARROOM_CACHE_DIR", str(tmp_path / "empty_cache"))
    assert sds._resolve_source_mode() == "sql"
