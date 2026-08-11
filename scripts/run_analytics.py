#!/usr/bin/env python3
"""Run isolated WAR_ROM analytics API (does not touch Streamlit)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Load secrets the same way Streamlit/systemd do — without printing them.
from app.core.settings import _load_secret_files  # noqa: E402

_load_secret_files()

import uvicorn  # noqa: E402


def main() -> None:
    host = os.getenv("WARROM_ANALYTICS_HOST", "127.0.0.1")
    port = int(os.getenv("WARROM_ANALYTICS_PORT", "8510"))
    uvicorn.run("analytics.app:app", host=host, port=port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
