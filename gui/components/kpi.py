"""KPI cards and status badges."""

from __future__ import annotations

import html
import math

import streamlit as st

STATUS_BADGE = {
    "Not run": ("gray", ":material/radio_button_unchecked:"),
    "Running": ("blue", ":material/progress_activity:"),
    "Optimal": ("green", ":material/check_circle:"),
    "Feasible": ("orange", ":material/timer:"),
    "Time limit": ("orange", ":material/timer_off:"),
    "Infeasible": ("red", ":material/block:"),
    "Input error": ("red", ":material/edit_off:"),
    "Error": ("red", ":material/error:"),
    "Cancelled": ("gray", ":material/cancel:"),
}
STATUS_HELP = {
    "Not run": "No optimization has been run for this case in this session.",
    "Running": "The solver is working in a background process; the page stays usable.",
    "Optimal": "Proven optimal (relative MIP gap 0) and the solution passed the residual audit.",
    "Feasible": "Time limit reached; the best feasible incumbent was accepted. Optimality is not proven.",
    "Time limit": "Time limit reached without an accepted solution. Increase the limit or accept incumbents.",
    "Infeasible": "No schedule satisfies all hard constraints. See the suggestions on the Results page.",
    "Input error": "The input failed validation; nothing was solved.",
    "Error": "The run failed. Open 'Details' for the full message.",
    "Cancelled": "The run was stopped by the user.",
}


def status_badge(status: str) -> None:
    color, icon = STATUS_BADGE.get(status, ("gray", ":material/help:"))
    st.badge(status, icon=icon, color=color, help=STATUS_HELP.get(status))


def fmt(value, digits: int = 0, unit: str = "") -> str:
    """Thousands-separated number or an em dash for missing values."""
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return "—"
    if isinstance(value, (int, float)):
        text = f"{value:,.{digits}f}"
    else:
        text = str(value)
    return f"{text} {unit}".strip()


def card(label: str, value: str, unit: str = "", sub: str = "", accent: bool = False, help: str = "") -> None:
    """One KPI tile (label, big value with unit, optional sub-line)."""
    title = f' title="{html.escape(help)}"' if help else ""
    st.markdown(
        f'<div class="kpi-card{" kpi-accent" if accent else ""}"{title}>'
        f'<div class="kpi-label">{html.escape(label)}</div>'
        f'<div class="kpi-value">{html.escape(value)}<span class="kpi-unit">{html.escape(unit)}</span></div>'
        f'<div class="kpi-sub">{html.escape(sub)}</div></div>',
        unsafe_allow_html=True)


def card_row(cards: list[dict], columns: int | None = None) -> None:
    """A row of KPI tiles; each dict holds the ``card`` arguments."""
    cols = st.columns(columns or len(cards), gap="small")
    for col, spec in zip(cols, cards):
        with col:
            card(**spec)


def section(title: str, note: str = "", tag: str = "") -> None:
    """Section header with an optional 'common' / 'scenario' tag and a note line."""
    tags = {"common": '<span class="common-tag">common to all scenarios</span>',
            "scenario": '<span class="scen-tag">scenario-dependent</span>'}
    st.markdown(f"#### {html.escape(title)} {tags.get(tag, '')}", unsafe_allow_html=True)
    if note:
        st.markdown(f'<div class="section-note">{note}</div>', unsafe_allow_html=True)
