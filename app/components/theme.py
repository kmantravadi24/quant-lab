"""Quant Lab design system: one place for colour, spacing, type and chart styling."""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# Colour tokens (dark neutral surface, two series colours, semantic status colours).
BG = "#0B0E14"
SURFACE = "#121722"
BORDER = "#222A38"
GRID = "#1C2330"
TEXT = "#E6EAF2"
MUTED = "#8B95A7"
ACCENT = "#5B8DEF"  # strategy / primary series
BENCH = "#E8A33D"  # benchmark / secondary series
POSITIVE = "#3FB68B"
NEGATIVE = "#E5605E"
VIOLET = "#A78BFA"
SERIES = [ACCENT, BENCH, POSITIVE, VIOLET, "#4FC3D9", NEGATIVE, "#9AA5B8"]

CSS = f"""
<style>
.block-container {{padding-top: 3.2rem; padding-bottom: 3rem; max-width: 1320px;}}
h1 {{font-size: 1.85rem !important; letter-spacing: -0.01em; padding-bottom: 0 !important;}}
h2 {{font-size: 1.25rem !important; margin-top: .6rem;}}
h3 {{font-size: 1.05rem !important; color: {TEXT};}}
[data-testid="stMetric"] {{background: {SURFACE}; border: 1px solid {BORDER};
  border-radius: 8px; padding: .7rem .9rem;}}
[data-testid="stMetricLabel"] p {{color: {MUTED}; font-size: .74rem; letter-spacing: .05em;
  text-transform: uppercase;}}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] div,
[data-testid="stMetricLabel"] p {{white-space: normal !important; overflow: visible !important;
  text-overflow: clip !important;}}
[data-testid="stMetricValue"] {{font-size: 1.4rem; font-variant-numeric: tabular-nums;}}
[data-testid="stMetricDelta"] {{font-size: .78rem; font-variant-numeric: tabular-nums;}}
[data-testid="stSidebar"] {{border-right: 1px solid {BORDER};}}
.ql-sub {{color: {MUTED}; margin: .1rem 0 .5rem 0; font-size: .98rem;}}
.ql-badge {{display: inline-block; padding: .16rem .65rem; border-radius: 999px;
  font-size: .74rem; font-weight: 600; letter-spacing: .04em; border: 1px solid;
  margin-right: .5rem;}}
.ql-live {{color: {POSITIVE}; border-color: {POSITIVE}66; background: {POSITIVE}14;}}
.ql-frozen {{color: {VIOLET}; border-color: {VIOLET}66; background: {VIOLET}14;}}
.ql-user {{color: {ACCENT}; border-color: {ACCENT}66; background: {ACCENT}14;}}
.ql-synthetic {{color: {BENCH}; border-color: {BENCH}88; background: {BENCH}1F;}}
.ql-meta {{color: {MUTED}; font-size: .82rem;}}
.ql-card {{background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
  padding: .9rem 1rem; height: 100%;}}
.ql-card b {{color: {TEXT};}} .ql-card span {{color: {MUTED}; font-size: .88rem;}}
/* Narrow screens: let rows of metric cards wrap instead of truncating their values. */
@media (max-width: 1320px) {{
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {{flex-wrap: wrap;}}
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"] {{
    min-width: 165px; flex: 1 1 165px;}}
}}
</style>
"""


def register_plotly_template() -> None:
    template = go.layout.Template()
    template.layout = go.Layout(
        font=dict(color=TEXT, size=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=SERIES,
        hovermode="x unified",
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=BORDER, font=dict(color=TEXT)),
        margin=dict(l=10, r=10, t=56, b=10),
        title=dict(font=dict(size=14, color=TEXT), x=0, xanchor="left", y=0.98, yanchor="top"),
        legend=dict(orientation="h", y=1.0, yanchor="bottom", x=1, xanchor="right",
                    font=dict(size=11, color=MUTED)),
        xaxis=dict(gridcolor=GRID, zeroline=False, linecolor=BORDER,
                   title=dict(font=dict(size=11, color=MUTED))),
        yaxis=dict(gridcolor=GRID, zeroline=False, linecolor=BORDER,
                   title=dict(font=dict(size=11, color=MUTED))),
    )  # fmt: skip
    pio.templates["quantlab"] = template
    pio.templates.default = "quantlab"
