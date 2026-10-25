"""Colours, unit-type palette and the Plotly template of the GUI.

The categorical hues are the dark-surface steps of the reference data-viz
palette. Each unit *type* owns one hue; several units of the same type get
lightness steps of that hue, so a unit keeps the same colour in every chart.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# ---------------------------------------------------------------- surfaces & ink
PAGE = "#0f1110"
SURFACE = "#1a1a19"
INK = "#f0efec"
INK_2 = "#c3c2b7"
MUTED = "#898781"
GRID = "#2c2c2a"
AXIS = "#383835"
ACCENT = "#2dd4bf"          # teal accent (UI only, never a data series)

# ---------------------------------------------------------------- unit types
TYPE_LABELS = {
    "thermal": "Thermal / diesel",
    "biomass": "Biomass / CHP",
    "wind": "Wind",
    "pv": "PV",
    "hybrid": "Hybrid RES (with BESS)",
    "partial": "Partially controllable",
    "storage": "Battery (BESS)",
}
TYPE_BASE = {
    "thermal": "#d95926",   # orange
    "biomass": "#008300",   # green
    "wind": "#3987e5",      # blue
    "pv": "#c98500",        # yellow
    "hybrid": "#9085e9",    # violet
    "partial": "#d55181",   # magenta
    "storage": "#9085e9",   # violet (same family as hybrid, stepped)
}
TYPE_ICON = {"thermal": "🔥", "biomass": "🌿", "wind": "🌬️", "pv": "☀️",
             "hybrid": "🔋", "partial": "⚙️", "storage": "🔋"}
LOAD = INK                  # load forecast line
LOAD_SHED = "#e66767"       # red: load shedding / unserved energy
EXCESS = "#d55181"          # magenta: excess generation slack
EXPECTED = INK              # bold expected-value line

# Status colours are reserved for state, never for series.
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}

# Sequential blue ramp (light -> dark) for scenarios and magnitudes.
SEQUENTIAL = ["#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95"]
# Commitment heatmap classes.
STATE_CLASS_COLORS = {"Off": "#2c2c2a", "Shutdown state": "#4a4a46",
                      "Transient": "#c98500", "Operational": "#199e70"}


def _mix(hex_color: str, target: str, amount: float) -> str:
    """Blend ``hex_color`` towards ``target`` by ``amount`` (0..1)."""
    a = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(target[i:i + 2], 16) for i in (1, 3, 5)]
    mixed = [round(x + (y - x) * amount) for x, y in zip(a, b)]
    return "#" + "".join(f"{v:02x}" for v in mixed)


# Lightness steps used for the 1st, 2nd, ... unit of a type.
_STEPS = [0.0, 0.30, -0.30, 0.50, -0.45, 0.15, -0.15, 0.65]


def type_shade(unit_type: str, k: int) -> str:
    """Colour of the k-th unit (0-based) of ``unit_type``."""
    base = TYPE_BASE.get(unit_type, MUTED)
    step = _STEPS[k % len(_STEPS)]
    return _mix(base, "#ffffff", step) if step >= 0 else _mix(base, "#000000", -step)


def scenario_colors(ids: list[str]) -> dict[str, str]:
    """Consistent sequential colour per scenario (by its position in the case)."""
    n = max(len(ids), 1)
    if n == 1:
        return {ids[0]: SEQUENTIAL[3]} if ids else {}
    return {sid: SEQUENTIAL[round(i * (len(SEQUENTIAL) - 1) / (n - 1))] for i, sid in enumerate(ids)}


def rgba(hex_color: str, alpha: float) -> str:
    """Hex colour to an rgba() string."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


# ---------------------------------------------------------------- Plotly template
def _template() -> go.layout.Template:
    axis = dict(gridcolor=GRID, linecolor=AXIS, zerolinecolor=AXIS, tickcolor=AXIS,
                tickfont=dict(color=MUTED, size=12), title=dict(font=dict(color=INK_2, size=13)),
                showline=True, ticks="outside", ticklen=4, automargin=True)
    return go.layout.Template(layout=dict(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif", color=INK_2, size=13),
        title=dict(font=dict(color=INK, size=15), x=0, xanchor="left"),
        xaxis=axis, yaxis=axis,
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=INK_2, size=12), orientation="v",
                    yanchor="top", y=1, xanchor="left", x=1.01, tracegroupgap=2),
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=AXIS, font=dict(color=INK)),
        hovermode="x unified",
        margin=dict(l=56, r=20, t=56, b=40),
        colorway=[TYPE_BASE[k] for k in ("wind", "thermal", "pv", "partial", "biomass", "hybrid")],
    ))


pio.templates["rdas_dark"] = _template()
PLOT_TEMPLATE = "rdas_dark"


def plotly_config(filename: str) -> dict:
    """Plotly toolbar config: PNG export at 2x, no logo."""
    return {"displaylogo": False,
            "toImageButtonOptions": {"format": "png", "filename": filename, "scale": 2},
            "modeBarButtonsToRemove": ["lasso2d", "select2d"]}


CSS = f"""
<style>
.block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1500px; }}
h1, h2, h3 {{ letter-spacing: -0.01em; }}
.kpi-card {{ background: {SURFACE}; border: 1px solid {GRID}; border-radius: 12px;
            padding: 14px 16px 12px 16px; height: 100%; }}
.kpi-label {{ color: {MUTED}; font-size: 0.78rem; text-transform: uppercase; letter-spacing: .06em; }}
.kpi-value {{ color: {INK}; font-size: 1.55rem; font-weight: 600; line-height: 1.25; margin-top: 2px; }}
.kpi-unit {{ color: {INK_2}; font-size: 0.9rem; font-weight: 400; margin-left: 4px; }}
.kpi-sub {{ color: {INK_2}; font-size: 0.8rem; margin-top: 4px; }}
.kpi-accent {{ border-left: 3px solid {ACCENT}; }}
.section-note {{ color: {MUTED}; font-size: 0.85rem; margin-top: -0.4rem; margin-bottom: .6rem; }}
.common-tag {{ display:inline-block; background: rgba(45,212,191,.12); color: {ACCENT};
              border: 1px solid rgba(45,212,191,.35); border-radius: 999px; padding: 1px 10px;
              font-size: .78rem; font-weight: 600; margin-left: 6px; vertical-align: middle; }}
.scen-tag {{ display:inline-block; background: rgba(57,135,229,.12); color: #86b6ef;
            border: 1px solid rgba(57,135,229,.35); border-radius: 999px; padding: 1px 10px;
            font-size: .78rem; font-weight: 600; margin-left: 6px; vertical-align: middle; }}
.legend-chip {{ display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:6px; }}
div[data-testid="stSidebarUserContent"] {{ padding-top: 1rem; }}
</style>
"""
