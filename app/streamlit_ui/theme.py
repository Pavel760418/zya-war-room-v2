"""Тема оформления: CSS, максимально повторяющий исходный War Room.

Переменные, цвета, радиусы, тени, типографика и классы карточек взяты из
``app/static/index.html`` практически один-в-один, плюс несколько правил,
чтобы «подружить» вёрстку со стандартным контейнером Streamlit.
"""
from __future__ import annotations

import streamlit as st

__all__ = ["inject_theme", "BADGE_COLORS"]

# Соответствие статусов цветам (для графиков и бейджей), как в оригинале.
BADGE_COLORS = {
    "green": "#44c06c",
    "yellow": "#f1b84a",
    "red": "#ff6c6c",
    "blue": "#5ea5ff",
    "primary": "#43d7c2",
}

_CSS = """
<style>
/* ==== Токены темы (как в исходном index.html, тёмная тема по умолчанию) ==== */
:root{
  --bg:#0b100f;--surface:#111816;--surface-2:#151f1b;--surface-3:#1b2621;
  --text:#edf4ef;--muted:#9baaa0;--border:rgba(237,244,239,.10);
  --primary:#43d7c2;--success:#44c06c;--warning:#f1b84a;--error:#ff6c6c;--blue:#5ea5ff;
  --shadow:0 16px 36px rgba(0,0,0,.34);
}

/* ==== Базовый фон и типографика ==== */
.stApp{
  background:radial-gradient(circle at top left, rgba(67,215,194,.12), transparent 20%), var(--bg);
  color:var(--text);
  font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
}
.block-container{max-width:1700px;padding:18px 26px 40px;}
#MainMenu,footer{visibility:hidden;height:0;}
header[data-testid="stHeader"]{background:transparent;}

/* ==== Карточки / панели ==== */
.panel,.card{
  background:linear-gradient(180deg,var(--surface),var(--surface-2));
  border:1px solid var(--border);border-radius:26px;box-shadow:var(--shadow);
}
.panel{padding:24px;} .card{padding:18px;}

.hero h1{margin:0 0 10px;font-size:32px;line-height:1.05;color:var(--text);}
.hero p{margin:0;color:var(--muted);max-width:90ch;}
.hero-meta{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-top:18px;}
.meta-box{padding:14px 16px;border:1px solid var(--border);border-radius:18px;background:rgba(255,255,255,.02);}
.meta-box .k{font-size:12px;color:var(--muted);margin-bottom:6px;}
.meta-box .v{font-size:18px;font-weight:800;color:var(--text);}
.pill{display:inline-flex;padding:10px 14px;border-radius:999px;background:rgba(67,215,194,.14);color:var(--primary);font-weight:800;margin-bottom:12px;}
.side .subtle{margin-bottom:8px;}

/* ==== KPI ==== */
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:16px;margin:4px 0 8px;}
.metric-label{font-size:12px;color:var(--muted);margin-bottom:8px;}
.metric-value{font-size:32px;font-weight:800;letter-spacing:-.03em;color:var(--text);}
.metric-sub{font-size:13px;color:var(--muted);margin-top:8px;}

/* ==== Цвета статусов ==== */
.green{color:var(--success)!important;} .yellow{color:var(--warning)!important;}
.red{color:var(--error)!important;} .blue{color:var(--blue)!important;}

/* ==== Списки: действия / алерты / рейтинги ==== */
.section-title{font-size:18px;font-weight:800;margin:0 0 12px;color:var(--text);}
.subtle{font-size:13px;color:var(--muted);}
.list{display:grid;gap:10px;}
.alert,.action,.rank{display:flex;justify-content:space-between;gap:12px;padding:12px 14px;border-radius:16px;border:1px solid var(--border);background:var(--surface-2);}
.alert strong,.action strong,.rank strong{color:var(--text);}
.badge{display:inline-flex;align-items:center;padding:6px 10px;border-radius:999px;font-size:12px;font-weight:800;white-space:nowrap;height:fit-content;}
.badge.green{background:rgba(68,192,108,.12);color:var(--success);}
.badge.yellow{background:rgba(241,184,74,.14);color:var(--warning);}
.badge.red{background:rgba(255,108,108,.12);color:var(--error);}
.badge.blue{background:rgba(94,165,255,.12);color:var(--blue);}

/* ==== Таблица магазинов ==== */
.table-wrap{max-height:520px;overflow:auto;}
table.war{width:100%;border-collapse:collapse;}
table.war th,table.war td{padding:10px 8px;border-bottom:1px solid var(--border);text-align:left;font-size:13px;}
table.war th{color:var(--muted);font-weight:600;position:sticky;top:0;background:var(--surface);}
table.war td{color:var(--text);}

/* ==== Drill-down ==== */
.mini-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;}
.mini{padding:12px;border:1px solid var(--border);border-radius:16px;background:var(--surface-2);}
.mini .v{font-size:22px;font-weight:800;color:var(--text);}
.reasons{display:grid;gap:10px;}
.reason{padding:12px 14px;border-radius:16px;background:var(--surface-2);border:1px solid var(--border);color:var(--text);}
.stack{display:grid;gap:16px;align-content:start;}
.drill-top{display:grid;grid-template-columns:1.1fr .9fr;gap:16px;}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px;}

/* Bordered-контейнеры Streamlit (для карточек с графиками) под стиль .card */
[data-testid="stVerticalBlockBorderWrapper"]{
  background:linear-gradient(180deg,var(--surface),var(--surface-2));
  border:1px solid var(--border)!important;border-radius:26px!important;
  box-shadow:var(--shadow);padding:8px 14px 4px;
}

/* ==== Sidebar ==== */
[data-testid="stSidebar"]{background:var(--surface);border-right:1px solid var(--border);}
[data-testid="stSidebar"] *{color:var(--text);}
.diag-head{font-size:15px;font-weight:800;margin:2px 0 10px;color:var(--text);}

@media(max-width:1320px){.hero-meta,.kpis{grid-template-columns:repeat(2,1fr);}.drill-top,.two{grid-template-columns:1fr;}}
@media(max-width:760px){.hero-meta,.kpis{grid-template-columns:1fr;}}
</style>
"""


def inject_theme() -> None:
    """Вставить CSS-тему в текущую страницу Streamlit."""
    st.markdown(
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">',
        unsafe_allow_html=True,
    )
    st.markdown(_CSS, unsafe_allow_html=True)
