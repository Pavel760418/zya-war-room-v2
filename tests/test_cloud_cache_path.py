from pathlib import Path

from app.services.local_cache_store import LocalCacheStore, cache_db_path, default_cache_dir
from app.services import sql_data_service as sds


def test_default_cache_dir_is_repo_relative():
    d = default_cache_dir()
    assert d.name == "cache"
    assert d.parent.name == "var"
    assert "zya-war-room-v2" in str(d)


def test_cache_db_path_read_does_not_require_mkdir(tmp_path, monkeypatch):
    missing = tmp_path / "no_such_dir"
    monkeypatch.setenv("WARROOM_CACHE_DIR", str(missing))
    # recreate default via env
    p = cache_db_path(create=False)
    assert p == missing / "warroom_raw.sqlite"
    assert not missing.exists()
    store = LocalCacheStore()
    assert store.exists() is False


def test_resolve_source_mode_sql_when_cache_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("WARROOM_DATA_SOURCE", raising=False)
    monkeypatch.setenv("WARROOM_CACHE_DIR", str(tmp_path / "empty_cache"))
    assert sds._resolve_source_mode() == "sql"


def test_resolve_source_mode_respects_env_cache(monkeypatch):
    monkeypatch.setenv("WARROOM_DATA_SOURCE", "cache")
    assert sds._resolve_source_mode() == "cache"
