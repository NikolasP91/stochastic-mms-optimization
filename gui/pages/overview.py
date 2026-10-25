"""🏠 Overview: KPI dashboard, expected dispatch vs load, slack/penalty warnings."""

from __future__ import annotations

import streamlit as st

from gui import adapter, state, theme
from gui.components import charts, kpi, tables

ss = st.session_state
data = state.work()
res = state.results()

st.title("Overview")
st.markdown(f'<div class="section-note">Case <b>{ss.case_label}</b> · mode <b>{ss.mode}</b> · '
            f'view <b>{ss.scenario_choice}</b></div>', unsafe_allow_html=True)
for note in ss.get("case_notes", []):
    st.info(note, icon="ℹ️")


def input_summary() -> None:
    """What the case contains, before any run."""
    kpi.section("Case at a glance", "Inputs of the loaded case. Press ▶ Run optimization in the sidebar to solve.")
    infos = adapter.unit_infos(data)
    gens = [u for u in infos if not u.is_storage]
    by_type = {}
    for u in gens:
        by_type[u.type] = by_type.get(u.type, 0) + 1
    config = data["stochastic"]
    n = adapter.horizon(data)
    kpi.card_row([
        {"label": "Units", "value": str(len(gens)),
         "sub": " · ".join(f"{theme.TYPE_ICON.get(k, '')} {v} {theme.TYPE_LABELS.get(k, k)}" for k, v in by_type.items())},
        {"label": "Storage (BESS)", "value": str(len(config.get("storage", []))),
         "sub": ", ".join(s["id"] for s in config.get("storage", [])) or "none"},
        {"label": "Scenarios", "value": str(len(adapter.scenario_ids(data, True))),
         "sub": "multistage tree" if "scenario_tree" in config else "two-stage (full-path recourse)"},
        {"label": "Horizon", "value": str(n), "unit": "h" if adapter.resolution_minutes(data) == 60 else "periods",
         "sub": f"{adapter.resolution_minutes(data)}-min resolution; t = 0 is the previous hour"},
        {"label": "Slack policy", "value": config["slack_policy"]["mode"],
         "sub": "regression semantics" if config["slack_policy"]["mode"] == "legacy" else "explicit caps"},
    ])
    st.space("small")
    frame = adapter.scenario_series(data)
    charts.show(charts.fan_chart(frame[frame["series"] == "Load"], "Load forecast per scenario (MW)", "Load (MW)",
                                 adapter.resolution_minutes(data), list(range(1, n + 1))), "load_fan", key="ov_fan")


if res is None:
    input_summary()
    st.stop()

if not res.ok:
    tables.error_box(f"Last run: {res.status}", res.message or res.error.get("message", ""),
                     res.error.get("traceback"))
    if res.status == "Infeasible":
        st.info("**Suggestions:** switch the slack policy to *bounded* with caps on load shedding and reserve "
                "shortfall (Parameters → Model), relax must-run / testing obligations, check initial states and "
                "timers (Inputs → Initial conditions), or lower BESS terminal SOC targets.", icon="💡")
    elif res.status == "Time limit":
        st.info("**Suggestions:** raise the time limit, or enable *Accept time-limited incumbent* "
                "(Parameters → Solver) to report the best feasible schedule.", icon="💡")
    input_summary()
    st.stop()

k = adapter.kpis(res)
h_unit = "h" if res.minutes == 60 else "min"
st.caption(f"Showing run `{res.run_dir.split('runs')[-1].strip(chr(92) + '/')}` ({res.mode}, {res.status}).")
kpi.card_row([
    {"label": "Expected total cost", "value": kpi.fmt(k.get("expected_cost")), "unit": "€", "accent": True,
     "sub": f"objective {kpi.fmt(k.get('objective'))} €"
            + (f" · CVaR {kpi.fmt(k.get('cvar'))} €" if k.get("cvar") is not None else ""),
     "help": "Probability-weighted total cost of the stochastic plan (RDAS) or the DS objective."},
    {"label": "Generation & operation", "value": kpi.fmt(k.get("cost_generation")), "unit": "€",
     "sub": "online charge, fuel, activation, BESS", "help": "Everything except start-up/shut-down, reserves, penalties."},
    {"label": "Start-up / shut-down", "value": kpi.fmt(k.get("cost_startup")), "unit": "€",
     "sub": f"{k.get('startups', 0)} start-up(s)"},
    {"label": "Reserves", "value": kpi.fmt(k.get("cost_reserves"), 1), "unit": "€",
     "sub": "capacity (+ state/transition costs in RDAS)"},
    {"label": "Penalties (slacks)", "value": kpi.fmt(k.get("cost_penalties"), 1), "unit": "€",
     "sub": "expected value of relaxation costs"},
])
st.space("small")
kpi.card_row([
    {"label": "Scenarios", "value": str(k.get("n_scenarios", 0)),
     "sub": "deterministic DS" if res.mode == "DS" else ("tree" if res.tree else "two-stage")},
    {"label": "Units committed", "value": f"{k.get('units_committed', 0)} / {k.get('units_conventional', 0)}",
     "sub": f"thermal; peak {k.get('peak_online', 0)} online at once"},
    {"label": "Load shedding (expected)", "value": kpi.fmt(k.get("load_shed_mwh"), 3), "unit": "MWh",
     "sub": f"of {kpi.fmt(k.get('energy_mwh'), 1)} MWh demand"},
    {"label": "RES share", "value": kpi.fmt(100 * k["res_share"], 1) if k.get("res_share") is not None else "—",
     "unit": "%", "sub": "wind + PV + hybrid of demand (expected)"},
    {"label": "MIP gap", "value": kpi.fmt(100 * k["mip_gap"], 3) if k.get("mip_gap") is not None else
     ("0" if res.status == "Optimal" else "—"), "unit": "%",
     "sub": "proven optimal" if res.status == "Optimal" else "incumbent, not proven"},
    {"label": "Solve time", "value": kpi.fmt(k.get("solve_seconds"), 2), "unit": "s",
     "sub": f"{kpi.fmt(k.get('rows'))} rows · {kpi.fmt(k.get('cols'))} cols · {kpi.fmt(k.get('binaries'))} bin"},
])
st.space("medium")

left, right = st.columns([3, 1.25], gap="large")
with left:
    choice = ss.scenario_choice
    view = choice if choice in set(res.dispatch["scenario"]) else adapter.EXPECTED_ID
    d = adapter.pick_scenario(res.dispatch, view, ["unit", "type", "t"])
    lo = adapter.pick_scenario(res.load, view, ["t"], "load_mw")
    if view == adapter.EXPECTED_ID:
        shed = adapter.expected(res.load, ["t"], "shed_mw")
        lo = lo.merge(shed, on="t")
    title = "Expected dispatch vs load (MW)" if view == adapter.EXPECTED_ID else f"Dispatch vs load – {view} (MW)"
    charts.show(charts.dispatch_stack(d, lo, res.units, res.minutes, title, res.periods), "dispatch", key="ov_disp")
    if view == adapter.EXPECTED_ID and res.mode == "RDAS" and len(res.scenarios) > 1:
        st.caption("Probability-weighted average of the scenario dispatches: a summary, not an operating schedule. "
                   "Commitment (Results → Common decisions) is the decision issued now.")
with right:
    kpi.section("Warnings", "Non-zero slack / penalty variables of the optimum.")
    summary = adapter.warnings_summary(res)
    if summary.empty:
        st.success("No slack variable is active: no load shedding, reserve shortfall or relaxed constraint.",
                   icon="✅")
    else:
        for _, row in summary.iterrows():
            st.warning(f"**{row['category']}** – {row['scenarios affected']} scenario(s), periods {row['periods']}; "
                       f"expected {row['expected amount']:,.3f}, penalty {row['expected penalty (€)']:,.0f} €",
                       icon="⚠️")
    validation = res.meta.get("validation", {})
    if validation:
        if validation.get("passed"):
            st.success(f"Residual audit passed ({kpi.fmt(validation.get('checked_constraints'))} checks).", icon="🧪")
        else:
            st.error("Residual audit failed – see Results → Constraint health.", icon="🧪")
    for note in res.notes:
        st.caption(f"**{note.get('code', '')}** – {note.get('message', '')}")
