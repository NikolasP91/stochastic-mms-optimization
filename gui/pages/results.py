"""📊 Results: common decisions, scenario schedules, reserves, costs, constraint health."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from gui import adapter, state, theme
from gui.components import charts, kpi, tables

ss = st.session_state
res = state.results()

st.title("Results")
if res is None:
    st.info("No results yet. Press **▶ Run optimization** in the sidebar, or open a past run on the "
            "**Compare runs** page.", icon="📊")
    st.stop()

st.caption(f"Run `{Path(res.run_dir).name}` · {res.mode} · {res.request.get('case')} · status **{res.status}**")
if not res.ok:
    tables.error_box(f"The run ended with status: {res.status}", res.message or res.error.get("message", ""),
                     res.error.get("traceback") or json.dumps(res.error.get("details", {}), indent=2, default=str))
    tips = {
        "Infeasible": ["Use the bounded slack policy with caps on `s_load_minus_` and reserve shortfalls "
                       "(Parameters → Model & risk) to see *where* the system is short.",
                       "Check initial states, remaining min up/down times and must-run flags (Inputs).",
                       "Lower BESS terminal SOC targets or set a terminal shortfall penalty.",
                       "With a scenario tree, scenarios sharing a node must carry identical data."],
        "Time limit": ["Raise the time limit (Parameters → Solver).",
                       "Enable 'Accept time-limited incumbent' to report the best feasible plan.",
                       "Reduce the number of scenarios or the horizon for exploratory runs."],
        "Input error": ["Open Inputs → Validate inputs: every problem is listed with its unit and field."],
    }.get(res.status, ["Open the solver log in the sidebar for details."])
    st.info("**What you can try**\n\n" + "\n".join(f"- {t}" for t in tips), icon="💡")
    st.stop()

if res.error:
    tables.error_box("Part of the result could not be displayed", res.error.get("message", ""),
                     res.error.get("traceback"))
if res.status == "Feasible":
    st.warning("Time-limited incumbent: feasible but **not proven optimal**.", icon="⏱️")

units = res.units
periods = res.periods
minutes = res.minutes
scen_ids = res.scenarios["scenario"].tolist()
scolors = theme.scenario_colors(scen_ids)
probabilities = dict(zip(res.scenarios["scenario"], res.scenarios["probability"]))
choice = ss.scenario_choice
view = choice if choice in scen_ids else adapter.EXPECTED_ID
if choice == adapter.ALL_ID:
    view = adapter.ALL_ID

names = ["🧭 Common decisions", "📈 Scenario schedules", "🛡️ Reserves", "💶 Costs", "🩺 Constraint health",
         "⬇ Downloads"]
if res.benchmarks:
    names.insert(4, "⚖️ Stochastic vs deterministic")
tabs = dict(zip(names, st.tabs(names)))

# ------------------------------------------------------------------ common decisions
with tabs["🧭 Common decisions"]:
    common_note = ("First-stage decisions: identical in every scenario because they are made before the "
                   "uncertainty is revealed (nonanticipativity)." if res.mode == "RDAS" else
                   "Deterministic DS commitment for the selected forecast.")
    kpi.section("Unit commitment & operating states", common_note, tag="common" if res.mode == "RDAS" else "")
    charts.show(charts.commitment_heatmap(res.commitment, units, minutes, periods), "commitment", key="r_uc")
    events = res.commitment[(res.commitment["startup"] > 0) | (res.commitment["shutdown"] > 0)]
    if not events.empty:
        ev = events.assign(event=events.apply(lambda r: "▲ start-up" if r["startup"] else "▼ shut-down", axis=1),
                           period=events["t"].map(lambda t: adapter.period_label(t, minutes)))
        st.dataframe(ev[["unit", "period", "event", "state_label"]], hide_index=True)
    rp = res.reserves_provided
    if not rp.empty:
        kpi.section("Reserve capacity awards", "Procured reserve per unit (MW); first-stage in RDAS.",
                    tag="common" if res.mode == "RDAS" else "")
        wide = rp.pivot_table(index=["unit", "product", "direction"], columns="t", values="mw", aggfunc="sum")
        wide = wide[(wide.abs() > 1e-9).any(axis=1)].round(3)
        wide.columns = [adapter.period_label(t, minutes) for t in wide.columns]
        st.dataframe(wide.reset_index(), hide_index=True)
    if not res.implementable.empty:
        kpi.section("Implementable dispatch (tree root)", "Root-node recourse decisions are identical across "
                    "scenarios, hence issuable now.", tag="common")
        tables.table(res.implementable, "implementable_dispatch", "imp")

# ------------------------------------------------------------------ scenario schedules
with tabs["📈 Scenario schedules"]:
    kpi.section("Dispatch per unit", "Scenario-dependent recourse. Use the sidebar 'Scenario view' to switch "
                "between the expected value, one scenario or all scenarios.", tag="scenario")
    if view == adapter.ALL_ID and len(scen_ids) > 1:
        charts.show(charts.dispatch_small_multiples(res.dispatch, res.load, units, minutes, periods, probabilities),
                    "dispatch_all", key="r_sm")
    else:
        v = view if view != adapter.ALL_ID else adapter.EXPECTED_ID
        d = adapter.pick_scenario(res.dispatch, v, ["unit", "type", "t"])
        lo = adapter.pick_scenario(res.load, v, ["t"], "load_mw")
        if v == adapter.EXPECTED_ID:
            lo = lo.merge(adapter.expected(res.load, ["t"], "shed_mw"), on="t")
        title = "Expected dispatch (MW)" if v == adapter.EXPECTED_ID else f"Dispatch – {v} (MW)"
        charts.show(charts.dispatch_stack(d, lo, units, minutes, title, periods), "dispatch", key="r_disp")
    u1, u2 = st.columns([1, 2], vertical_alignment="bottom")
    with u1:
        unit_pick = st.selectbox("Unit across scenarios", units[~units["is_storage"]]["unit"].tolist(),
                                 help="One unit's output in every scenario, with the expected value in bold.")
    frame = res.dispatch[res.dispatch["unit"] == unit_pick]
    charts.show(charts.fan_chart(frame, f"{unit_pick} – output per scenario (MW)", "Power (MW)", minutes, periods,
                                 scenario_colors=scolors, height=320), "unit_fan", key="r_ufan")
    if not res.storage.empty:
        kpi.section("Battery / hybrid storage", "State of charge per scenario and charge/discharge power.",
                    tag="scenario")
        stores = list(dict.fromkeys(res.storage["store"]))
        case_input = adapter.read_json(Path(res.run_dir) / "input.json")
        specs = {s["id"]: s for s in case_input["stochastic"].get("storage", [])}
        for store_id in stores:
            spec = specs.get(store_id, {})
            charts.show(charts.soc_chart(res.storage, store_id, spec.get("capacity_mwh", 0), spec.get("min_mwh", 0),
                                         minutes, periods, scolors), f"soc_{store_id}", key=f"r_soc_{store_id}")
            color = units.set_index("unit")["color"].get(f"BESS {store_id}", theme.TYPE_BASE["storage"])
            sc = view if view in scen_ids else adapter.EXPECTED_ID
            charts.show(charts.charge_bars(res.storage, store_id, sc, minutes, periods, color),
                        f"bess_flows_{store_id}", key=f"r_flow_{store_id}")
    kpi.section("Load shedding", "Unserved power per scenario (MW).", tag="scenario")
    if res.load["shed_mw"].abs().sum() <= 1e-9:
        st.success("No load shedding in any scenario.", icon="✅")
    else:
        charts.show(charts.shedding_bars(res.load, minutes, periods, scolors), "load_shedding", key="r_shed")

# ------------------------------------------------------------------ reserves
with tabs["🛡️ Reserves"]:
    kpi.section("Required vs provided", "Provided capacity is the first-stage award (bars); requirements depend "
                "on each scenario's dispatch (lines; bold = expected).", tag="common" if res.mode == "RDAS" else "")
    if res.reserves_required.empty:
        st.info("Reserve constraints are disabled in this case.", icon="ℹ️")
    else:
        c1, c2 = st.columns(2)
        products = [p for p in adapter.PRODUCTS if p in set(res.reserves_required["product"])]
        product = c1.segmented_control("Product", products, default=products[0], key="r_prod",
                                       help="Primary (FCR), secondary (aFRR), tertiary (mFRR).") or products[0]
        direction = c2.segmented_control("Direction", ["up", "down"], default="up", key="r_dir") or "up"
        charts.show(charts.reserve_chart(res.reserves_provided, res.reserves_required, units, product, direction,
                                         minutes, periods, scolors), f"reserve_{product}_{direction}", key="r_res")
        short = res.reserves_required[res.reserves_required["shortfall_mw"] > 1e-7]
        if short.empty:
            st.success("Requirements are met in every scenario and period.", icon="✅")
        else:
            st.warning(f"Reserve shortfall in {short['scenario'].nunique()} scenario(s).", icon="⚠️")
            tables.table(short, "reserve_shortfall", "short")
    kpi.section("Headroom and footroom per unit", "Upward room to the active upper limit and downward room to the "
                "minimum stable output (MW).", tag="scenario")
    hv = view if view in scen_ids else adapter.EXPECTED_ID
    hr = adapter.pick_scenario(res.headroom, hv, ["unit", "type", "t"], "headroom_mw")
    fr = adapter.pick_scenario(res.headroom, hv, ["unit", "type", "t"], "footroom_mw")
    h1, h2 = st.columns(2)
    with h1:
        charts.show(charts.headroom_chart(hr, units, "headroom_mw", f"Upward headroom – {hv} (MW)", minutes, periods),
                    "headroom", key="r_head")
    with h2:
        charts.show(charts.headroom_chart(fr, units, "footroom_mw", f"Downward footroom – {hv} (MW)", minutes,
                                          periods), "footroom", key="r_foot")

# ------------------------------------------------------------------ costs
with tabs["💶 Costs"]:
    meta = res.meta
    kpi.card_row([
        {"label": "Expected total cost", "value": kpi.fmt(meta.get("expected_cost_eur")), "unit": "€", "accent": True},
        {"label": "First-stage cost", "value": kpi.fmt(meta.get("first_stage_cost_eur")), "unit": "€",
         "sub": "commitment, reserves (common)"},
        {"label": "Expected recourse", "value": kpi.fmt(meta.get("expected_recourse_cost_eur")), "unit": "€",
         "sub": "dispatch, activation, penalties"},
        {"label": f"CVaR {meta.get('cvar_alpha', 0.95):.0%}" if meta.get("cvar_eur") is not None else "CVaR",
         "value": kpi.fmt(meta.get("cvar_eur")), "unit": "€",
         "sub": f"weight λ = {meta.get('risk_weight', 0)}" if meta.get("cvar_eur") is not None else "n/a in DS"},
    ])
    st.space("small")
    w1, w2 = st.columns([1.3, 1], gap="large")
    with w1:
        charts.show(charts.cost_waterfall(res.waterfall, meta.get("expected_cost_eur"),
                                          "Expected objective breakdown (€)"), "cost_waterfall", key="r_wf")
        st.caption("Components reconcile with the engine's expected cost. 'Generation, activation & BESS' is the "
                   "expected recourse operating cost; start-up/shut-down are reconstructed from the common schedule."
                   if res.mode == "RDAS" else "Components from the legacy Objective_Breakdown_Report.")
    with w2:
        charts.show(charts.scenario_cost_bars(res.costs, meta.get("expected_cost_eur"), meta.get("cvar_eur"),
                                              scolors), "scenario_costs", key="r_sc")
    kpi.section("Per-scenario costs", "Probability-weighted; totals include the common first-stage cost.")
    show = res.costs.copy()
    tables.table(show, "scenario_costs", "costs", column_config={
        "probability": st.column_config.NumberColumn("p", format="%.4f"),
        **{c: st.column_config.NumberColumn(format="%.2f") for c in show.columns if c.endswith("_eur")},
        **{c: st.column_config.NumberColumn(format="%.4f") for c in show.columns if c.endswith("_mwh")}})
    st.caption(f"Σ p·total = {res.costs['weighted_total_eur'].sum():,.2f} €")

# ------------------------------------------------------------------ benchmarks
if res.benchmarks:
    with tabs["⚖️ Stochastic vs deterministic"]:
        b = res.benchmarks
        kpi.section("Value of the stochastic solution", "RP: stochastic plan · EEV: the deterministic (expected-"
                    "value) plan evaluated on the scenarios · WS: perfect information.")
        kpi.card_row([
            {"label": "VSS = EEV − RP", "value": kpi.fmt(b.get("VSS"), 2), "unit": "€", "accent": True,
             "sub": "saving from planning with scenarios"},
            {"label": "EVPI = RP − WS", "value": kpi.fmt(b.get("EVPI"), 2), "unit": "€",
             "sub": "value of a perfect forecast"},
            {"label": "RP", "value": kpi.fmt(b.get("RP")), "unit": "€"},
            {"label": "EEV", "value": kpi.fmt(b.get("EEV")), "unit": "€", "sub": b.get("EEV_status") or ""},
            {"label": "WS", "value": kpi.fmt(b.get("WS")), "unit": "€"},
        ])
        charts.show(charts.benchmark_bars(b), "vss_evpi", key="r_bench")
        dec = b.get("VSS_decomposition") or {}
        rows = [{"fixed from EV plan": k.replace("_", " "), "EEV (€)": v.get("EEV"), "VSS (€)": v.get("VSS"),
                 "fixed decisions": v.get("fixed_decisions")} for k, v in dec.items() if isinstance(v, dict)]
        if rows:
            st.markdown("**VSS decomposition** – which first-stage decisions carry the value (not additive)")
            st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
                "EEV (€)": st.column_config.NumberColumn(format="%.2f"),
                "VSS (€)": st.column_config.NumberColumn(format="%.2f")})
        if b.get("risk_averse_expected_cost") is not None:
            st.info(f"Risk-averse plan (CVaR weight > 0): expected cost {b['risk_averse_expected_cost']:,.2f} €, "
                    f"CVaR {b['risk_averse_cvar']:,.2f} €. Benchmarks above are risk-neutral.", icon="ℹ️")

# ------------------------------------------------------------------ constraint health
with tabs["🩺 Constraint health"]:
    validation = res.meta.get("validation", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Residual audit", "passed" if validation.get("passed") else "failed", border=True,
              help="Every constraint of the solved MILP re-evaluated at the solution values.")
    residual = validation.get("max_constraint_residual")
    c2.metric("Max residual", f"{residual:.2e}" if isinstance(residual, (int, float)) else "—", border=True,
              help="Largest constraint violation found by the audit (should be ≈ 0).")
    c3.metric("Checked constraints", kpi.fmt(validation.get("checked_constraints")), border=True)
    c4.metric("Operational status", res.meta.get("operational_status", "—").replace("_", " "), border=True,
              help="'degraded' when any permitted slack is non-zero. Not a reliability certificate.")
    kpi.section("Active slacks / penalties", "Every non-zero relaxation variable, by scenario.")
    summary = adapter.warnings_summary(res)
    if summary.empty:
        st.success("No slack variable is active.", icon="✅")
    else:
        st.dataframe(summary, hide_index=True)
        tables.table(res.slacks, "slacks", "slacks")
    kpi.section("Binding physical limits", "Detected from solution values: units at their upper or minimum "
                "limit, ramp-limited moves, BESS at full / minimum SOC.")
    lim = res.limits
    if view in scen_ids:
        lim = lim[lim["scenario"] == view]
    if not lim.empty:
        counts = lim.groupby("limit").size().rename("occurrences").reset_index()
        st.dataframe(counts, hide_index=True)
    tables.table(lim, "binding_limits", "limits", height=300)
    for note in res.notes:
        st.caption(f"**{note.get('code', '')}** – {note.get('message', '')}")

# ------------------------------------------------------------------ downloads
with tabs["⬇ Downloads"]:
    kpi.section("Export", "Every table as CSV, all tables as one Excel workbook, and the raw engine JSON. Charts: "
                "use the camera icon in each chart's toolbar for PNG.")
    xlsx = adapter.excel_bytes(res)
    d1, d2 = st.columns(2)
    if xlsx:
        d1.download_button("⬇ Excel workbook (all tables)", xlsx, file_name=f"{Path(res.run_dir).name}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
    raw = Path(res.run_dir) / "result.json"
    if raw.exists():
        d2.download_button("⬇ Raw result JSON", raw.read_bytes(), file_name="result.json", mime="application/json")
    cols = st.columns(3)
    for k, (name, frame) in enumerate(res.tables().items()):
        with cols[k % 3]:
            st.download_button(f"⬇ {name}.csv ({len(frame)} rows)", frame.to_csv(index=False).encode("utf-8"),
                               file_name=f"{name}.csv", mime="text/csv", key=f"dl_all_{name}", width="stretch")
    st.caption(f"Run folder: {res.run_dir}")
