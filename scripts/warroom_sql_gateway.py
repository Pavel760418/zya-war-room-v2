"""Read-only War Room SQL gateway for Streamlit Cloud (LAN edge).

Runs on the analytics host with direct access to 1C MSSQL. Exposes JSON
snapshots of ``SqlDataService.load()`` behind a shared bearer token.

Public edge (nginx on :3000) proxies ``/warroom-api/`` here and Metabase on ``/``.
"""
from __future__ import annotations

import gzip
import json
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse

# Ensure repo root on path when started as script
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.settings import get_app_settings, missing_database_secret_keys  # noqa: E402
from app.services.sql_data_service import SqlDataService  # noqa: E402

LOG_DIR = Path(os.environ.get("WARROOM_GATEWAY_LOG_DIR", str(ROOT / "var" / "log")))
LOG_DIR.mkdir(parents=True, exist_ok=True)
HEARTBEAT_PATH = LOG_DIR / "gateway_heartbeat.json"


def _load_gateway_token() -> str:
    for path in (
        Path.home() / ".config" / "warroom" / "gateway.env",
        Path("/etc/warroom/gateway.env"),
    ):
        if path.is_file():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line.startswith("WARROOM_GATEWAY_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return (os.environ.get("WARROOM_GATEWAY_TOKEN") or "").strip()


GATEWAY_TOKEN = _load_gateway_token()

app = FastAPI(title="War Room SQL Gateway", version="1.0.0")


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.hex()
    if pd.isna(obj):
        return None
    raise TypeError(f"Unserializable type: {type(obj)}")


def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or not isinstance(df, pd.DataFrame):
        return []
    clean = df.where(pd.notnull(df), None)
    return json.loads(clean.to_json(orient="records", date_format="iso", force_ascii=False))


def _require_token(authorization: Optional[str], x_warroom_token: Optional[str]) -> None:
    expected = GATEWAY_TOKEN
    if not expected:
        raise HTTPException(status_code=503, detail="gateway_token_not_configured")
    got = ""
    if x_warroom_token:
        got = x_warroom_token.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        got = authorization[7:].strip()
    if not got or got != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


def _write_heartbeat(payload: dict[str, Any]) -> None:
    try:
        HEARTBEAT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


@app.get("/health")
def health() -> dict[str, Any]:
    settings = get_app_settings()
    missing = missing_database_secret_keys()
    sql_ok = False
    sql_error = None
    server = None
    database = None
    try:
        status = SqlDataService().status()
        sql_ok = bool(status.ok)
        sql_error = status.error
        server = status.server
        database = status.database
    except Exception as exc:  # noqa: BLE001
        sql_error = str(exc)[:300]
    body = {
        "ok": sql_ok,
        "service": "warroom-sql-gateway",
        "sql_ok": sql_ok,
        "server": server,
        "database": database,
        "error": sql_error,
        "database_url_configured": bool(settings.database_url),
        "missing_secrets": list(missing),
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    _write_heartbeat(body)
    return body


@app.get("/raw")
def raw(
    authorization: Optional[str] = Header(default=None),
    x_warroom_token: Optional[str] = Header(default=None, alias="X-WarRoom-Token"),
    gzip_body: int = 1,
) -> Response:
    _require_token(authorization, x_warroom_token)
    t0 = time.time()
    try:
        result = SqlDataService().load()
    except Exception as exc:  # noqa: BLE001
        _write_heartbeat({"ok": False, "error": str(exc)[:300], "ts": datetime.utcnow().isoformat() + "Z"})
        raise HTTPException(status_code=503, detail=f"sql_load_failed: {exc}") from exc

    sheets: dict[str, Any] = {}
    for key, val in (result.raw or {}).items():
        if isinstance(val, pd.DataFrame):
            sheets[key] = _df_to_records(val)
        else:
            sheets[key] = val

    payload = {
        "ok": bool(result.status.ok),
        "mapping_complete": bool(result.mapping_complete),
        "status": {
            "ok": result.status.ok,
            "message": result.status.message,
            "server": result.status.server,
            "database": result.status.database,
            "error": result.status.error,
            "last_success_at": result.status.last_success_at or result.last_success_at,
        },
        "warnings": list(result.warnings or []),
        "confidence_notes": list(result.confidence_notes or []),
        "last_success_at": result.last_success_at,
        "elapsed_ms": int((time.time() - t0) * 1000),
        "sheets": sheets,
    }
    _write_heartbeat(
        {
            "ok": payload["ok"],
            "mapping_complete": payload["mapping_complete"],
            "server": payload["status"]["server"],
            "database": payload["status"]["database"],
            "last_success_at": payload["last_success_at"],
            "ts": datetime.utcnow().isoformat() + "Z",
        }
    )
    raw_bytes = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
    if gzip_body:
        return Response(
            content=gzip.compress(raw_bytes),
            media_type="application/json",
            headers={"Content-Encoding": "gzip", "X-WarRoom-Mapping-Complete": str(payload["mapping_complete"]).lower()},
        )
    return JSONResponse(payload)


def main() -> None:
    import uvicorn

    host = os.environ.get("WARROOM_GATEWAY_HOST", "127.0.0.1")
    port = int(os.environ.get("WARROOM_GATEWAY_PORT", "8520"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
