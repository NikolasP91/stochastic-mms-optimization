"""⚙️ Parameters: solver, model, penalties, reserves, constraint toggles, storage economics."""

from __future__ import annotations

import json
import math

import pandas as pd
import streamlit as st

from gui import adapter, state
from gui.components import kpi, tables

ss = st.session_state
data = state.work()
base = state.base()
ver = ss.ver
opts = ss.solver_opts
cc = st.column_config

st.title("Parameters")
st.markdown('<div class="section-note">Defaults are the values in the case file; the engine reads every value '
            'shown here. Hover the ⓘ icons for meaning, unit and allowed range.</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ binding helpers
def _clean(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def num(path: str, label: str, help: str, lo: float | None = 0.0, hi: float | None = None,
        step: float | None = None, fmt: str | None = None, default: float = 0.0) -> None:
    """Number input bound to a dotted path of the working case."""
    current = adapter.get_path(data, path, default)
    file_value = adapter.get_path(base, path)
    value = st.number_input(
        label, min_value=lo, max_value=hi, value=float(current), step=step, format=fmt,
        key=f"p_{path}_{ver}", help=f"{help}  \nFile value: {file_value if file_value is not None else '—'}.")
    adapter.set_path(data, path, _clean(value))


def optional_num(path: str, label: str, help: str, default: float, lo: float | None = 0.0,
                 hi: float | None = None, step: float | None = None, fmt: str | None = None) -> None:
    """Optional field: a toggle decides whether the key is present at all."""
    present = adapter.get_path(data, path) is not None
    use = st.toggle(f"Set {label.split(' (')[0].lower()}", value=present, key=f"use_{path}_{ver}",
                    help="Off: the field is omitted and the engine's default behaviour applies.")
    if use:
        num(path, label, help, lo, hi, step, fmt, default=adapter.get_path(data, path, default))
    else:
        adapter.set_path(data, path, None)


# ------------------------------------------------------------------ top actions
a, b, _ = st.columns([1.2, 1.2, 3])
with a:
    if st.button("↺ Restore defaults", width="stretch",
                 help="Restore every parameter on this page to the case-file value and the solver defaults."):
        adapter.apply_parameters(data, adapter.parameters_snapshot(base))
        ss.solver_opts = dict(state.DEFAULT_SOLVER)
        state.bump()
        st.toast("Parameters restored to the case-file values.", icon="↺")
        st.rerun()
with b:
    payload = {"solver": ss.solver_opts, "parameters": adapter.parameters_snapshot(data)}
    st.download_button("⬇ Download config (JSON)", json.dumps(payload, indent=2, ensure_ascii=False),
                       file_name="rdas_parameters.json", mime="application/json", width="stretch")

tabs = st.tabs(["🧮 Solver", "🧠 Model & risk", "💶 Penalties", "🛡️ Reserves", "🔒 Constraints",
                "🔋 Storage economics", "💾 Save / load"])

# ------------------------------------------------------------------ solver
with tabs[0]:
    kpi.section("Solver", "Settings passed to the engine's solve() call.")
    c1, c2, c3 = st.columns(3)
    with c1:
        choice = st.selectbox("Solver", ["highs", "cbc", "gurobi (not supported)", "cplex (not supported)"],
                              index=["highs", "cbc"].index(opts["solver"]), key=f"solver_{ver}",
                              help="MILP solver. The engine supports HiGHS (default) and CBC; Gurobi/CPLEX "
                                   "are not wired into mms.stochastic.model.solve.")
        if choice in ("highs", "cbc"):
            opts["solver"] = choice
        else:
            st.warning("Not supported by the engine; the run keeps using "
                       f"**{opts['solver']}**.", icon="⚠️")
    with c2:
        opts["time_limit"] = st.number_input("Time limit (s)", 0.0, 86_400.0, float(opts["time_limit"]), 10.0,
                                             key=f"tl_{ver}", help="0 = no limit. Wall-clock limit per MILP solve (s).")
    with c3:
        opts["accept_incumbent"] = st.toggle(
            "Accept time-limited incumbent", opts["accept_incumbent"], key=f"inc_{ver}",
            help="Report a feasible but not proven optimal solution as status 'Feasible' when the time limit "
                 "stops the search. Not allowed with the VSS/EVPI comparison.")
    c4, c5, c6 = st.columns(3)
    with c4:
        opts["compare"] = st.toggle(
            "Compute VSS / EVPI (RDAS)", opts["compare"], key=f"cmp_{ver}",
            disabled=ss.mode != "RDAS", help="Also solve the expected-value (EV/EEV) and wait-and-see (WS) "
                                              "problems: RP, EEV, WS, VSS = EEV − RP, EVPI = RP − WS. "
                                              "Several extra solves; risk-neutral.")
        if opts["compare"] and opts["accept_incumbent"]:
            st.warning("VSS/EVPI need proven optima: the incumbent option is ignored in comparison runs.")
    with c5:
        st.number_input("Relative MIP gap", value=0.0, disabled=True, key="gap_ro",
                        help="Fixed at 0 by the engine (mms.stochastic.model.solve) so that 'Optimal' means proven "
                             "optimal and VSS/EVPI are exact. Not adjustable without changing the model code.")
    with c6:
        st.number_input("Threads", value=1, disabled=True, key="thr_ro",
                        help="Fixed at 1 by the engine for reproducible HiGHS runs (process-wide scheduler).")
    st.space("small")
    kpi.section("Horizon and resolution")
    n = adapter.horizon(data)
    h1, h2 = st.columns(2)
    with h1:
        st.metric("RDAS horizon", f"{n} × 60 min", help="Decision periods 1..H; t = 0 is the previous hour "
                                                       "(hour 24 of the previous day for a 24-h case). "
                                                       "Set by the length of Load_forecast.", border=True)
    with h2:
        opts["ds_hours"] = int(st.slider(
            "DS horizon (hours from the start)", 1, n, min(int(opts["ds_hours"]), n), key=f"dsh_{ver}",
            help="DS mode solves the first N hours at 15-min resolution (4 h = 16 × 15 min)."))
        st.caption(f"DS: {opts['ds_hours'] * 4} intervals × 15 min")
    auto = st.toggle("Automatic Big-M", adapter.get_path(data, "optimization_parameters.big_m") == "auto",
                     key=f"bigm_auto_{ver}", help="On: big_m = 'auto' derives tight constants per constraint "
                                                  "(recommended). Off: one fixed constant for all constraints.")
    if auto:
        adapter.set_path(data, "optimization_parameters.big_m", "auto")
    else:
        if not isinstance(adapter.get_path(data, "optimization_parameters.big_m"), (int, float)):
            adapter.set_path(data, "optimization_parameters.big_m", 1000)
        num("optimization_parameters.big_m", "Big-M (fixed value)",
            "Constant used to relax indicator-type constraints; too small cuts feasible schedules, too large "
            "weakens the LP relaxation.", lo=1.0)

# ------------------------------------------------------------------ model & risk
with tabs[1]:
    config = data["stochastic"]
    kpi.section("Slack policy", "How constraint relaxations are allowed in the stochastic model.")
    mode = st.radio("Mode", ["legacy", "bounded"], index=["legacy", "bounded"].index(config["slack_policy"]["mode"]),
                    horizontal=True, key=f"slack_mode_{ver}",
                    help="legacy: original slack domains (regression semantics). bounded: every slack is 0 unless "
                         "a cap is given below, RES output ≤ scenario resource.")
    config["slack_policy"]["mode"] = mode
    if mode == "bounded":
        caps = config["slack_policy"].get("caps", {})
        src = state.editor_source("caps", lambda: pd.DataFrame(
            [{"Slack prefix": k, "Cap": v} for k, v in caps.items()], columns=["Slack prefix", "Cap"]))
        edited = st.data_editor(src, key=f"ed_caps_{ver}", num_rows="dynamic", hide_index=True, column_config={
            "Slack prefix": cc.SelectboxColumn(options=sorted(set(caps) | {
                "s_load_minus_", "s_load_plus_", "s_primary_APR_", "s_secondary_APR_", "s_tertiary_APR_",
                "s_power_plus_", "s_power_minus_", "ramp_relax_", "s_must_run_", "s_forbidden_zones_"}),
                help="Slack variable family (name prefix)."),
            "Cap": cc.NumberColumn(min_value=0.0, help="Upper bound of each slack of this family (MW).")})
        new_caps = {r["Slack prefix"]: float(r["Cap"]) for _, r in edited.iterrows()
                    if isinstance(r["Slack prefix"], str) and r["Cap"] is not None and not math.isnan(r["Cap"])}
        if new_caps:
            config["slack_policy"]["caps"] = {k: _clean(v) for k, v in new_caps.items()}
        else:
            config["slack_policy"].pop("caps", None)
    else:
        config["slack_policy"].pop("caps", None)
    st.space("small")
    kpi.section("Risk (CVaR)", "Objective = E[cost] + weight · CVaR_α[cost].")
    r1, r2 = st.columns(2)
    with r1:
        num("stochastic.risk.alpha", "CVaR confidence α (-)", "Tail level in (0, 1); 0.95 averages the worst 5 %.",
            lo=0.01, hi=0.999, step=0.01, fmt="%.3f", default=0.95)
    with r2:
        num("stochastic.risk.weight", "CVaR weight λ (-)", "0 = risk-neutral. Larger values penalise bad scenarios.",
            lo=0.0, step=0.1, fmt="%.3f", default=0.0)
    st.space("small")
    kpi.section("Cost policy", "Optional explicit hourly economics instead of the legacy minute-scaled terms.")
    p1, p2, p3 = st.columns(3)
    with p1:
        scaled = st.selectbox("Time-scaled costs", ["(not set) legacy", "legacy", "per_hour"],
                              index=["(not set) legacy", "legacy", "per_hour"].index(
                                  config.get("cost_policy", {}).get("legacy_time_scaled_costs", "(not set) legacy")),
                              key=f"cp_scaled_{ver}",
                              help="legacy: reserve prices, state costs, online charge and RES weight are multiplied "
                                   "by Time_granularity (60). per_hour: hourly €/MW·h values.")
        adapter.set_path(data, "stochastic.cost_policy.legacy_time_scaled_costs",
                         None if scaled.startswith("(not set)") else scaled)
    with p2:
        optional_num("stochastic.cost_policy.thermal_online_charge_eur_per_h", "Thermal online charge (€/h)",
                     "Charge per online thermal unit and hour (legacy default 100 × 60 = 6000).", 100.0)
    with p3:
        optional_num("stochastic.cost_policy.renewable_curtailment_eur_per_mwh", "RES curtailment weight (€/MWh)",
                     "Penalty per MWh of curtailed RES (requires the set-point algorithm to be off).", 1000.0)
    if not config.get("cost_policy"):
        config.pop("cost_policy", None)

# ------------------------------------------------------------------ penalties
PENALTY_HELP = {
    "x_load": "Load shedding / excess generation (€/MW per period)",
    "x_primary_APR_up": "Primary upward reserve shortfall", "x_primary_APR_down": "Primary downward reserve shortfall",
    "x_secondary_APR_up": "Secondary upward reserve shortfall",
    "x_secondary_APR_down": "Secondary downward reserve shortfall",
    "x_tertiary_APR_up": "Tertiary upward reserve shortfall", "x_tertiary_APR_down": "Tertiary downward reserve shortfall",
    "x_forbidden_zones": "Operation inside a forbidden zone", "x_ramp": "Ramp-rate relaxation",
    "x_must_run": "Must-run violation", "x_Grid_Capacity": "Grid capacity violation",
    "x_testing_mode": "Testing-mode deviation", "x_RES_PV_power_plus": "RES/PV above set-point/forecast",
    "x_RES_PV_power_minus": "RES/PV below set-point/forecast", "x_OOS_more_than": "Out-of-service (more than)",
    "x_OOS_less_than": "Out-of-service (less than)",
}
with tabs[2]:
    kpi.section("Penalty costs", "Objective weights of the slack variables (€ per MW per period unless stated). "
                "Keep a clear hierarchy: load shedding ≫ reserve shortfall ≫ timers.")
    rows = [{"Parameter": k, "Meaning": PENALTY_HELP.get(k, "State-timer / transition relaxation"
                                                         if "transition" in k or "state" in k else ""),
             "Value (€)": v, "File value (€)": base["Cost_parameters"].get(k)}
            for k, v in data["Cost_parameters"].items()]
    src = state.editor_source("penalties", lambda: pd.DataFrame(rows))
    edited = st.data_editor(src, key=f"ed_pen_{ver}", hide_index=True, disabled=["Parameter", "Meaning",
                                                                                 "File value (€)"],
                            column_config={"Value (€)": cc.NumberColumn(min_value=0.0, format="%.0f",
                                                                        help="Penalty weight (€)."),
                                           "Meaning": cc.TextColumn(width="large")})
    for _, r in edited.iterrows():
        if r["Value (€)"] is not None and not math.isnan(float(r["Value (€)"])):
            data["Cost_parameters"][r["Parameter"]] = _clean(float(r["Value (€)"]))
    if data["Cost_parameters"].get("x_load", 0) < max(data["Cost_parameters"].get(f"x_{p}_APR_up", 0)
                                                      for p in adapter.PRODUCTS):
        st.warning("Load shedding is cheaper than a reserve shortfall: the optimizer may shed load to keep reserves.",
                   icon="⚠️")

# ------------------------------------------------------------------ reserves
METHODS = ["% total generation", "% generation excl. PV", "% RES output", "% RES excl. PV",
           "% largest online unit (N-1)", "% two largest units (N-2)"]


def _flat(coef):
    return [coef[0][0], coef[0][1], coef[1][0], coef[1][1], coef[2], coef[3]]


def _nest(values):
    return [[values[0], values[1]], [values[2], values[3]], values[4], values[5]]


with tabs[3]:
    flags = data["constraints"]
    kpi.section("Reserve requirements", "Requirement = max over enabled methods of (coefficient % × metric). "
                "Products: primary (FCR), secondary (aFRR), tertiary (mFRR).")
    t1, t2, t3 = st.columns(3)
    for col, product in zip((t1, t2, t3), adapter.PRODUCTS):
        with col:
            key = f"{product}_active_power_reserves_constraint"
            flags[key] = st.toggle(f"{product.capitalize()} reserves", bool(flags.get(key)), key=f"f_{key}_{ver}",
                                   help=f"Enable the {product} reserve requirement and provision constraints. "
                                        "Tertiary needs secondary; secondary needs primary.")
    rows = []
    for product in adapter.PRODUCTS:
        for word in ("upwards", "downwards"):
            coef = data["Other_coefficients"].get(f"{product}_{word}")
            if coef:
                rows.append({"Product": product, "Direction": word, **dict(zip(METHODS, _flat(coef)))})
    src = state.editor_source("aprr", lambda: pd.DataFrame(rows))
    edited = st.data_editor(src, key=f"ed_aprr_{ver}", hide_index=True, disabled=["Product", "Direction"],
                            column_config={m: cc.NumberColumn(min_value=0.0, format="%.3f",
                                                              help=f"Coefficient in percent: requirement ≥ value/100 × "
                                                                   f"{m.split('% ')[1]}.") for m in METHODS})
    for _, r in edited.iterrows():
        data["Other_coefficients"][f"{r['Product']}_{r['Direction']}"] = _nest([_clean(float(r[m])) for m in METHODS])
    st.markdown("**Active requirement methods** (apply to all products)")
    calc = flags.setdefault("APRR_calculations", {})
    m_up, m_down = st.columns(2)
    for col, word in ((m_up, "upwards"), (m_down, "downwards")):
        with col:
            key = f"calculation-method_{word}"
            weights = _flat(calc.get(key, [[1, 1], [0, 1], 0, 0]))
            new = []
            for k, m in enumerate(METHODS):
                on = st.checkbox(f"{word.capitalize()}: {m}", bool(weights[k]), key=f"m_{word}_{k}_{ver}",
                                 help="Include this metric in the requirement (N-1 / N-2 = loss of the largest one "
                                      "or two online units).")
                new.append(int(on) if weights[k] in (0, 1) or not on else weights[k])
            calc[key] = _nest(new)
    st.space("small")
    kpi.section("Stochastic reserve linkage", "Reserve capacity is first-stage; activation is scenario-dependent.")
    config = data["stochastic"]
    link = st.toggle("Link reserves to scenario dispatch (reserve_link)", bool(config.get("reserve_link")),
                     key=f"rlink_{ver}", help="Scenario dispatch = common reference ± activated reserve. "
                                              "Requires at least one enabled product.")
    config["reserve_link"] = link
    if link:
        modes = list(adapter.sdata.RESERVE_LINK_MODES)
        config["reserve_link_mode"] = st.selectbox(
            "Linkage mode", modes, index=modes.index(config.get("reserve_link_mode", modes[0])),
            key=f"rlmode_{ver}", help="post_balancing_headroom: room for r after balancing. deploy_from_procured: "
                                      "balancing consumes procured reserve (remaining r − e).")
        products = config.setdefault("reserve_products", {})
        prow = [{"Product": p, "Response time (min)": products.get(p, {}).get("response_minutes", 1.0),
                 "Activation up (€/MWh)": products.get(p, {}).get("activation_eur_per_mwh_up", 0.0),
                 "Activation down (€/MWh)": products.get(p, {}).get("activation_eur_per_mwh_down", 0.0),
                 "Balancing deployment": products.get(p, {}).get("balancing_deployment", True),
                 "Defined": p in products} for p in adapter.PRODUCTS]
        src = state.editor_source("products", lambda: pd.DataFrame(prow))
        edited = st.data_editor(src, key=f"ed_prod_{ver}", hide_index=True, disabled=["Product"], column_config={
            "Response time (min)": cc.NumberColumn(min_value=0.01, help="Full activation time (min)."),
            "Activation up (€/MWh)": cc.NumberColumn(min_value=0.0, help="Energy price of upward activation."),
            "Activation down (€/MWh)": cc.NumberColumn(min_value=0.0, help="Energy price of downward activation."),
            "Balancing deployment": cc.CheckboxColumn(help="May cover hourly forecast deviations (off for FCR)."),
            "Defined": cc.CheckboxColumn(help="Include this product in stochastic.reserve_products.")})
        for _, r in edited.iterrows():
            if r["Defined"]:
                spec = {"response_minutes": _clean(float(r["Response time (min)"])),
                        "activation_eur_per_mwh_up": _clean(float(r["Activation up (€/MWh)"])),
                        "activation_eur_per_mwh_down": _clean(float(r["Activation down (€/MWh)"]))}
                if not r["Balancing deployment"] or "balancing_deployment" in products.get(r["Product"], {}):
                    spec["balancing_deployment"] = bool(r["Balancing deployment"])
                products[r["Product"]] = spec
            else:
                products.pop(r["Product"], None)
    else:
        config.pop("reserve_link_mode", None)

# ------------------------------------------------------------------ constraints
FLAG_HELP = {
    "min_max_constraint": ("Unit min/max power limits", "Bounds of each unit's power by state and availability."),
    "load_production_balance_constraint": ("Load–production balance", "Required by the stochastic RDAS."),
    "operating_states_min_transition_time_between_states_constraint_a":
        ("Min time between states (a)", "Minimum transition times between operating states, type a."),
    "operating_states_min_transition_time_between_states_constraint_b":
        ("Min time between states (b)", "Minimum transition times between operating states, type b."),
    "operating_states_max_transition_time_between_states_constraint_b":
        ("Max time in transition (b)", "Maximum time a unit may stay in a transient state."),
    "state_min_time_constraint": ("Min up / down time", "Minimum ON and OFF times of the binary state."),
    "ramp_up_down_constraints": ("Ramp limits", "Ramp up/down rates between periods (kW/min)."),
    "forbidden_zones_constraint": ("Forbidden zones", "Exclude forbidden operating bands."),
    "must_run_units_constraint": ("MustRun", "Units flagged must-run stay online."),
    "allowed_thermal_states_transition_constraints": ("Allowed state transitions", "Required by the stochastic RDAS."),
    "res_pv_dispatch_variables_constraints": ("RES set-point dispatch (RES-share equalisation)",
                                              "Legacy set-point algorithm sharing curtailment across RES/PV units."),
    "testing_mode_constraints": ("Testing mode", "Units in testing produce their test power."),
    "OOS_mode_constraints": ("Out-of-service modes", "Out-of-service more-than / less-than limits."),
}
REQUIRED = {"load_production_balance_constraint", "allowed_thermal_states_transition_constraints"}
with tabs[4]:
    kpi.section("Optional constraints", "Toggle constraint families of the legacy MMS kernel. Reserve products "
                "are on the Reserves tab.")
    flags = data["constraints"]
    keys = [k for k in flags if k != "APRR_calculations" and not k.endswith("_active_power_reserves_constraint")]
    cols = st.columns(2)
    for k, key in enumerate(keys):
        label, help_text = FLAG_HELP.get(key, (key.replace("_", " "), "Legacy constraint flag."))
        with cols[k % 2]:
            flags[key] = st.toggle(label, bool(flags[key]), key=f"flag_{key}_{ver}", disabled=key in REQUIRED,
                                   help=f"{help_text}  \n`constraints.{key}`")
    st.space("small")
    kpi.section("RES dispatch coefficients")
    o1, o2, o3 = st.columns(3)
    with o1:
        num("Other_coefficients.x_res_pv_dynamic", "RES/PV dynamic share (-)",
            "Dynamic penetration coefficient of the set-point algorithm (fraction of load).", lo=0.0, hi=1.0,
            step=0.01, fmt="%.3f")
    with o2:
        num("Other_coefficients.PV_Participation_coefficient", "PV participation (%)",
            "PV participation coefficient in the set-point sharing (%).", lo=0.0, hi=100.0)
    with o3:
        inc = st.toggle("Include PV units", bool(data["Other_coefficients"].get("include_PV", 1)),
                        key=f"incpv_{ver}", help="Other_coefficients.include_PV.")
        data["Other_coefficients"]["include_PV"] = int(inc)

# ------------------------------------------------------------------ storage economics
with tabs[5]:
    stores = data["stochastic"].get("storage", [])
    if not stores:
        st.info("This case has no BESS (stochastic.storage).", icon="🔋")
    for j, store in enumerate(stores):
        kpi.section(f"BESS {store['id']}", "Economic terms of the storage recourse.")
        e1, e2, e3 = st.columns(3)
        with e1:
            value = st.number_input("Throughput cost (€/MWh)", 0.0, None, float(store["throughput_eur_per_mwh"]),
                                    key=f"thr_{j}_{ver}", help="Degradation cost per MWh charged or discharged.")
            store["throughput_eur_per_mwh"] = _clean(value)
        for col, key, label, help_text, default in (
                (e2, "terminal_value_eur_per_mwh", "Terminal SOC value (€/MWh)",
                 "Value of energy left at the end of the horizon (negative cost).", 40.0),
                (e3, "max_cycles_per_horizon", "Max cycles per horizon (-)",
                 "Equivalent full cycles allowed over the horizon.", 1.0)):
            with col:
                present = key in store
                use = st.toggle(f"Set {label.split(' (')[0].lower()}", present, key=f"use_{key}_{j}_{ver}")
                if use:
                    store[key] = _clean(st.number_input(label, 0.0, None, float(store.get(key, default)),
                                                        key=f"{key}_{j}_{ver}", help=help_text))
                else:
                    store.pop(key, None)
        e4, e5, _ = st.columns(3)
        for col, key, label, help_text, default in (
                (e4, "terminal_shortfall_penalty_eur_per_mwh", "Terminal shortfall penalty (€/MWh)",
                 "Soft terminal SOC target: shortfall is penalised instead of infeasible.", 500.0),
                (e5, "soc_recovery_penalty_eur_per_mwh", "SOC recovery penalty (€/MWh)",
                 "Allows an initial SOC below the minimum with a penalised recovery.", 500.0)):
            with col:
                present = key in store
                use = st.toggle(f"Set {label.split(' (')[0].lower()}", present, key=f"use_{key}_{j}_{ver}")
                if use:
                    store[key] = _clean(st.number_input(label, 0.01, None, float(store.get(key, default)),
                                                        key=f"{key}_{j}_{ver}", help=help_text))
                else:
                    store.pop(key, None)

# ------------------------------------------------------------------ save / load
with tabs[6]:
    kpi.section("Parameter configurations", "Saved to configs/<name>.json: solver options plus every parameter on "
                "this page (not units or scenarios).")
    s1, s2 = st.columns(2)
    with s1:
        cfg_name = st.text_input("Config name", placeholder="e.g. bounded_cvar_0.3")
        if st.button("💾 Save config", disabled=not cfg_name, type="primary"):
            try:
                path = adapter.save_config(cfg_name, {"solver": ss.solver_opts,
                                                      "parameters": adapter.parameters_snapshot(data)})
                st.toast(f"Saved {adapter.case_label(path)}", icon="💾")
            except OSError as exc:
                tables.error_box("Could not save", str(exc))
    with s2:
        configs = adapter.list_configs()
        upload = st.file_uploader("…or upload a config JSON", type=["json"])
        pick = st.selectbox("Saved configs", [adapter.case_label(p) for p in configs] or ["(none)"])
        if st.button("📂 Load config", disabled=not configs and upload is None):
            try:
                payload = json.loads(upload.getvalue()) if upload is not None else \
                    adapter.read_json(configs[[adapter.case_label(p) for p in configs].index(pick)])
                skipped = adapter.apply_parameters(data, payload.get("parameters", {}))
                ss.solver_opts = dict(state.DEFAULT_SOLVER, **payload.get("solver", {}))
                state.bump()
                st.toast("Config applied." + (f" Skipped: {'; '.join(skipped)}" if skipped else ""), icon="📂")
                st.rerun()
            except (OSError, ValueError, KeyError) as exc:
                tables.error_box("Could not load the config", str(exc))
