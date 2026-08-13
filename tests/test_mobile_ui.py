"""Мобильная вёрстка: узкий экран, сайдбар свёрнут, без зума iOS."""
from __future__ import annotations

from pathlib import Path

from app.streamlit_ui import theme


ROOT = Path(__file__).resolve().parents[1]


def test_sidebar_starts_collapsed_for_phones():
    text = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    assert 'initial_sidebar_state="collapsed"' in text


def test_theme_has_phone_breakpoints_and_ios_input_size():
    css = theme._CSS_BODY
    assert "@media (max-width: 700px)" in css
    assert "grid-template-columns: 1fr" in css
    assert "font-size: 16px !important" in css
    assert "safe-area-inset-bottom" in css
    assert "stDataFrame" in css
