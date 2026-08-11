# Inventory — WAR_ROM analytics isolation (2026-08-11)

## Deployed Streamlit (immutable)

| Item | Value |
|------|--------|
| Entrypoint | `streamlit_app.py` |
| systemd | `warroom-streamlit.service` (user) |
| Bind | `127.0.0.1:8502` |
| Proxy | `warroom-proxy.service` → `0.0.0.0:8501` |
| URL | http://192.168.2.95:8501 |
| Health before/after | 200 / 200 |

**Forbidden to change for this work:** `streamlit_app.py`, `app/streamlit_ui/*`, Streamlit systemd unit, port, design, KPI cards, filters.

Backup: `~/.config/warroom/backups/YYYYMMDD/`

## Integration points (safe)

- Existing SQL repos under `app/repositories/retail_*.py`, `app/domain/*`
- New isolated package `analytics/`
- Service DB SQLite `var/db/warroom_service.sqlite`
- New service `warroom-analytics.service` on `127.0.0.1:8510`

## Risks

- Official XLSX at `/opt/war_rom/...` absent → temporary SQL INFORMATION_SCHEMA probe
- COGS/stock/writeoffs remain candidates
- Analytics only on localhost (no public proxy by default)

## New files

See `docs/analytics/README.md` and package `analytics/`.
