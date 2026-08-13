"""Тема оформления War Room.

ВАЖНО: не трогать overflow/width у нативных виджетов Streamlit (radio, button, select).
Именно глобальный CSS раньше «ломал» кириллицу: День→моб, Светлая→калила, Магазин→левый.
"""
from __future__ import annotations

import streamlit as st

__all__ = ["inject_theme", "render_theme_toggle", "BADGE_COLORS", "DEFAULT_THEME"]

DEFAULT_THEME = "dark"

BADGE_COLORS = {
    "green": "#44c06c",
    "yellow": "#f1b84a",
    "red": "#ff6c6c",
    "blue": "#5ea5ff",
    "primary": "#43d7c2",
}

_FONT = "system-ui, 'Segoe UI', 'Noto Sans', Arial, sans-serif"

_TOKENS_DARK = """
  --bg:#0b100f;--surface:#111816;--surface-2:#151f1b;--surface-3:#1b2621;
  --text:#edf4ef;--muted:#9baaa0;--border:rgba(237,244,239,.12);
  --primary:#43d7c2;--success:#44c06c;--warning:#f1b84a;--error:#ff6c6c;--blue:#5ea5ff;
  --shadow:0 12px 28px rgba(0,0,0,.30);
  --app-glow:rgba(67,215,194,.10);
"""

_TOKENS_LIGHT = """
  --bg:#f3f7f5;--surface:#ffffff;--surface-2:#eef3f0;--surface-3:#e4ece7;
  --text:#15201b;--muted:#4d5c54;--border:rgba(21,32,27,.12);
  --primary:#167a6c;--success:#146c34;--warning:#8a5a0a;--error:#b71c1c;--blue:#1565c0;
  --shadow:0 10px 24px rgba(21,32,27,.08);
  --app-glow:rgba(26,158,140,.08);
"""

# Только оформление фона/карточек. Без overflow/width на label/button/p.
_CSS_BODY = f"""
:root {{ --ui-font:{_FONT}; }}
.stApp {{
  background: radial-gradient(circle at top left, var(--app-glow), transparent 22%), var(--bg);
  color: var(--text);
  font-family: var(--ui-font);
}}
.block-container {{ max-width: min(1920px, 100%) !important; padding: 16px 20px 40px !important; }}
#MainMenu, footer {{ visibility: hidden; height: 0; }}
header[data-testid="stHeader"] {{ background: transparent; }}

.panel, .card {{
  background: linear-gradient(180deg, var(--surface), var(--surface-2));
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: var(--shadow);
  padding: 18px;
}}
.panel {{ padding: 22px; }}
.pill {{
  display: inline-block;
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(67,215,194,.14);
  color: var(--primary);
  font-weight: 700;
  margin-bottom: 10px;
}}
.section-title {{
  font-size: 20px;
  font-weight: 700;
  margin: 0 0 10px;
  color: var(--text);
}}
.subtle {{ font-size: 14px; color: var(--muted); line-height: 1.4; }}
.focus-note {{
  border: 1px solid rgba(241,184,74,.4);
  border-radius: 14px;
  padding: 12px 14px;
  margin: 10px 0 14px;
  background: var(--surface-2);
  font-size: 15px;
  line-height: 1.4;
  color: var(--text);
}}
.kpis {{
  display: grid;
  grid-template-columns: repeat(4, minmax(140px, 1fr));
  gap: 12px;
  margin: 4px 0 12px;
}}
.kpis-stack {{
  display: flex !important;
  flex-direction: column;
  gap: 8px;
  margin: 4px 0 0;
  grid-template-columns: none !important;
}}
.kpis-stack > .card {{
  padding: 10px 12px;
  min-width: 0;
  overflow: hidden;
}}
.kpis-stack .metric-value {{
  font-size: 22px;
  line-height: 1.2;
  overflow-wrap: anywhere;
  word-break: break-word;
}}
.kpis-stack .metric-sub {{
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
  font-size: 12px;
}}
.kpis-stack .metric-label {{ font-size: 12px; }}
[data-testid="stHorizontalBlock"] > div {{
  min-width: 0 !important;
}}
.metric-label {{ font-size: 13px; color: var(--muted); margin-bottom: 6px; }}
.metric-value {{ font-size: 28px; font-weight: 700; color: var(--text); }}
.metric-sub {{ font-size: 13px; color: var(--muted); margin-top: 6px; white-space: normal; }}
.green {{ color: var(--success) !important; }}
.yellow {{ color: var(--warning) !important; }}
.red {{ color: var(--error) !important; }}
.blue {{ color: var(--blue) !important; }}

[data-testid="stSidebar"] {{ background: var(--surface); border-right: 1px solid var(--border); }}
[data-testid="stVerticalBlockBorderWrapper"] {{
  background: linear-gradient(180deg, var(--surface), var(--surface-2));
  border: 1px solid var(--border) !important;
  border-radius: 18px !important;
  box-shadow: var(--shadow);
  padding: 8px 12px 4px;
}}

/* Защита нативных виджетов: никогда не обрезать подписи */
div[role="radiogroup"] label,
div[role="radiogroup"] label *,
[data-testid="stButton"] button,
[data-testid="stButton"] button *,
[data-testid="stSelectbox"] label,
[data-testid="stSelectbox"] label *,
[data-baseweb="select"],
[data-baseweb="select"] * {{
  overflow: visible !important;
  text-overflow: clip !important;
  max-width: none !important;
  white-space: normal !important;
}}
div[role="radiogroup"] label p {{
  font-size: 15px !important;
  font-weight: 600 !important;
}}

@media (max-width: 1100px) {{
  .kpis:not(.kpis-stack) {{ grid-template-columns: repeat(2, minmax(140px, 1fr)); }}
}}
@media (max-width: 700px) {{
  .kpis:not(.kpis-stack) {{ grid-template-columns: 1fr; }}
  .block-container {{
    padding: 8px 10px calc(28px + env(safe-area-inset-bottom, 0px)) !important;
  }}
  .wr-brand {{ font-size: 26px !important; }}
  .metric-value {{ font-size: 22px; }}
  .card, .panel {{ padding: 12px; border-radius: 14px; }}
  /* iOS Safari не зумит поля, если шрифт ≥16px */
  input, textarea, select,
  [data-baseweb="input"] input,
  [data-baseweb="select"] input,
  [data-baseweb="input"] textarea {{
    font-size: 16px !important;
  }}
  [data-testid="stDataFrame"],
  [data-testid="stDataFrameResizable"] {{
    overflow-x: auto;
  }}
}}

.wr-brand {{
  font-size: clamp(28px, 4.2vw, 44px);
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.05;
  margin: 0 0 6px;
  color: var(--text);
  text-shadow: 0 0 22px rgba(67,215,194,.55), 0 0 4px rgba(67,215,194,.35);
}}
[data-testid="stMetricValue"],
[data-testid="stMetricDelta"],
[data-testid="stMetricLabel"] {{
  overflow: visible !important;
  text-overflow: clip !important;
  white-space: normal !important;
  word-break: break-word;
}}
[data-testid="stMetricValue"] {{
  font-size: 1.15rem !important;
  line-height: 1.25 !important;
}}

/* Оверлей «AI Агент работает» при пересчёте */
.wr-ai-overlay {{
  display: none;
  position: fixed;
  inset: 0;
  z-index: 99999;
  background: rgba(8, 12, 11, .72);
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 18px;
  pointer-events: none;
}}
.stApp[data-test-script-state="running"] .wr-ai-overlay,
body:has([data-testid="stSpinner"]) .wr-ai-overlay,
.stApp:has([data-testid="stSpinner"]) .wr-ai-overlay {{
  display: flex;
}}
.wr-bot-head {{
  width: 132px;
  height: 132px;
  border-radius: 28px;
  background: linear-gradient(180deg, #1c2a26, #101816);
  border: 3px solid var(--primary);
  box-shadow: 0 0 32px rgba(67,215,194,.45);
  position: relative;
  animation: wr-bot-bob 1.4s ease-in-out infinite;
}}
.wr-bot-eye {{
  position: absolute;
  top: 42px;
  width: 28px;
  height: 28px;
  background: #edf4ef;
  border-radius: 50%;
  overflow: hidden;
}}
.wr-bot-eye.left {{ left: 26px; }}
.wr-bot-eye.right {{ right: 26px; }}
.wr-bot-eye .pupil {{
  width: 12px;
  height: 12px;
  background: #0b100f;
  border-radius: 50%;
  position: absolute;
  top: 8px;
  left: 8px;
  animation: wr-eye 1.6s ease-in-out infinite;
}}
.wr-bot-mouth {{
  position: absolute;
  left: 50%;
  bottom: 28px;
  width: 42px;
  height: 10px;
  margin-left: -21px;
  border-radius: 0 0 12px 12px;
  border-bottom: 3px solid var(--primary);
  animation: wr-mouth 1.4s ease-in-out infinite;
}}
.wr-ai-label {{
  font-size: 22px;
  font-weight: 800;
  color: #edf4ef;
  letter-spacing: .02em;
  text-shadow: 0 0 16px rgba(67,215,194,.5);
}}
@keyframes wr-bot-bob {{
  0%, 100% {{ transform: translateY(0); }}
  50% {{ transform: translateY(-8px); }}
}}
@keyframes wr-eye {{
  0%, 100% {{ transform: translate(0, 0); }}
  25% {{ transform: translate(6px, 2px); }}
  50% {{ transform: translate(-4px, 3px); }}
  75% {{ transform: translate(3px, -2px); }}
}}
@keyframes wr-mouth {{
  0%, 100% {{ width: 42px; margin-left: -21px; }}
  50% {{ width: 28px; margin-left: -14px; }}
}}
[data-testid="stSpinner"] {{
  position: relative;
  z-index: 100000;
}}
"""


def _ensure_theme_state() -> str:
    theme = st.session_state.get("ui_theme", DEFAULT_THEME)
    if theme not in {"dark", "light"}:
        theme = DEFAULT_THEME
        st.session_state["ui_theme"] = theme
    return theme


def inject_theme() -> None:
    theme = _ensure_theme_state()
    tokens = _TOKENS_LIGHT if theme == "light" else _TOKENS_DARK
    st.markdown(f"<style>\n:root{{{tokens}}}\n{_CSS_BODY}\n</style>", unsafe_allow_html=True)
    st.markdown(
        "<div class='wr-ai-overlay' aria-hidden='true'>"
        "<div class='wr-bot-head'>"
        "<div class='wr-bot-eye left'><div class='pupil'></div></div>"
        "<div class='wr-bot-eye right'><div class='pupil'></div></div>"
        "<div class='wr-bot-mouth'></div>"
        "</div>"
        "<div class='wr-ai-label'>AI Агент работает!</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def render_theme_toggle(*, location: str = "sidebar") -> None:
    """Переключатель темы через radio — без emoji и без длинных фраз в button (они клипались)."""
    theme = _ensure_theme_state()
    options = ["Тёмная", "Светлая"]
    current = "Светлая" if theme == "light" else "Тёмная"
    key = f"theme_radio_{location}"
    choice = st.radio(
        "Тема оформления",
        options,
        index=options.index(current),
        horizontal=True,
        key=key,
        help="Тёмная — по умолчанию. Светлая — альтернатива.",
    )
    new_theme = "light" if choice == "Светлая" else "dark"
    if new_theme != theme:
        st.session_state["ui_theme"] = new_theme
        st.rerun()
