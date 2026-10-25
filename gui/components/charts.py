"""Plotly figures. Every unit keeps its colour; scenarios use one sequential hue.

All figures share the ``rdas_dark`` template, carry axis units and show a
hover tooltip. ``show`` renders a figure with PNG export enabled.
"""

from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from gui import theme
from gui.adapter import axis_title, period_label

STACK_ORDER = ["thermal", "biomass", "partial", "wind", "hybrid", "pv", "storage"]


def show(fig: go.Figure, filename: str, key: str | None = None) -> None:
    st.plotly_chart(fig, config=theme.plotly_config(filename), key=key, theme=None)


def _time_axis(fig: go.Figure, minutes: int, periods: list[int], row: int | None = None, col: int | None = None,
               title: bool = True) -> None:
    kwargs = dict(title_text=axis_title(minutes) if title else None)
    if minutes != 60:
        step = max(1, len(periods) // 8)
        ticks = periods[::step]
        kwargs.update(tickmode="array", tickvals=ticks, ticktext=[period_label(t, minutes) for t in ticks])
    else:
        kwargs.update(dtick=1 if len(periods) <= 12 else 2)
    if row is None:
        fig.update_xaxes(**kwargs)
    else:
        fig.update_xaxes(row=row, col=col, **kwargs)


def _base(title: str, ytitle: str, height: int = 420) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(template=theme.PLOT_TEMPLATE, title=title, height=height, yaxis_title=ytitle)
    return fig


def _ordered_units(units: pd.DataFrame, present: set[str]) -> list[str]:
    frame = units[units["unit"].isin(present)].copy()
    frame["_o"] = frame["type"].map({k: i for i, k in enumerate(STACK_ORDER)}).fillna(99)
    return frame.sort_values(["_o", "index"])["unit"].tolist()


# ------------------------------------------------------------------ dispatch
def dispatch_stack(dispatch: pd.DataFrame, load: pd.DataFrame, units: pd.DataFrame, minutes: int,
                   title: str, periods: list[int], height: int = 440) -> go.Figure:
    """Stacked dispatch (MW) per unit with load, load shedding and BESS charging."""
    fig = _base(title, "Power (MW)", height)
    colors = dict(zip(units["unit"], units["color"]))
    present = set(dispatch["unit"])
    for unit in _ordered_units(units, present):
        d = dispatch[dispatch["unit"] == unit].sort_values("t")
        pos = d["mw"].clip(lower=0)
        if pos.abs().sum() > 1e-9:
            fig.add_trace(go.Scatter(
                x=d["t"], y=pos, name=unit, stackgroup="gen", mode="lines",
                line=dict(width=1.5, color=theme.SURFACE), fillcolor=colors.get(unit, theme.MUTED),
                hovertemplate="%{y:.2f} MW", legendgroup=unit))
        neg = d["mw"].clip(upper=0)
        if neg.abs().sum() > 1e-9:
            fig.add_trace(go.Scatter(
                x=d["t"], y=neg, name=f"{unit} charging", stackgroup="charge", mode="lines",
                line=dict(width=1.5, color=theme.SURFACE), fillcolor=theme.rgba(colors.get(unit, theme.MUTED), .55),
                hovertemplate="%{y:.2f} MW", legendgroup=unit))
    if not load.empty:
        lo = load.sort_values("t")
        if lo["shed_mw"].abs().sum() > 1e-9:
            fig.add_trace(go.Scatter(x=lo["t"], y=lo["shed_mw"], name="Load shedding", stackgroup="gen",
                                     mode="lines", line=dict(width=1.5, color=theme.SURFACE),
                                     fillcolor=theme.LOAD_SHED, hovertemplate="%{y:.2f} MW"))
        fig.add_trace(go.Scatter(x=lo["t"], y=lo["load_mw"], name="Load forecast", mode="lines+markers",
                                 line=dict(width=3, color=theme.LOAD), marker=dict(size=7, color=theme.LOAD),
                                 hovertemplate="%{y:.2f} MW"))
    _time_axis(fig, minutes, periods)
    return fig


def dispatch_small_multiples(dispatch: pd.DataFrame, load: pd.DataFrame, units: pd.DataFrame, minutes: int,
                             periods: list[int], probabilities: dict[str, float]) -> go.Figure:
    """One small stacked chart per scenario, shared y-axis."""
    scenarios = list(dict.fromkeys(dispatch["scenario"]))
    cols = 2 if len(scenarios) > 1 else 1
    rows = math.ceil(len(scenarios) / cols)
    fig = make_subplots(rows=rows, cols=cols, shared_yaxes=True, shared_xaxes=True,
                        subplot_titles=[f"{s}  (p = {probabilities.get(s, 0):.3f})" for s in scenarios],
                        vertical_spacing=0.12 / max(rows, 1) + 0.04, horizontal_spacing=0.05)
    colors = dict(zip(units["unit"], units["color"]))
    order = _ordered_units(units, set(dispatch["unit"]))
    for k, sid in enumerate(scenarios):
        r, c = k // cols + 1, k % cols + 1
        d_s = dispatch[dispatch["scenario"] == sid]
        for unit in order:
            d = d_s[d_s["unit"] == unit].sort_values("t")
            fig.add_trace(go.Scatter(x=d["t"], y=d["mw"].clip(lower=0), name=unit, stackgroup=f"g{k}",
                                     mode="lines", line=dict(width=1, color=theme.SURFACE),
                                     fillcolor=colors.get(unit, theme.MUTED), legendgroup=unit,
                                     showlegend=k == 0, hovertemplate=f"{unit}: %{{y:.2f}} MW<extra>{sid}</extra>"),
                          row=r, col=c)
        lo = load[load["scenario"] == sid].sort_values("t")
        fig.add_trace(go.Scatter(x=lo["t"], y=lo["load_mw"], name="Load", mode="lines",
                                 line=dict(width=2.5, color=theme.LOAD), legendgroup="load", showlegend=k == 0,
                                 hovertemplate=f"Load: %{{y:.2f}} MW<extra>{sid}</extra>"), row=r, col=c)
        _time_axis(fig, minutes, periods, row=r, col=c, title=r == rows)
    fig.update_layout(template=theme.PLOT_TEMPLATE, height=260 * rows + 150, hovermode="closest",
                      title="Dispatch per scenario (MW)")
    fig.update_yaxes(title_text="MW", col=1)
    fig.update_annotations(font=dict(color=theme.INK_2, size=12))
    return fig


# ------------------------------------------------------------------ scenarios / fans
def fan_chart(frame: pd.DataFrame, title: str, ytitle: str, minutes: int, periods: list[int],
              value: str = "mw", scenario_colors: dict[str, str] | None = None, height: int = 360) -> go.Figure:
    """Scenario fan: min–max band, thin line per scenario, bold expected value."""
    fig = _base(title, ytitle, height)
    if frame.empty:
        return fig
    scenarios = list(dict.fromkeys(frame["scenario"]))
    colors = scenario_colors or theme.scenario_colors(scenarios)
    wide = frame.pivot_table(index="t", columns="scenario", values=value, aggfunc="sum").sort_index()
    if len(scenarios) > 1:
        fig.add_trace(go.Scatter(x=wide.index, y=wide.max(axis=1), mode="lines", line=dict(width=0),
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=wide.index, y=wide.min(axis=1), mode="lines", line=dict(width=0),
                                 fill="tonexty", fillcolor=theme.rgba(theme.SEQUENTIAL[3], .14),
                                 name="Scenario range", hoverinfo="skip"))
    for sid in scenarios:
        if sid in wide:
            fig.add_trace(go.Scatter(x=wide.index, y=wide[sid], name=sid, mode="lines",
                                     line=dict(width=1.6, color=colors.get(sid, theme.SEQUENTIAL[3])),
                                     hovertemplate="%{y:.2f}"))
    prob = frame.groupby("scenario")["probability"].first()
    expected = sum(wide[s] * prob.get(s, 0) for s in scenarios if s in wide)
    if len(scenarios) > 1:
        fig.add_trace(go.Scatter(x=wide.index, y=expected, name="Expected (probability-weighted)",
                                 mode="lines", line=dict(width=3.5, color=theme.EXPECTED),
                                 hovertemplate="%{y:.2f}"))
    _time_axis(fig, minutes, periods)
    return fig


def scenario_tree(layout: dict) -> go.Figure:
    """Scenario tree: nodes at their stage start hour, labelled with probability."""
    fig = _base("Scenario tree (nonanticipativity structure)", "", 380)
    pts = layout["points"]
    for parent, child in layout["edges"]:
        a, b = pts[parent], pts[child]
        fig.add_trace(go.Scatter(x=[a["x"], b["x"]], y=[a["y"], b["y"]], mode="lines",
                                 line=dict(color=theme.AXIS, width=2), hoverinfo="skip", showlegend=False))
    xs = [p["x"] for p in pts.values()]
    ys = [p["y"] for p in pts.values()]
    text = [f"{p['label']}<br>p={p['p']:.3f}" for p in pts.values()]
    hover = [f"Node {'/'.join(k)}<br>stage starts at hour {p['x']}<br>probability {p['p']:.4f}<br>"
             f"scenarios: {', '.join(p['members'])}" for k, p in pts.items()]
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers+text", text=text, textposition="top center",
                             marker=dict(size=16, color=theme.SEQUENTIAL[3], line=dict(width=2, color=theme.SURFACE)),
                             textfont=dict(color=theme.INK_2, size=11), hovertext=hover, hoverinfo="text",
                             showlegend=False))
    fig.update_layout(hovermode="closest")
    fig.update_yaxes(visible=False, range=[min(ys) - 0.6, max(ys) + 0.9])
    fig.update_xaxes(title_text="Stage start (hour)", tickvals=layout["starts"])
    return fig


# ------------------------------------------------------------------ commitment
def commitment_heatmap(commitment: pd.DataFrame, units: pd.DataFrame, minutes: int,
                       periods: list[int]) -> go.Figure:
    """Units × periods coloured by operating-state class, with start/stop markers."""
    classes = list(theme.STATE_CLASS_COLORS)
    order = [u for u in units.sort_values("index")["unit"] if u in set(commitment["unit"])]
    z, text, hover = [], [], []
    for unit in order:
        c = commitment[commitment["unit"] == unit].set_index("t").reindex(periods)
        z.append([classes.index(v) if v in classes else 0 for v in c["state_class"].fillna("Off")])
        text.append(["" if pd.isna(v) else str(int(v)) for v in c["operating_state"]])
        hover.append([f"{unit}<br>{period_label(t, minutes)}<br>{'ON' if on else 'OFF'} · state "
                      f"{lab or '—'}" for t, on, lab in zip(periods, c["on"].fillna(0), c["state_label"].fillna(""))])
    n = len(classes)
    scale = []
    for i, cls in enumerate(classes):
        scale += [[i / n, theme.STATE_CLASS_COLORS[cls]], [(i + 1) / n, theme.STATE_CLASS_COLORS[cls]]]
    fig = go.Figure(go.Heatmap(z=z, x=periods, y=order, text=text, texttemplate="%{text}",
                               textfont=dict(color=theme.INK, size=11), hovertext=hover, hoverinfo="text",
                               colorscale=scale, zmin=-0.5, zmax=n - 0.5, xgap=2, ygap=2, showscale=False))
    for col, symbol, name, color in (("startup", "triangle-up", "Start-up", theme.INK),
                                     ("shutdown", "triangle-down", "Shut-down", theme.LOAD_SHED)):
        ev = commitment[commitment[col] > 0]
        if not ev.empty:
            fig.add_trace(go.Scatter(x=ev["t"], y=ev["unit"], mode="markers", name=name,
                                     marker=dict(symbol=symbol, size=13, color=color,
                                                 line=dict(width=2, color=theme.SURFACE)),
                                     hovertemplate=f"{name}<br>%{{y}}<br>period %{{x}}<extra></extra>"))
    for cls in classes:     # legend entries for the state classes
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=cls,
                                 marker=dict(symbol="square", size=12, color=theme.STATE_CLASS_COLORS[cls])))
    fig.update_layout(template=theme.PLOT_TEMPLATE, height=max(300, 46 * len(order) + 190), hovermode="closest",
                      title="Unit commitment & operating states (cell text = operating-state id)")
    fig.update_yaxes(autorange="reversed", title_text=None, showgrid=False)
    fig.update_xaxes(showgrid=False)
    _time_axis(fig, minutes, periods)
    return fig


# ------------------------------------------------------------------ storage
def soc_chart(storage: pd.DataFrame, store: str, capacity: float, min_mwh: float, minutes: int,
              periods: list[int], scenario_colors: dict[str, str]) -> go.Figure:
    """BESS state of charge (MWh) per scenario with capacity / min bands."""
    fig = _base(f"State of charge – {store} (MWh)", "Energy (MWh)", 340)
    d = storage[storage["store"] == store]
    for sid, grp in d.groupby("scenario", sort=False):
        grp = grp.sort_values("t")
        fig.add_trace(go.Scatter(x=grp["t"], y=grp["energy_mwh"], name=sid, mode="lines+markers",
                                 line=dict(width=1.8, color=scenario_colors.get(sid, theme.SEQUENTIAL[3])),
                                 marker=dict(size=6), hovertemplate="%{y:.3f} MWh"))
    if d["scenario"].nunique() > 1:
        e = (d.assign(w=d["probability"] * d["energy_mwh"]).groupby("t")["w"].sum())
        fig.add_trace(go.Scatter(x=e.index, y=e.values, name="Expected", mode="lines",
                                 line=dict(width=3.5, color=theme.EXPECTED), hovertemplate="%{y:.3f} MWh"))
    for y, label in ((capacity, "capacity"), (min_mwh, "min SOC")):
        fig.add_hline(y=y, line=dict(color=theme.MUTED, width=1), annotation_text=label,
                      annotation_font_color=theme.MUTED, annotation_position="top left")
    _time_axis(fig, minutes, [0] + periods)
    return fig


def charge_bars(storage: pd.DataFrame, store: str, scenario: str, minutes: int, periods: list[int],
                color: str) -> go.Figure:
    """Charge (negative) and discharge (positive) power of one scenario (MW)."""
    fig = _base(f"Charge / discharge – {store}, {scenario} (MW)", "Power (MW)", 300)
    d = storage[(storage["store"] == store) & (storage["t"] > 0)]
    if scenario in set(d["scenario"]):
        d = d[d["scenario"] == scenario]
    else:
        d = d.assign(charge_mw=d["probability"] * d["charge_mw"], discharge_mw=d["probability"] * d["discharge_mw"])
        d = d.groupby("t", as_index=False)[["charge_mw", "discharge_mw"]].sum()
    fig.add_trace(go.Bar(x=d["t"], y=d["discharge_mw"], name="Discharge", marker_color=color,
                         hovertemplate="%{y:.3f} MW"))
    fig.add_trace(go.Bar(x=d["t"], y=-d["charge_mw"], name="Charge", marker_color=theme.rgba(color, .5),
                         hovertemplate="%{y:.3f} MW"))
    fig.update_layout(barmode="relative", bargap=0.25)
    _time_axis(fig, minutes, periods)
    return fig


# ------------------------------------------------------------------ load shedding / reserves
def shedding_bars(load: pd.DataFrame, minutes: int, periods: list[int], colors: dict[str, str]) -> go.Figure:
    fig = _base("Load shedding per scenario (MW)", "Unserved power (MW)", 300)
    for sid, grp in load.groupby("scenario", sort=False):
        fig.add_trace(go.Bar(x=grp["t"], y=grp["shed_mw"], name=sid, marker_color=colors.get(sid, theme.LOAD_SHED),
                             hovertemplate="%{y:.3f} MW"))
    fig.update_layout(barmode="group", bargap=0.2)
    _time_axis(fig, minutes, periods)
    return fig


def reserve_chart(provided: pd.DataFrame, required: pd.DataFrame, units: pd.DataFrame, product: str,
                  direction: str, minutes: int, periods: list[int], scenario_colors: dict[str, str]) -> go.Figure:
    """Provided reserve per unit (stacked bars) against each scenario's requirement (MW)."""
    word = "upward" if direction == "up" else "downward"
    fig = _base(f"{product.capitalize()} {word} reserve: provided vs required (MW)", "Reserve (MW)", 380)
    colors = dict(zip(units["unit"], units["color"]))
    p = provided[(provided["product"] == product) & (provided["direction"] == direction)]
    for unit in _ordered_units(units, set(p["unit"])):
        d = p[p["unit"] == unit].sort_values("t")
        if d["mw"].abs().sum() > 1e-9:
            fig.add_trace(go.Bar(x=d["t"], y=d["mw"], name=unit, marker_color=colors.get(unit, theme.MUTED),
                                 hovertemplate="%{y:.3f} MW"))
    r = required[(required["product"] == product) & (required["direction"] == direction)]
    for sid, grp in r.groupby("scenario", sort=False):
        grp = grp.sort_values("t")
        fig.add_trace(go.Scatter(x=grp["t"], y=grp["required_mw"], name=f"Required · {sid}", mode="lines",
                                 line=dict(width=1.6, color=scenario_colors.get(sid, theme.SEQUENTIAL[3]), shape="hvh"),
                                 hovertemplate="%{y:.3f} MW"))
    if r["scenario"].nunique() > 1:
        e = r.assign(w=r["probability"] * r["required_mw"]).groupby("t")["w"].sum()
        fig.add_trace(go.Scatter(x=e.index, y=e.values, name="Required · expected", mode="lines",
                                 line=dict(width=3.5, color=theme.EXPECTED, shape="hvh"), hovertemplate="%{y:.3f} MW"))
    fig.update_layout(barmode="stack", bargap=0.25)
    _time_axis(fig, minutes, periods)
    return fig


def headroom_chart(headroom: pd.DataFrame, units: pd.DataFrame, column: str, title: str, minutes: int,
                   periods: list[int]) -> go.Figure:
    fig = _base(title, "MW", 320)
    colors = dict(zip(units["unit"], units["color"]))
    for unit in _ordered_units(units, set(headroom["unit"])):
        d = headroom[headroom["unit"] == unit].sort_values("t")
        fig.add_trace(go.Bar(x=d["t"], y=d[column], name=unit, marker_color=colors.get(unit, theme.MUTED),
                             hovertemplate="%{y:.3f} MW"))
    fig.update_layout(barmode="stack", bargap=0.25)
    _time_axis(fig, minutes, periods)
    return fig


# ------------------------------------------------------------------ costs
def cost_waterfall(waterfall: pd.DataFrame, total: float | None, title: str) -> go.Figure:
    """Waterfall of the expected objective (EUR)."""
    labels = [_wrap(c) for c in waterfall["component"]] + ["Total"]
    values = waterfall["eur"].tolist() + [total if total is not None else waterfall["eur"].sum()]
    measure = ["relative"] * len(waterfall) + ["total"]
    fig = go.Figure(go.Waterfall(
        x=labels, y=values, measure=measure, connector=dict(line=dict(color=theme.AXIS, width=1)),
        increasing=dict(marker=dict(color=theme.TYPE_BASE["thermal"])),
        decreasing=dict(marker=dict(color=theme.TYPE_BASE["wind"])),
        totals=dict(marker=dict(color=theme.ACCENT)),
        text=[f"{v:,.0f}" for v in values], textposition="outside", textfont=dict(color=theme.INK_2),
        hovertemplate="%{x}<br>%{y:,.2f} €<extra></extra>"))
    fig.update_layout(template=theme.PLOT_TEMPLATE, title=title, height=460, yaxis_title="Cost (€)",
                      hovermode="closest", showlegend=False)
    fig.update_xaxes(tickangle=0, tickfont=dict(size=11))
    return fig


def _wrap(text: str, width: int = 16) -> str:
    """Break a long axis label into short lines."""
    words, lines, line = text.split(), [], ""
    for word in words:
        if line and len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    lines.append(line)
    return "<br>".join(lines)


def scenario_cost_bars(costs: pd.DataFrame, expected_cost: float | None, cvar: float | None,
                       colors: dict[str, str]) -> go.Figure:
    fig = _base("Total cost per scenario (€)", "Cost (€)", 340)
    fig.add_trace(go.Bar(x=costs["scenario"], y=costs["total_eur"],
                         marker_color=[colors.get(s, theme.SEQUENTIAL[3]) for s in costs["scenario"]],
                         customdata=costs["probability"], name="Scenario cost",
                         hovertemplate="%{x}<br>%{y:,.2f} €<br>p = %{customdata:.4f}<extra></extra>"))
    if expected_cost is not None:
        fig.add_hline(y=expected_cost, line=dict(color=theme.EXPECTED, width=2),
                      annotation_text=f"expected {expected_cost:,.0f} €", annotation_font_color=theme.INK)
    if cvar is not None and len(costs) > 1:
        fig.add_hline(y=cvar, line=dict(color=theme.STATUS["serious"], width=1.5),
                      annotation_text=f"CVaR {cvar:,.0f} €", annotation_position="bottom right",
                      annotation_font_color=theme.STATUS["serious"])
    fig.update_layout(hovermode="closest", showlegend=False, bargap=0.35)
    return fig


def benchmark_bars(bench: dict) -> go.Figure:
    """WS ≤ RP ≤ EEV with VSS / EVPI annotated (EUR)."""
    labels, values = [], []
    for key, label in (("WS", "WS – wait-and-see"), ("RP", "RP – stochastic"), ("EEV", "EEV – deterministic plan")):
        if bench.get(key) is not None:
            labels.append(label)
            values.append(bench[key])
    fig = _base("Stochastic vs deterministic (expected cost, €)", "Expected cost (€)", 340)
    fig.add_trace(go.Bar(x=labels, y=values, marker_color=[theme.SEQUENTIAL[1], theme.ACCENT, theme.TYPE_BASE["thermal"]][:len(values)],
                         text=[f"{v:,.0f}" for v in values], textposition="outside",
                         hovertemplate="%{x}<br>%{y:,.2f} €<extra></extra>"))
    if values:
        fig.update_yaxes(range=[0, max(values) * 1.12])     # bars always start at zero
    fig.update_layout(hovermode="closest", showlegend=False, bargap=0.45)
    return fig


# ------------------------------------------------------------------ compare runs
def compare_lines(frames: dict[str, pd.DataFrame], title: str, ytitle: str, minutes_by_run: dict[str, int]) -> go.Figure:
    """Overlay of one series for several runs, on hours so RDAS and DS align."""
    fig = _base(title, ytitle, 360)
    palette = [theme.ACCENT, theme.TYPE_BASE["thermal"], theme.SEQUENTIAL[1], theme.TYPE_BASE["partial"]]
    for k, (name, frame) in enumerate(frames.items()):
        minutes = minutes_by_run.get(name, 60)
        x = frame["t"] * minutes / 60
        fig.add_trace(go.Scatter(x=x, y=frame["mw"], name=name, mode="lines", line=dict(width=2.5 if k == 0 else 2,
                                 color=palette[k % len(palette)], shape="vh" if minutes == 60 else "linear"),
                                 hovertemplate="%{y:.2f}"))
    fig.update_xaxes(title_text="Time from horizon start (h)")
    return fig
