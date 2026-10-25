"""Entry point: ``streamlit run gui/app.py`` (from the project root).

Builds the always-visible sidebar (case, mode, scenario view, run control and
status) and the page navigation.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Stochastic RDAS · DS Scheduler", page_icon="⚡", layout="wide",
                   initial_sidebar_state="expanded")

from gui import adapter, state, theme  # noqa: E402
from gui.components import kpi, tables  # noqa: E402

st.markdown(theme.CSS, unsafe_allow_html=True)
state.init()
ss = st.session_state

UPLOAD = "⬆ Upload a JSON file…"


# ------------------------------------------------------------------ sidebar pieces
def _case_selector() -> None:
    cases = adapter.discover_cases()
    labels = [adapter.case_label(p) for p in cases]
    current = ss.case_label if ss.case_label in labels else None
    options = labels + [UPLOAD]
    index = options.index(current) if current else len(options) - 1
    choice = st.selectbox("Case", options, index=index, key=f"case_select_{ss.ver}",
                          help="Input JSON (MMS units + `stochastic` section). Files are searched in examples/, "
                               "cases/ and the project root. Edits are kept in memory until you save them.")
    if choice == UPLOAD:
        upload = st.file_uploader("Input JSON", type=["json"], label_visibility="collapsed",
                                  help="An MMS input file; a `stochastic` section is added if missing.")
        if upload is not None and ss.case_label != f"upload: {upload.name}":
            try:
                state.load_uploaded(upload.name, upload.getvalue())
                st.toast(f"Loaded {upload.name}", icon="📂")
                st.rerun()
            except (ValueError, UnicodeDecodeError) as exc:
                st.error(f"Cannot load this file: {exc}")
    elif choice != ss.case_label:
        if state.running():
            st.warning("A run is in progress; the case will switch, the run continues in the background.")
        state.load_file(cases[labels.index(choice)])
        st.toast(f"Loaded {choice}", icon="📂")
        st.rerun()
    data = state.work()
    n = adapter.horizon(data)
    scen = len(adapter.scenario_ids(data, positive_only=True))
    st.caption(f"{len(data['Generating_Units'])} units · {len(data['stochastic'].get('storage', []))} BESS · "
               f"{scen} scenario(s) · {n} × {adapter.resolution_minutes(data)} min")


def _mode_and_view() -> None:
    mode = st.segmented_control(
        "Mode", ["RDAS", "DS"], default=ss.mode, key="mode_ctrl", required=True,
        help="RDAS: hourly stochastic day-ahead schedule (two-stage / multistage, all scenarios). "
             "DS: deterministic dispatch schedule with 15-min intervals from the legacy MMS kernel, "
             "using the forecast picked below.")
    if mode and mode != ss.mode:
        ss.mode = mode
        ss.issues = None
    ids = adapter.scenario_ids(state.work())
    options = [adapter.EXPECTED_ID, adapter.ALL_ID] + ids
    if ss.scenario_choice not in options:
        ss.scenario_choice = adapter.EXPECTED_ID
    ss.scenario_choice = st.selectbox(
        "Scenario view", options, index=options.index(ss.scenario_choice),
        help="Which scenario the charts show: the probability-weighted expected value, all scenarios "
             "(overlays / small multiples) or one scenario. In DS mode it is also the deterministic forecast "
             "(expected value for 'All scenarios').")


def _run_controls() -> None:
    running = state.running()
    if st.button("▶ Run optimization", type="primary", width="stretch", disabled=running,
                 help="Validate the current inputs and parameters, then solve in a background process."):
        opts = ss.solver_opts
        with st.spinner("Validating inputs…"):
            issues = adapter.validate_case(state.work(), ss.mode, ss.scenario_choice, opts["ds_hours"])
        ss.issues = issues
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            st.toast(f"{len(errors)} input error(s): nothing was solved. See Inputs → Validate.", icon="🛑")
        else:
            try:
                ss.run = adapter.start_run(
                    state.work(), mode=ss.mode, case_name=ss.case_label, solver=opts["solver"],
                    time_limit=opts["time_limit"] or None, accept_incumbent=opts["accept_incumbent"],
                    compare=opts["compare"], scenario_choice=ss.scenario_choice, ds_hours=opts["ds_hours"],
                    params_snapshot=adapter.parameters_snapshot(state.work()))
                ss.run_notified = False
                st.toast("Solver started in the background.", icon="⚙️")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                tables.error_box("Could not start the run", str(exc))
    if ss.issues:
        errors = [i for i in ss.issues if i.severity == "error"]
        if errors:
            st.error(f"{len(errors)} input error(s). First: **{errors[0].location}** – {errors[0].message}",
                     icon="🛑")


def _status_panel() -> None:
    running = state.running()

    @st.fragment(run_every=1.0 if running else None)
    def panel() -> None:
        run = ss.get("run")
        if run is not None and run.process is not None and run.process.poll() is None:
            kpi.status_badge("Running")
            elapsed = (datetime.now() - run.started).total_seconds()
            st.caption(f"Started {run.started:%H:%M:%S} · {elapsed:,.0f} s elapsed")
            if st.button("■ Cancel run", width="stretch"):
                adapter.cancel_run(run)
                st.rerun(scope="app")
            with st.expander("Solver log (live)", expanded=True):
                st.code(adapter.log_tail(run.run_dir, 25) or "starting…", language="text")
            return
        if run is not None and not ss.get("run_notified", True):
            ss.run_notified = True
            ss.result_dir = str(run.run_dir)
            status = adapter.finalize_run(run)
            icon = {"Optimal": "✅", "Feasible": "⏱️"}.get(status, "🛑")
            st.toast(f"Run finished: {status}", icon=icon)
            st.rerun(scope="app")
        res = state.results()
        kpi.status_badge(res.status if res else "Not run")
        if res:
            finished = res.meta.get("finished") or res.meta.get("started") or ""
            st.caption(f"Last run: {finished.replace('T', ' ')} · {res.mode} · {res.request.get('solver', '')}")
            if res.status not in ("Optimal", "Feasible") and res.message:
                st.caption(res.message[:240])
            with st.expander("Solver log"):
                st.code(adapter.log_tail(Path(res.run_dir), 40) or "(empty)", language="text")

    panel()


def sidebar() -> None:
    with st.sidebar:
        st.markdown("### ⚡ Stochastic RDAS · DS")
        _case_selector()
        _mode_and_view()
        st.divider()
        _run_controls()
        _status_panel()


# ------------------------------------------------------------------ navigation
PAGES = Path(__file__).parent / "pages"
navigation = st.navigation([
    st.Page(PAGES / "overview.py", title="Overview", icon="🏠", default=True),
    st.Page(PAGES / "inputs.py", title="Inputs", icon="📥"),
    st.Page(PAGES / "parameters.py", title="Parameters", icon="⚙️"),
    st.Page(PAGES / "results.py", title="Results", icon="📊"),
    st.Page(PAGES / "compare.py", title="Compare runs", icon="🔁"),
    st.Page(PAGES / "help.py", title="Help", icon="❓"),
])
sidebar()
navigation.run()
