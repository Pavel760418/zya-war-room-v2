"""Gateway client: Streamlit Cloud pulls War Room raw sheets over HTTPS/HTTP edge."""
from __future__ import annotations

import gzip
import json
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from app.ingestion.schema import SCHEMA
from app.repositories.sql_database import SqlStatus

if False:  # type-checking only
    from app.services.sql_data_service import SqlLoadResult


@dataclass(frozen=True)
class GatewaySettings:
    base_url: str
    token: str
    timeout_sec: int = 90
    retries: int = 4


def _records_to_df(records: list[dict[str, Any]], schema_key: str) -> pd.DataFrame:
    df = pd.DataFrame(records or [])
    spec = SCHEMA.get(schema_key)
    if spec is not None:
        for c in spec.columns:
            if c.canonical not in df.columns:
                df[c.canonical] = c.default
    return df


def fetch_gateway_raw(settings: GatewaySettings):
    from app.services.sql_data_service import SqlLoadResult

    url = settings.base_url.rstrip("/") + "/raw?gzip_body=1"
    last_err: Optional[str] = None
    delay = 0.8
    for attempt in range(1, settings.retries + 1):
        try:
            req = Request(
                url,
                headers={
                    "X-WarRoom-Token": settings.token,
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                },
                method="GET",
            )
            with urlopen(req, timeout=settings.timeout_sec) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding", "").lower() == "gzip" or data[:2] == b"\x1f\x8b":
                    data = gzip.decompress(data)
                payload = json.loads(data.decode("utf-8"))
            status_body = payload.get("status") or {}
            status = SqlStatus(
                ok=bool(payload.get("ok") and status_body.get("ok", True)),
                message=str(status_body.get("message") or "gateway ok"),
                server=status_body.get("server") or "warroom-gateway",
                database=status_body.get("database"),
                engine="gateway",
                last_success_at=status_body.get("last_success_at") or payload.get("last_success_at"),
                error=status_body.get("error"),
            )
            sheets = payload.get("sheets") or {}
            raw: dict[str, Any] = {}
            for key, records in sheets.items():
                if isinstance(records, list):
                    raw[key] = _records_to_df(records, key if key in SCHEMA else key)
                else:
                    raw[key] = records
            # Ensure all SCHEMA keys exist
            for canon, spec in SCHEMA.items():
                if canon not in raw:
                    raw[canon] = pd.DataFrame({c.canonical: pd.Series(dtype=object) for c in spec.columns})
            return SqlLoadResult(
                raw=raw,
                status=status,
                warnings=list(payload.get("warnings") or []),
                mapping_complete=bool(payload.get("mapping_complete")),
                last_success_at=payload.get("last_success_at"),
                confidence_notes=list(payload.get("confidence_notes") or [])
                + [f"Источник: SQL gateway {settings.base_url}"],
            )
        except HTTPError as exc:
            last_err = f"HTTP {exc.code}: {exc.reason}"
        except URLError as exc:
            last_err = f"URL error: {exc.reason}"
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)[:300]
        if attempt < settings.retries:
            time.sleep(delay)
            delay = min(delay * 2, 8.0)
    return SqlLoadResult(
        raw={},
        status=SqlStatus(
            ok=False,
            message="SQL gateway недоступен",
            server=settings.base_url,
            error=last_err or "gateway_unreachable",
            engine="gateway",
        ),
        warnings=[last_err or "gateway_unreachable"],
        mapping_complete=False,
    )


def fetch_gateway_health(settings: GatewaySettings) -> dict[str, Any]:
    url = settings.base_url.rstrip("/") + "/health"
    req = Request(url, method="GET")
    with urlopen(req, timeout=min(30, settings.timeout_sec)) as resp:
        return json.loads(resp.read().decode("utf-8"))
