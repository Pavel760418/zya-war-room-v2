# WAR_ROM Analytics — isolated SQL layer (production Streamlit untouched)

## Boundaries

- Production Streamlit: `streamlit_app.py` + `warroom-streamlit.service` on `127.0.0.1:8502` (proxy `:8501`) — **do not modify for analytics**.
- Analytics API: `analytics/` + `warroom-analytics.service` on `127.0.0.1:8510`.
- SQL Server `retail`: **SELECT only**.
- Service DB: SQLite `var/db/warroom_service.sqlite` (metadata catalog + semantic entities).

## 1C structure map XLSX

Place official file at either:

- `/opt/war_rom/data/1c/СтруктураХраненияБазыДанных.xlsx`
- or `var/data/1c/СтруктураХраненияБазыДанных.xlsx`
- or set `WARROM_1C_STRUCTURE_XLSX` in `warroom.env`

Import: `POST /api/admin/metadata/1c-storage-map/import`

Admin UI: `http://127.0.0.1:8510/admin/1c-storage-map`

## Commands

```bash
systemctl --user status warroom-streamlit.service
systemctl --user status warroom-analytics.service
journalctl --user -u warroom-analytics.service -n 50 --no-pager
systemctl --user restart warroom-analytics.service
curl -s http://127.0.0.1:8510/health
```
