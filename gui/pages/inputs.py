"""📥 Inputs: units, forecasts, scenarios, initial conditions (editable, validated)."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from gui import adapter, state, theme
from gui.components import charts, kpi, tables

ss = st.session_state
data = state.work()
ver = ss.ver
n = adapter.horizon(data)
minutes = adapter.resolution_minutes(data)
periods = list(range(1, n + 1))
cc = st.column_config

st.title("Inputs")
st.markdown('<div class="section-note">Edit values in the tables; changes stay in memory and are used by the next '
            'run. Hover a column header for its meaning and unit.</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------ action bar
a, b, c, d = st.columns([1, 1, 2.2, 1.2], vertical_alignment="bottom")
with a:
    if st.button("↺ Reset to file", width="stretch", help="Discard all edits (inputs and parameters)."):
        state.reset_work()
        st.toast("Edits discarded.", icon="↺")
        st.rerun()
with b:
    if st.button("✔ Validate inputs", width="stretch", type="primary",
                 help="Run the GUI checks plus the engine's validators for the current mode."):
        with st.spinner("Validating…"):
            ss.issues = adapter.validate_case(data, ss.mode, ss.scenario_choice, ss.solver_opts["ds_hours"])
with c:
    name = st.text_input("New case name", placeholder="e.g. island_winter_peak",
                         help="Saved as cases/<name>.json, including parameter edits.")
with d:
    if st.button("💾 Save as new case", width="stretch", disabled=not name):
        try:
            path = adapter.save_case(data, name)
            st.toast(f"Saved {adapter.case_label(path)}", icon="💾")
        except FileExistsError as exc:
            st.error(str(exc))
        except (OSError, ValueError) as exc:
            tables.error_box("Could not save the case", str(exc))

if ss.issues is not None:
    with st.container(border=True):
        tables.issues_list(ss.issues)

changes = adapter.diff(state.base(), data)
with st.expander(f"Changes vs. file ({len(changes)})", expanded=False):
    if changes.empty:
        st.caption("No edits yet.")
    else:
        st.dataframe(changes.astype(str), hide_index=True)
        st.download_button("⬇ Download edited case (JSON)", json.dumps(data, indent=2, ensure_ascii=False),
                           file_name="edited_case.json", mime="application/json")

units_tab, fc_tab, sc_tab, ic_tab = st.tabs(["🏭 Units", "📈 Forecasts", "🎲 Scenarios", "⏱️ Initial conditions"])

# ------------------------------------------------------------------ units
with units_tab:
    kpi.section("Generating units", "Scalar technical and economic data per unit.")
    source = state.editor_source("units", lambda: adapter.units_frame(data))
    edited = st.data_editor(
        source, key=f"ed_units_{ver}", hide_index=True, num_rows="fixed",
        disabled=["gen_id", "Unit", "Type", "Comment", "Var. cost curve"],
        column_config={
            "gen_id": cc.NumberColumn("gen_id", help="Unit ID = zero-based list index (required by the kernel)."),
            "Type": cc.TextColumn(help="Derived from the comment prefix (Therm…/PV…/other RES) and BESS links."),
            "Comment": cc.TextColumn(help="Original description; its prefix defines the legacy unit category.",
                                     width="medium"),
            "Max power (MW)": cc.NumberColumn(min_value=0.0, format="%.3f", help="Installed maximum output (MW)."),
            "Min power (MW)": cc.NumberColumn(min_value=0.0, format="%.3f", help="Technical minimum (MW)."),
            "Ramp up (kW/min)": cc.NumberColumn(min_value=0.0, help="Maximum upward ramp rate (kW/min)."),
            "Ramp down (kW/min)": cc.NumberColumn(min_value=0.0, help="Maximum downward ramp rate (kW/min)."),
            "Start-up cost (€)": cc.NumberColumn(min_value=0.0, help="Cost per start-up (€)."),
            "Shut-down cost (€)": cc.NumberColumn(min_value=0.0, help="Cost per shut-down (€)."),
            "Accepts set-point": cc.CheckboxColumn(help="RES unit accepts dispatch set-points (Accepts_SP)."),
            "AGC connected": cc.CheckboxColumn(help="Unit is connected to AGC (agc_configuration.isConnected)."),
            "Var. cost curve": cc.TextColumn(help="Piecewise-linear variable cost: breakpoint MW → €/MWh "
                                                  "(or €/MW·min, see cost_curve_time_unit).", width="medium"),
        })
    adapter.apply_units_frame(data, edited)
    bad = edited[edited["Min power (MW)"] > edited["Max power (MW)"]]
    for _, row in bad.iterrows():
        st.error(f"{row['Unit']}: min power exceeds max power.", icon="🛑")

    st.space("small")
    kpi.section("Unit details", "Hourly series, operating states and allowed state transitions of one unit.")
    infos = [u for u in adapter.unit_infos(data) if not u.is_storage]
    pick = st.selectbox("Unit", [u.label for u in infos], key="unit_detail",
                        help="Choose the unit whose detailed data you want to see or edit.")
    idx = next(u.index for u in infos if u.label == pick)
    s1, s2 = st.columns([1.15, 1], gap="large")
    with s1:
        st.markdown("**Hourly series**")
        src = state.editor_source(f"series_{idx}", lambda: adapter.unit_series_frame(data, idx))
        series = st.data_editor(
            src, key=f"ed_series_{idx}_{ver}", hide_index=True, disabled=["t", "Period"], height=320,
            column_config={
                "Availability (MW)": cc.NumberColumn(min_value=0.0, format="%.3f",
                                                     help="Available capacity per period (MW) ≤ max power."),
                "Production forecast (MW)": cc.NumberColumn(min_value=0.0, format="%.3f",
                                                            help="Nominal RES forecast (scenarios override it)."),
                "Must-run (0/1)": cc.NumberColumn(min_value=0, max_value=1, step=1,
                                                  help="1 = the unit must be online in this period."),
                "Testing mode (0/1)": cc.NumberColumn(min_value=0, max_value=1, step=1,
                                                      help="1 = unit in testing mode with a fixed output."),
                "Testing power (MW)": cc.NumberColumn(min_value=0.0, help="Output required in testing mode (MW)."),
            })
        adapter.apply_unit_series(data, idx, series)
    with s2:
        st.markdown("**Operating states**")
        src = state.editor_source(f"states_{idx}", lambda: adapter.operating_states_frame(data, idx))
        states = st.data_editor(
            src, key=f"ed_states_{idx}_{ver}", hide_index=True,
            disabled=["id", "State", "Shutdown", "Operational", "Transient", "Initial"],
            column_config={
                "Min power (MW)": cc.NumberColumn(min_value=0.0, help="Lower power bound inside this state (MW)."),
                "Max power (MW)": cc.NumberColumn(min_value=0.0, help="Upper power bound inside this state (MW)."),
                "Enabled cost (€/period)": cc.NumberColumn(min_value=0.0,
                                                           help="Cost per period spent in this state (legacy: "
                                                                "× Time_granularity unless cost_policy per_hour)."),
                "Initial": cc.CheckboxColumn(help="Initial state (change it under Initial conditions)."),
            })
        adapter.apply_operating_states(data, idx, states)
        st.markdown("**Allowed transitions** (read-only)")
        st.dataframe(adapter.transitions_frame(data, idx), hide_index=True, height=200)

    stores = data["stochastic"].get("storage", [])
    if stores:
        st.space("small")
        kpi.section("Battery storage (BESS)", "Physical data; economics are on the Parameters page.")
        src = state.editor_source("storage", lambda: adapter.storage_frame(data))
        edited_st = st.data_editor(
            src, key=f"ed_storage_{ver}", hide_index=True, disabled=["id", "Linked RES unit", "Initial SOC (%)"],
            column_config={
                "Grid charging": cc.CheckboxColumn(help="If off, the BESS may charge only from its linked RES unit."),
                "Capacity (MWh)": cc.NumberColumn(min_value=0.0, help="Usable energy capacity (MWh)."),
                "Min SOC (MWh)": cc.NumberColumn(min_value=0.0, help="Operational minimum energy (MWh)."),
                "Initial SOC (MWh)": cc.NumberColumn(min_value=0.0, help="Measured energy at t = 0 (MWh)."),
                "Terminal min SOC (MWh)": cc.NumberColumn(min_value=0.0, help="Required energy at horizon end."),
                "Charge max (MW)": cc.NumberColumn(min_value=0.0, help="Maximum charging power (MW)."),
                "Discharge max (MW)": cc.NumberColumn(min_value=0.0, help="Maximum discharging power (MW)."),
                "Charge efficiency (-)": cc.NumberColumn(min_value=0.01, max_value=1.0, format="%.3f",
                                                         help="η_c in (0, 1]."),
                "Discharge efficiency (-)": cc.NumberColumn(min_value=0.01, max_value=1.0, format="%.3f",
                                                            help="η_d in (0, 1]."),
                "Self-discharge (1/h)": cc.NumberColumn(min_value=0.0, max_value=0.99, format="%.4f",
                                                        help="Fraction of energy lost per hour (optional)."),
                "POI export limit (MW)": cc.NumberColumn(min_value=0.0,
                                                         help="Hybrid point-of-interconnection limit (optional)."),
                "Initial SOC (%)": cc.NumberColumn(format="%.1f %%", help="Initial SOC / capacity."),
            })
        adapter.apply_storage_frame(data, edited_st)

# ------------------------------------------------------------------ forecasts
with fc_tab:
    frame = adapter.scenario_series(data)
    colors = theme.scenario_colors(adapter.scenario_ids(data))
    kpi.section("Load and RES forecasts", "One thin line per scenario, the scenario range as a band and the "
                "probability-weighted expected value in bold.", tag="scenario")
    charts.show(charts.fan_chart(frame[frame["series"] == "Load"], "Load (MW)", "Load (MW)", minutes, periods,
                                 scenario_colors=colors), "load_fan", key="fc_load")
    res_series = [s for s in frame["series"].unique() if s != "Load"]
    cols = st.columns(2)
    for k, name in enumerate(res_series):
        with cols[k % 2]:
            charts.show(charts.fan_chart(frame[frame["series"] == name], f"{name} – available RES (MW)", "MW",
                                         minutes, periods, scenario_colors=colors, height=320),
                        f"res_fan_{k}", key=f"fc_res_{k}")
    st.space("small")
    kpi.section("Edit one scenario's forecasts", "Values per decision period (MW).")
    ids = adapter.scenario_ids(data)
    sid = st.selectbox("Scenario to edit", ids, key="fc_edit_sid")
    src = state.editor_source(f"scen_{sid}", lambda: adapter.scenario_editor_frame(data, sid))
    edited = st.data_editor(src, key=f"ed_scen_{sid}_{ver}", hide_index=True, disabled=["t", "Period"],
                            column_config={col: cc.NumberColumn(min_value=0.0, format="%.3f",
                                                                help="Forecast power in this period (MW).")
                                           for col in src.columns if col.endswith("(MW)")})
    adapter.apply_scenario_editor(data, sid, edited)
    if "scenario_tree" in data["stochastic"]:
        st.caption("With a scenario tree, scenarios sharing a node must keep identical data in that node's hours; "
                   "the validator reports any mismatch.")

# ------------------------------------------------------------------ scenarios
with sc_tab:
    kpi.section("Scenarios and probabilities", "Probabilities must sum to 1; the engine never rescales them.")
    src = state.editor_source("scenarios", lambda: adapter.scenarios_frame(data))
    edited = st.data_editor(
        src, key=f"ed_scen_tbl_{ver}", hide_index=True,
        disabled=["id", "Tree path", "Energy (MWh)", "Peak load (MW)", "RES energy (MWh)", "Periods"],
        column_config={"Probability": cc.NumberColumn(min_value=0.0, max_value=1.0, format="%.6f",
                                                      help="Scenario probability π_s (sum = 1)."),
                       "Energy (MWh)": cc.NumberColumn(help="Total load energy of the scenario (MWh)."),
                       "RES energy (MWh)": cc.NumberColumn(help="Total available RES energy (MWh).")})
    adapter.apply_probabilities(data, edited)
    total = float(edited["Probability"].sum())
    m1, m2, m3 = st.columns([1, 1, 2], vertical_alignment="center")
    with m1:
        st.metric("Σ probabilities", f"{total:.6f}", border=True,
                  delta="OK" if abs(total - 1) <= 1e-9 else f"{total - 1:+.6f}",
                  delta_color="normal" if abs(total - 1) <= 1e-9 else "inverse", delta_arrow="off")
    with m2:
        if st.button("Normalize to 1", disabled=abs(total - 1) <= 1e-9 or total <= 0,
                     help="Explicitly rescale all probabilities so they sum to 1."):
            adapter.normalize_probabilities(data)
            state.bump()
            st.rerun()
    layout = adapter.tree_layout(data) if abs(total - 1) <= 1e-6 else None
    if layout:
        charts.show(charts.scenario_tree(layout), "scenario_tree", key="sc_tree")
    elif "scenario_tree" not in data["stochastic"]:
        st.caption("Two-stage structure: commitment and reserves are common; each scenario's recourse sees its "
                   "full path. Add a tree below for multistage nonanticipativity.")
    with st.expander("🎲 Generate synthetic scenarios (replaces the current set)"):
        st.caption("Seeded AR(1) paths around the nominal forecast (`Load_forecast`, `Production_Forecast`), "
                   "using the engine's demonstration generator. Not a calibrated forecast model.")
        g1, g2, g3 = st.columns(3)
        count = g1.number_input("Number of scenarios", 1, 50, 3, help="Equally likely Monte-Carlo paths.")
        seed = g2.number_input("Random seed", 0, 10_000, 42, help="Same seed → same scenarios.")
        tree = g3.toggle("Multistage tree", help="Build a scenario tree instead of independent paths.")
        stages, branching = None, None
        if tree:
            t1, t2 = st.columns(2)
            stages = t1.text_input("Stage start hours", "1, " + str(max(2, n // 2)),
                                   help="Comma-separated, starting at 1, strictly increasing, ≤ horizon.")
            branching = t2.text_input("Branching per stage", "1, 3",
                                      help="Children per node at each stage; the first must be 1 (one root).")
        confirm = st.checkbox("I understand the current scenarios will be replaced")
        if st.button("Generate", disabled=not confirm, type="primary"):
            try:
                if tree:
                    starts = [int(x) for x in stages.split(",") if x.strip()]
                    branch = [int(x) for x in branching.split(",") if x.strip()]
                    adapter.generate_scenarios(data, int(count), int(seed), starts, branch)
                else:
                    adapter.generate_scenarios(data, int(count), int(seed))
                state.bump()
                st.toast("Scenarios generated.", icon="🎲")
                st.rerun()
            except (ValueError, KeyError) as exc:
                tables.error_box("Could not generate scenarios", str(exc))

# ------------------------------------------------------------------ initial conditions
with ic_tab:
    kpi.section("Initial conditions (t = 0, the hour before the horizon)",
                "Operating state, power and remaining minimum up/down times at the start of the horizon.")
    src = state.editor_source("init", lambda: adapter.initial_conditions_frame(data))
    all_states = sorted({o for i in range(len(data["Generating_Units"])) for o in adapter.state_options(data, i)},
                        key=lambda s: (int(s.split(" · ")[0]), s))
    edited = st.data_editor(
        src, key=f"ed_init_{ver}", hide_index=True, disabled=["gen_id", "Unit", "On (state)"],
        column_config={
            "Initial operating state": cc.SelectboxColumn(
                options=all_states, required=True, width="medium",
                help="State the unit is in at t = 0; sets isEnabled and the binary on/off state."),
            "On (state)": cc.CheckboxColumn(help="Derived: on unless the initial state is a shutdown state."),
            "Current power (MW)": cc.NumberColumn(min_value=0.0, format="%.3f",
                                                  help="Measured output at t = 0 (MW); must lie in the state's band."),
            "Min ON time left (min)": cc.NumberColumn(min_value=0.0,
                                                      help="Remaining minimum up time before a shut-down (min)."),
            "Min OFF time left (min)": cc.NumberColumn(min_value=0.0,
                                                       help="Remaining minimum down time before a start-up (min)."),
            "Max-ON elapsed (h)": cc.NumberColumn(min_value=0, step=1,
                                                  help="Hours already online for the maximum-ON rule (if defined)."),
        })
    invalid = []
    for _, row in edited.iterrows():
        options = adapter.state_options(data, int(row["gen_id"]))
        if row["Initial operating state"] not in options:
            invalid.append(f"{row['Unit']}: state '{row['Initial operating state']}' does not exist for this unit "
                           f"(choose one of {', '.join(options)}).")
    for message in invalid:
        st.error(message, icon="🛑")
    if not invalid:
        adapter.apply_initial_conditions(data, edited)
    if data["stochastic"].get("storage"):
        st.markdown("**BESS state of charge at t = 0**")
        frame = adapter.storage_frame(data)[["id", "Initial SOC (MWh)", "Capacity (MWh)", "Min SOC (MWh)",
                                             "Initial SOC (%)"]]
        st.dataframe(frame, hide_index=True)
        st.caption("Edit the initial SOC in Units → Battery storage.")
