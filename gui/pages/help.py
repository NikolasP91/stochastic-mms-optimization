"""❓ Help: how to use the GUI, glossary and status meanings."""

from __future__ import annotations

import streamlit as st

from gui import theme
from gui.components import kpi

st.title("Help")

kpi.section("How to use in 5 steps")
st.markdown("""
1. **Pick a case** in the sidebar (examples/, cases/ or upload a JSON). A file without a `stochastic`
   section gets its nominal forecast as one scenario.
2. **Check the inputs** (📥 Inputs): units, forecasts and scenarios, initial conditions. Edit values in the
   tables and press **Validate inputs**; every problem names the unit and field.
3. **Set the parameters** (⚙️ Parameters): solver and time limit, slack policy and CVaR, penalties, reserve
   requirements, optional constraints, BESS economics. Save them as a config for later.
4. **Choose the mode and press ▶ Run optimization.** *RDAS* solves the hourly stochastic day-ahead schedule;
   *DS* solves the deterministic 15-min schedule for the selected forecast. The solver runs in the background:
   the live log is in the sidebar and you can keep browsing.
5. **Read the results** (🏠 Overview, 📊 Results) and compare runs (🔁 Compare runs). Download tables as CSV or
   Excel; each chart has a PNG button in its toolbar.
""")

kpi.section("Glossary")
GLOSSARY = {
    "RDAS (ΚΗΕΠ)": "Rolling Day-Ahead Scheduling: hourly unit commitment and dispatch for the next day, re-run "
                   "as forecasts update. Hour t = 0 is the observed previous hour (hour 24 of the previous day).",
    "DS": "Dispatch Scheduling: short-term schedule with 15-min intervals (e.g. 16 × 15 min = 4 h). In this GUI "
          "it runs the deterministic legacy MMS kernel on one forecast.",
    "Scenario": "One possible joint path of load and RES output over the horizon, with probability π_s. "
                "Probabilities must sum to 1.",
    "First stage / common decisions": "Decisions taken before the uncertainty is revealed: commitment, operating "
                                      "states, reserve capacity (and BESS reserve). Identical in all scenarios.",
    "Recourse": "Decisions that adapt to the realised scenario: dispatch, reserve activation, BESS "
                "charge/discharge, permitted slacks.",
    "Nonanticipativity": "Decisions may only depend on information already available. Two-stage: first-stage "
                         "variables are equal across scenarios. Multistage tree: scenarios sharing a node also "
                         "share their recourse decisions in that node's hours.",
    "Expected value view": "Probability-weighted average of scenario results. Useful as a summary; it is not an "
                           "operating schedule.",
    "Primary reserve (FCR)": "Fast frequency containment, seconds to ~1 min.",
    "Secondary reserve (aFRR)": "Automatic frequency restoration via AGC, minutes.",
    "Tertiary reserve (mFRR)": "Manual frequency restoration / replacement, ~15 min.",
    "Headroom / footroom": "Room to increase output up to the active upper limit / to decrease to the minimum "
                           "stable output.",
    "Load shedding": "Unserved demand (slack `s_load_minus_`), penalised with `x_load` €/MW per period.",
    "Slack variable": "A permitted, penalised relaxation of a constraint (reserve shortfall, ramp relaxation, "
                      "timers …). Non-zero slacks are listed in the Overview warnings.",
    "CVaR": "Conditional Value-at-Risk: mean cost of the worst (1 − α) share of scenarios; weight λ trades "
            "expected cost against tail risk.",
    "VSS / EVPI": "VSS = EEV − RP: what you save by planning with scenarios instead of the mean forecast. "
                  "EVPI = RP − WS: what a perfect forecast would be worth.",
    "MIP gap": "Relative distance between the best solution and the best bound. The engine requires 0 for "
               "'Optimal'.",
}
for term, text in GLOSSARY.items():
    st.markdown(f"**{term}** – {text}")

kpi.section("Run status")
for status in ("Not run", "Running", "Optimal", "Feasible", "Time limit", "Infeasible", "Input error", "Error",
               "Cancelled"):
    c1, c2 = st.columns([1, 5], vertical_alignment="center")
    with c1:
        kpi.status_badge(status)
    with c2:
        st.markdown(kpi.STATUS_HELP[status])

kpi.section("Colours")
chips = " ".join(f'<span class="legend-chip" style="background:{theme.TYPE_BASE[k]}"></span>{v} &nbsp;'
                 for k, v in theme.TYPE_LABELS.items())
st.markdown(chips + f'<span class="legend-chip" style="background:{theme.LOAD_SHED}"></span>Load shedding',
            unsafe_allow_html=True)
st.caption("Each unit keeps its colour on every chart; several units of one type use lighter/darker steps of the "
           "type's hue. Scenarios use one blue ramp; the expected value is the bold light line.")

kpi.section("Command line equivalents")
st.code("""# stochastic RDAS (what ▶ Run does in RDAS mode)
.venv\\Scripts\\python.exe stochastic_main.py examples/small_tree_bess.json -o runs/tree_bess.json
# with VSS / EVPI
.venv\\Scripts\\python.exe stochastic_main.py examples/small_stochastic.json --compare -o runs/comparison.json
# deterministic MMS (what DS mode runs, on a converted 15-min input)
.venv\\Scripts\\python.exe main.py new_json_test.json -o optimization_output.json""", language="powershell")
