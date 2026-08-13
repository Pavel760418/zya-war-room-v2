"""Графики War Room на Plotly с цветами и тёмной темой из оригинала.

Повторяют два ключевых графика исходного дашборда:
- «Выполнение плана по магазинам» — bar chart, цвет столбца по статусу;
- «Структура потерь» — doughnut.
"""
from __future__ import annotations

import plotly.graph_objects as go

from app.streamlit_ui.theme import BADGE_COLORS

__all__ = ["plan_chart", "losses_chart", "losses_pct_chart"]

_AXIS_COLOR = "#9baaa0"
_GRID_COLOR = "rgba(155,170,160,.15)"
_DOUGHNUT_COLORS = [
    "#44c06c", "#f1b84a", "#5ea5ff", "#ff6c6c", "#43d7c2",
    "#c084fc", "#fb923c", "#34d399", "#60a5fa", "#f472b6",
]


def _base_layout(height: int = 300) -> dict:
    return dict(
        height=height,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=_AXIS_COLOR, family="Inter, sans-serif"),
    )


def plan_chart(plan_vs_store: list[dict]) -> go.Figure:
    """Bar chart выполнения плана по магазинам (цвет — по статусу)."""
    labels = [x.get("store", "") for x in plan_vs_store]
    values = [x.get("plan_pct") or 0 for x in plan_vs_store]
    colors = [
        BADGE_COLORS.get(x.get("status_color"), BADGE_COLORS["blue"]) for x in plan_vs_store
    ]
    fig = go.Figure(
        go.Bar(x=labels, y=values, marker=dict(color=colors), marker_line_width=0,
               hovertemplate="%{x}<br>%{y:.1f}%<extra></extra>")
    )
    fig.update_layout(**_base_layout(), showlegend=False)
    fig.update_xaxes(showgrid=False, tickfont=dict(color=_AXIS_COLOR))
    fig.update_yaxes(gridcolor=_GRID_COLOR, tickfont=dict(color=_AXIS_COLOR), zeroline=False)
    fig.update_traces(marker=dict(cornerradius=8))
    return fig


def losses_pct_chart(rows: list[dict]) -> go.Figure:
    """Bar chart потерь % к выручке (вместо плана, когда план не задан)."""
    labels = [x.get("store", "") for x in rows]
    values = [x.get("losses_pct") or 0 for x in rows]
    colors = [
        BADGE_COLORS.get(x.get("status_color"), BADGE_COLORS["blue"]) for x in rows
    ]
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            marker=dict(color=colors),
            marker_line_width=0,
            hovertemplate="%{x}<br>%{y:.2f}% к выручке<extra></extra>",
        )
    )
    fig.update_layout(**_base_layout(), showlegend=False)
    fig.update_xaxes(showgrid=False, tickfont=dict(color=_AXIS_COLOR))
    fig.update_yaxes(gridcolor=_GRID_COLOR, tickfont=dict(color=_AXIS_COLOR), zeroline=False)
    fig.update_traces(marker=dict(cornerradius=8))
    return fig


def losses_chart(losses_structure: list[dict]) -> go.Figure:
    """Doughnut «структура потерь»."""
    labels = [x.get("group", "") for x in losses_structure]
    values = [x.get("amount") or 0 for x in losses_structure]
    fig = go.Figure(
        go.Pie(labels=labels, values=values, hole=0.62,
               marker=dict(colors=_DOUGHNUT_COLORS),
               textinfo="none",
               hovertemplate="%{label}<br>%{value:.1f} тыс. руб. (%{percent})<extra></extra>")
    )
    layout = _base_layout()
    layout["legend"] = dict(font=dict(color=_AXIS_COLOR), orientation="v")
    fig.update_layout(**layout)
    return fig
