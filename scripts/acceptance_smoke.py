#!/usr/bin/env python3
"""Acceptance smoke for public SQL gateway + edge Streamlit."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOG = ROOT / "var" / "log" / "acceptance_smoke.jsonl"


def _load_gateway_env() -> dict[str, str]:
    vals: dict[str, str] = {}
    p = Path.home() / ".config" / "warroom" / "gateway.env"
    for line in p.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            vals[k] = v.strip()
    return vals


def _http_json(url: str, headers: dict | None = None, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _external_port_open(host: str, port: int) -> bool:
    body = json.dumps({"host": host, "ports": [port]}).encode()
    req = urllib.request.Request(
        "https://portchecker.io/api/v1/query",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    for item in data.get("check") or []:
        if int(item.get("port")) == port:
            return bool(item.get("status"))
    return False


def run(label: str) -> dict:
    vals = _load_gateway_env()
    os.environ["WARROOM_GATEWAY_TOKEN"] = vals["WARROOM_GATEWAY_TOKEN"]
    os.environ["WARROOM_GATEWAY_URL"] = "http://127.0.0.1:3000/warroom-api"

    edge_ui = urllib.request.urlopen("http://127.0.0.1:3000/warroom/_stcore/health", timeout=20).read().decode().strip()
    gw = _http_json("http://127.0.0.1:3000/warroom-api/health")
    port_open = _external_port_open("81.163.35.181", 3000)

    # External HTTP probe via check-host (best-effort)
    ext_ok = ext_fail = 0
    try:
        target = "http://81.163.35.181:3000/warroom-api/health"
        rid = _http_json(
            "https://check-host.net/check-http?host=" + urllib.parse.quote(target),
            headers={"Accept": "application/json", "User-Agent": "warroom-smoke/1.0"},
        ).get("request_id")
        time.sleep(8)
        nodes = _http_json(
            f"https://check-host.net/check-result/{rid}",
            headers={"Accept": "application/json", "User-Agent": "warroom-smoke/1.0"},
        )
        for _n, res in (nodes or {}).items():
            try:
                code = str(res[0][3])
                if code.startswith("2"):
                    ext_ok += 1
                else:
                    ext_fail += 1
            except Exception:
                ext_fail += 1
    except Exception as exc:  # noqa: BLE001
        ext_fail = -1
        ext_err = str(exc)[:120]
    else:
        ext_err = None

    from importlib import reload

    import app.core.settings as settings

    reload(settings)
    import app.services.sql_data_service as sds

    reload(sds)
    from app.services.metrics_service import MetricsService

    svc = sds.SqlDataService(use_env_db=False)
    st = svc.status()
    res = svc.load()
    dash = MetricsService(res.raw, mode="excel").build_dashboard(period="day") if res.mapping_complete else None

    rec = {
        "label": label,
        "ts": datetime.now(timezone.utc).isoformat(),
        "port_3000_open_external": port_open,
        "external_gateway_http_200_nodes": ext_ok,
        "external_gateway_fail_nodes": ext_fail,
        "external_probe_error": ext_err,
        "edge_ui_health": edge_ui,
        "gateway_ok": gw.get("ok"),
        "gateway_db": gw.get("database"),
        "gateway_server": gw.get("server"),
        "sql_status_ok": st.ok,
        "mapping_complete": bool(res.mapping_complete),
        "last_success_at": res.last_success_at or st.last_success_at,
        "kpi_count": len(dash.kpis) if dash else 0,
        "stores": len(dash.store_table) if dash else 0,
        "ok": bool(gw.get("ok") and res.mapping_complete and dash and edge_ui == "ok" and port_open),
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False))
    return rec


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "manual"
    run(label)
