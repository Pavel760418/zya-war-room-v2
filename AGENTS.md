# AGENTS.md

## Cursor Cloud specific instructions

This is a single self-contained **FastAPI** app (ZYA War Room v2 — an operational dashboard). No database, no frontend build step, no Docker. See `README.md` for the canonical setup/run commands.

### Services

| Service | Command | Port | Notes |
|---------|---------|------|-------|
| FastAPI app (API + static UI) | `.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` | 8000 | Serves both the JSON API and the static SPA (`app/static/index.html`) |

- UI: `http://127.0.0.1:8000/` (Excel pilot mode, default) and `http://127.0.0.1:8000/?mode=demo` (synthetic data).
- API docs: `http://127.0.0.1:8000/docs`.
- Key endpoints: `GET /api/v1/filters`, `GET /api/v1/dashboard`, `POST /api/v1/upload/excel` (all accept `mode=excel|demo`).

### Non-obvious caveats

- Always use the venv interpreter (`.venv/bin/uvicorn` / `.venv/bin/python`); there is no `python` on PATH, only `python3`.
- The repository originally committed a **Windows** `.venv` (Python 3.10, `Lib/`+`Scripts/`). That is unusable on Linux and is now git-ignored; the Linux venv is recreated by the update script. If you pull a state where `.venv` still contains Windows files, delete it and run `python3 -m venv .venv` again.
- Creating the venv requires the system package `python3.12-venv` (provides `ensurepip`). It is part of the base VM environment; if `python3 -m venv` fails with an `ensurepip` error, install it with `sudo apt-get install -y python3.12-venv`.
- There is **no lint, test, or build tooling** configured in this repo (no `pytest`, no `Makefile`, no CI, no `package.json`). "Build" is a no-op — the frontend is static HTML served as-is.
- Excel pilot mode reads `data/war-room-template-2-no-traffic.xlsx` (path in `app/core/config.py`). Demo mode needs no external files.
- Charts/fonts load from CDNs (`cdn.jsdelivr.net`, `fonts.googleapis.com`); the app still functions offline but visuals may degrade.
