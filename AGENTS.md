# AGENTS.md

## Cursor Cloud specific instructions

This repo contains **two front-ends over one shared business core** (ZYA War Room v2 — an operational dashboard): the original **FastAPI + static SPA**, and a **Streamlit** version. No database, no frontend build step, no Docker. See `README.md` for canonical setup/run commands.

- Shared core: `app/services/metrics_service.py` (KPI/drilldown/action logic) + `app/models/schemas.py`. Both front-ends reuse it; don't fork the logic.
- Robust Excel ingestion lives in `app/ingestion/` (`schema`, `excel_loader`, `data_mapping`, `data_validation`, `error_handling`, `pipeline`, `sample_inputs`). It returns a `raw` dict shaped exactly like what `MetricsService(..., mode='excel')` expects, so the calc layer is untouched.
- Streamlit UI lives in `app/streamlit_ui/` (`theme`, `formatting`, `render`, `charts`, `views`, `diagnostics`, `data_access`); entrypoint is `streamlit_app.py`.

### Services

| Service | Command | Port | Notes |
|---------|---------|------|-------|
| Streamlit app | `.venv/bin/streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true` | 8501 | Sidebar navigation + data source + Excel upload; reuses the shared core |
| FastAPI app (API + static UI) | `.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` | 8000 | Original app, still works. Serves JSON API + static SPA (`app/static/index.html`) |

- Streamlit UI: `http://127.0.0.1:8501/`. FastAPI UI: `http://127.0.0.1:8000/` (add `?mode=demo` for synthetic data). API docs: `http://127.0.0.1:8000/docs`.
- Key FastAPI endpoints: `GET /api/v1/filters`, `GET /api/v1/dashboard`, `POST /api/v1/upload/excel` (all accept `mode=excel|demo`).
- Tests: `.venv/bin/python -m pytest -q` (ingestion robustness smoke/unit tests in `tests/`).

### Non-obvious caveats

- Always use the venv interpreter (`.venv/bin/uvicorn` / `.venv/bin/python`); there is no `python` on PATH, only `python3`.
- The repository originally committed a **Windows** `.venv` (Python 3.10, `Lib/`+`Scripts/`). That is unusable on Linux and is now git-ignored; the Linux venv is recreated by the update script. If you pull a state where `.venv` still contains Windows files, delete it and run `python3 -m venv .venv` again.
- Creating the venv requires the system package `python3.12-venv` (provides `ensurepip`). It is part of the base VM environment; if `python3 -m venv` fails with an `ensurepip` error, install it with `sudo apt-get install -y python3.12-venv`.
- There is no separate lint config; "build" is a no-op (frontend is static HTML / Streamlit-rendered). Tests exist only for the ingestion layer (`pytest`).
- Excel pilot mode reads `data/war-room-template-2-no-traffic.xlsx` (path in `app/core/config.py`). Demo mode needs no external files. In Streamlit, an uploaded file overrides the reference file for the session.
- Charts/fonts load from CDNs (`cdn.jsdelivr.net`, `fonts.googleapis.com` for FastAPI; Plotly assets for Streamlit); apps still function offline but visuals may degrade.
- **Streamlit hot-reload gotcha:** after many edit/save cycles, `streamlit run` (with `runOnSave`) can get into a stale state where the sidebar/widgets stop rendering correctly even though the code is fine. If the UI looks wrong after edits, fully restart the Streamlit process (kill the PID and re-run) rather than trusting the hot-reloaded view.
- Streamlit renders the dashboard via injected HTML/CSS (`app/streamlit_ui/theme.py` + `render.py`) to match the original design; charts are Plotly. If you change the visual design, edit those modules, not `app/static/index.html`.
