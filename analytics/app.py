"""Isolated WAR_ROM analytics / metadata admin API.

Runs separately from production Streamlit. Does not alter Streamlit UI.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from analytics.db import apply_migrations, get_engine
from analytics.metadata_import import catalog_status, import_structure_map, search_catalog
from analytics.metrics_service import invalidate_cache, last_success_at, load_analytics, sql_health
from analytics.semantic_seed import list_entities, seed_semantic_entities
from app.core.settings import redact_error
from app.domain.store_prefix_map import STORE_PREFIX_TO_NAME

app = FastAPI(
    title="WAR_ROM Analytics API",
    version="1.0.0",
    description="Isolated SQL analytics + 1C metadata catalog. Not the production Streamlit UI.",
)


@app.on_event("startup")
def _startup() -> None:
    apply_migrations(get_engine())
    seed_semantic_entities(get_engine())


@app.get("/health")
def health():
    st = sql_health()
    return {
        "ok": True,
        "service": "warroom-analytics",
        "sql_ok": st.ok,
        "sql_message": st.message,
        "sql_database": st.database,
        "last_sql_success_at": last_success_at() or st.last_success_at,
        "streamlit_untouched": True,
    }


@app.post("/api/admin/cache/invalidate")
def cache_invalidate():
    return {"cleared": invalidate_cache()}


@app.get("/api/admin/metadata/1c-storage-map/status")
def metadata_status():
    return catalog_status()


@app.get("/api/admin/metadata/1c-storage-map")
def metadata_list(
    q: str = Query(""),
    active_only: bool = True,
    limit: int = Query(200, ge=1, le=1000),
):
    return {"rows": search_catalog(q=q, active_only=active_only, limit=limit)}


@app.get("/api/admin/metadata/1c-storage-map/search")
def metadata_search(q: str = Query(""), limit: int = Query(200, ge=1, le=1000)):
    return {"rows": search_catalog(q=q, active_only=True, limit=limit)}


@app.post("/api/admin/metadata/1c-storage-map/import")
def metadata_import(actor: str = "admin"):
    try:
        result = import_structure_map(actor=actor)
        return result
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=redact_error(exc)) from exc


@app.get("/api/admin/semantic/entities")
def semantic_entities():
    return {"entities": list_entities()}


@app.post("/api/admin/semantic/seed")
def semantic_seed():
    return seed_semantic_entities()


@app.get("/api/analytics/stores")
def stores():
    return {"stores": sorted(set(STORE_PREFIX_TO_NAME.values())), "prefixes": STORE_PREFIX_TO_NAME}


@app.get("/api/analytics/metrics")
def analytics_metrics(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    store: Optional[str] = None,
):
    end = date_to or date.today()
    start = date_from or (end - timedelta(days=7))
    if start > end:
        raise HTTPException(status_code=400, detail="date_from > date_to")
    if (end - start).days > 31:
        raise HTTPException(status_code=400, detail="period too long (max 31 days for analytics API)")
    snap = load_analytics(start, end, store)
    return {
        "ok": snap.ok,
        "message": snap.message,
        "loaded_at": snap.loaded_at,
        "date_from": snap.date_from,
        "date_to": snap.date_to,
        "store_filter": snap.store_filter,
        "sql_status": snap.sql_status,
        "warnings": snap.warnings,
        "metrics": [m.__dict__ for m in snap.metrics],
        "tables": snap.tables,
        "payment_label": "Оплаты по закрытиям смен",
        "payment_warning": "Форма оплаты доступна на уровне закрытия смены и не привязана к отдельному чеку",
    }


ADMIN_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <title>WAR_ROM — Карта структуры 1С (admin)</title>
  <style>
    body{font-family:system-ui,sans-serif;margin:24px;background:#0f1412;color:#e8f0ea}
    input,button,select{padding:8px;margin:4px;border-radius:6px;border:1px solid #345}
    table{border-collapse:collapse;width:100%;font-size:13px}
    th,td{border:1px solid #2a3a33;padding:6px 8px;vertical-align:top}
    th{background:#1b2621;position:sticky;top:0}
    .ok{color:#5dca86}.fail{color:#ff7b7b}.muted{color:#9bb0a3}
    a{color:#6fd6c5}
    .card{background:#151f1b;padding:14px;border-radius:10px;margin-bottom:14px}
  </style>
</head>
<body>
  <h1>Карта структуры 1С</h1>
  <p class="muted">Закрытый admin UI. Production Streamlit не изменяется.</p>
  <div class="card" id="status">Загрузка статуса…</div>
  <div class="card">
    <input id="q" placeholder="Поиск…" size="40"/>
    <button onclick="loadRows()">Искать</button>
    <button onclick="doImport()">Повторный импорт XLSX</button>
    <button onclick="loadEntities()">Semantic entities</button>
    <a href="/health" target="_blank">/health</a>
    <a href="/docs" target="_blank">/docs</a>
  </div>
  <div class="card"><pre id="entities" class="muted"></pre></div>
  <table><thead><tr>
    <th>ID</th><th>Метаданные</th><th>Таблица хранения</th><th>Имя таблицы</th><th>Назначение</th><th>Active</th><th>Imported</th>
  </tr></thead><tbody id="tbody"></tbody></table>
<script>
async function loadStatus(){
  const r = await fetch('/api/admin/metadata/1c-storage-map/status');
  const j = await r.json();
  const li = j.last_import || {};
  document.getElementById('status').innerHTML =
    `<b>Активных строк:</b> ${j.active_rows} / ${j.total_rows}<br/>
     <b>Последний импорт:</b> ${li.imported_at||'—'} · <span class="${li.import_status==='ok'?'ok':'fail'}">${li.import_status||'нет'}</span><br/>
     <b>Файл:</b> ${li.source_file_name||'—'} · rows=${li.total_rows??'—'} ins=${li.inserted_rows??'—'} upd=${li.updated_rows??'—'} skip=${li.skipped_rows??'—'}<br/>
     <span class="muted">Ожидаемые пути: ${(j.expected_xlsx_paths||[]).join(' | ')}</span>
     ${li.error_summary?`<div class="fail">${li.error_summary}</div>`:''}`;
}
async function loadRows(){
  const q = document.getElementById('q').value;
  const r = await fetch('/api/admin/metadata/1c-storage-map/search?q='+encodeURIComponent(q));
  const j = await r.json();
  const tb = document.getElementById('tbody');
  tb.innerHTML = (j.rows||[]).map(x=>`<tr>
    <td>${x.id}</td><td>${x.metadata_name||''}</td><td>${x.storage_table_name||''}</td>
    <td>${x.physical_table_name||''}</td><td>${x.purpose||''}</td>
    <td>${x.is_active}</td><td>${x.imported_at||''}</td></tr>`).join('') || '<tr><td colspan="7" class="muted">Нет строк (импортируйте XLSX)</td></tr>';
}
async function doImport(){
  const r = await fetch('/api/admin/metadata/1c-storage-map/import',{method:'POST'});
  const j = await r.json();
  alert(JSON.stringify(j,null,2));
  await loadStatus(); await loadRows();
}
async function loadEntities(){
  const r = await fetch('/api/admin/semantic/entities');
  const j = await r.json();
  document.getElementById('entities').textContent = (j.entities||[]).map(e=>
    `${e.entity_code}: ${e.entity_name} [${e.status}/${e.validation_status}] ← ${e.source_tables||'—'}`
  ).join('\\n');
}
loadStatus(); loadRows();
</script>
</body></html>
"""


@app.get("/admin/1c-storage-map", response_class=HTMLResponse)
def admin_page():
    return ADMIN_HTML


@app.get("/")
def root():
    return JSONResponse(
        {
            "service": "warroom-analytics",
            "admin": "/admin/1c-storage-map",
            "health": "/health",
            "docs": "/docs",
            "note": "Isolated from production Streamlit",
        }
    )
