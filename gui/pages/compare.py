"""🔁 Compare runs: run history, side-by-side KPIs and dispatch, VSS / EVPI."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from gui import adapter, state, theme
from gui.components import charts, kpi

ss = st.session_state
st.title("Compare runs")
st.markdown('<div class="section-note">Every run is stored in <code>runs/gui/&lt;timestamp&gt;_&lt;mode&gt;_'
            '&lt;case&gt;/</code> with its exact input, request (solver + parameters), solver log and result.</div>',
            unsafe_allow_html=True)

runs = adapter.list_runs()
if not runs:
    st.info("No runs yet. Solve a case first.", icon="🔁")
    st.stop()

history = pd.DataFrame([{"run": r["name"], "mode": r["mode"], "case": r["case"], "created": r["created"],
                         "status": r["status"], "expected cost (€)": r["expected_cost"],
                         "VSS/EVPI": "yes" if r["compare"] else ""} for r in runs])
kpi.section("Run history")
st.dataframe(history, hide_index=True, height=min(38 * len(history) + 40, 320),
             column_config={"expected cost (€)": st.column_config.NumberColumn(format="%.2f")})
o1, o2 = st.columns([3, 1], vertical_alignment="bottom")
with o1:
    open_pick = st.selectbox("Open a run on the Overview / Results pages", history["run"].tolist())
with o2:
    if st.button("📂 Open run", width="stretch", type="primary"):
        ss.result_dir = str(adapter.RUNS_ROOT / open_pick)
        st.toast(f"Showing {open_pick}", icon="📂")
        st.rerun()

finished = [r for r in runs if r["status"] in ("Optimal", "Feasible")]
if len(finished) < 2:
    st.info("Solve at least two runs to compare them side by side.", icon="ℹ️")
    st.stop()

st.space("small")
kpi.section("Side-by-side comparison")
names = [r["name"] for r in finished]
c1, c2 = st.columns(2)
a_name = c1.selectbox("Run A", names, index=0)
b_name = c2.selectbox("Run B", names, index=1 if len(names) > 1 else 0)


@st.cache_data(show_spinner=False, max_entries=16)
def _load(name: str, mtime: float) -> adapter.Results:
    return adapter.load_results(adapter.RUNS_ROOT / name)


def load(name: str) -> adapter.Results:
    path = adapter.RUNS_ROOT / name / "status.json"
    return _load(name, path.stat().st_mtime if path.exists() else 0)


ra, rb = load(a_name), load(b_name)
ka, kb = adapter.kpis(ra), adapter.kpis(rb)
ROWS = [("Mode", lambda r, k: r.mode), ("Case", lambda r, k: r.request.get("case")),
        ("Solver", lambda r, k: r.request.get("solver")),
        ("Expected total cost (€)", lambda r, k: k.get("expected_cost")),
        ("First-stage cost (€)", lambda r, k: r.meta.get("first_stage_cost_eur")),
        ("CVaR (€)", lambda r, k: k.get("cvar")),
        ("Start-up / shut-down (€)", lambda r, k: k.get("cost_startup")),
        ("Penalties (€)", lambda r, k: k.get("cost_penalties")),
        ("Load shedding (MWh)", lambda r, k: k.get("load_shed_mwh")),
        ("RES share (%)", lambda r, k: 100 * k["res_share"] if k.get("res_share") is not None else None),
        ("Start-ups", lambda r, k: k.get("startups")),
        ("Scenarios", lambda r, k: k.get("n_scenarios")),
        ("Solve time (s)", lambda r, k: k.get("solve_seconds")),
        ("Rows / columns / binaries", lambda r, k: f"{k.get('rows')} / {k.get('cols')} / {k.get('binaries')}")]
table = []
for label, fn in ROWS:
    va, vb = fn(ra, ka), fn(rb, kb)
    delta = vb - va if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None
    table.append({"KPI": label, "Run A": va, "Run B": vb, "B − A": delta})
def _show(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


frame = pd.DataFrame(table)
for col in ("Run A", "Run B", "B − A"):
    frame[col] = frame[col].map(_show)
st.dataframe(frame, hide_index=True)

if ra.mode != rb.mode:
    st.caption("RDAS (hourly) and DS (15-min) runs are aligned on a time axis in hours. DS is deterministic, "
               "so its costs refer to one forecast and a shorter horizon.")


def expected_by_type(res: adapter.Results) -> pd.DataFrame:
    e = adapter.expected(res.dispatch, ["type", "t"])
    return e


ea, eb = expected_by_type(ra), expected_by_type(rb)
types = [t for t in charts.STACK_ORDER if t in set(ea["type"]) | set(eb["type"])]
pick = st.segmented_control("Series", ["Total thermal", "Total RES", "Load shedding"] + [
    theme.TYPE_LABELS[t] for t in types], default="Total thermal", key="cmp_series") or "Total thermal"


def series(res: adapter.Results, e: pd.DataFrame) -> pd.DataFrame:
    if pick == "Load shedding":
        return adapter.expected(res.load, ["t"], "shed_mw").rename(columns={"shed_mw": "mw"})
    if pick == "Total thermal":
        sel = ["thermal", "biomass", "partial"]
    elif pick == "Total RES":
        sel = ["wind", "pv", "hybrid"]
    else:
        sel = [t for t, label in theme.TYPE_LABELS.items() if label == pick]
    return e[e["type"].isin(sel)].groupby("t", as_index=False)["mw"].sum()


frames = {f"A · {a_name}": series(ra, ea), f"B · {b_name}": series(rb, eb)}
charts.show(charts.compare_lines(frames, f"{pick} – expected (MW)", "MW",
                                 {f"A · {a_name}": ra.minutes, f"B · {b_name}": rb.minutes}),
            "compare_runs", key="cmp_lines")

if ra.mode == rb.mode and not ra.commitment.empty and not rb.commitment.empty and ra.periods == rb.periods:
    merged = ra.commitment.merge(rb.commitment, on=["unit", "t"], suffixes=("_a", "_b"))
    changed = merged[merged["on_a"] != merged["on_b"]]
    if changed.empty:
        st.success("Both runs commit the same units in every period.", icon="✅")
    else:
        st.warning(f"Commitment differs in {len(changed)} unit-period(s).", icon="⚠️")
        st.dataframe(changed[["unit", "t", "on_a", "on_b"]].rename(columns={"on_a": "A on", "on_b": "B on"}),
                     hide_index=True)

bench = [r for r in (ra, rb) if r.benchmarks]
if bench:
    st.space("small")
    kpi.section("Stochastic vs deterministic (from a VSS/EVPI run)")
    b = bench[0].benchmarks
    kpi.card_row([
        {"label": "VSS", "value": kpi.fmt(b.get("VSS"), 2), "unit": "€", "accent": True,
         "sub": f"run {Path(bench[0].run_dir).name}"},
        {"label": "EVPI", "value": kpi.fmt(b.get("EVPI"), 2), "unit": "€"},
        {"label": "RP / EEV / WS", "value": f"{kpi.fmt(b.get('RP'))} / {kpi.fmt(b.get('EEV'))} / {kpi.fmt(b.get('WS'))}",
         "unit": "€"},
    ])
    charts.show(charts.benchmark_bars(b), "benchmarks", key="cmp_bench")
else:
    st.caption("Enable **Compute VSS / EVPI** (Parameters → Solver) for a run to see the value of the stochastic "
               "solution and of perfect information.")
