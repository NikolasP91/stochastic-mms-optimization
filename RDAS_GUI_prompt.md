# Prompt: Build a GUI for the Stochastic RDAS/DS Scheduler

> Paste everything below the line into your AI coding assistant in VS Code (Copilot Chat / Claude Code / Cursor) with the project folder open.

---

## Role & goal

You are a senior Python developer and UI/UX designer. In this workspace there is a **stochastic Rolling Day Ahead Scheduling (RDAS) / Dispatch Scheduling (DS)** program for a **non-interconnected island power system**, formulated as a **scenario-based two-stage stochastic MILP** in Python (PuLP, solver CBC/Gurobi/CPLEX).

Build a **beautiful, easy-to-use desktop/web GUI** that gives a clear overview of:

1. **Inputs** – units, forecasts, scenarios, initial conditions
2. **Parameters** – solver and model settings
3. **Outputs** – common (first-stage) decisions, scenario-dependent schedules, reserves, costs, slacks/penalties

The GUI must **wrap** the existing program. **Do not change the optimization model logic.** If you need hooks (e.g. a `run(config) -> results` function), add a thin adapter module rather than editing the model.

## Step 0 — Understand the project first (do this before writing any GUI code)

1. Explore the repository: entry point(s), model-building module(s), input JSON/CSV files, output files, config files.
2. Write me a short summary (≤ 20 lines) of:
   - how the program is run today (command, arguments, config),
   - every input file and its key fields (e.g. `gen_id`, `min/max power`, `ramp`, `min_time_on/off`, `time_On_left/time_Off_left`, `availability`, `current_Power`, `state`, startup/shutdown costs, `var_gen_cost`, APR up/down, operating states, `Production_Forecast`, `mustRun`, testing, `agc_configuration`, scenarios & probabilities, SOC of storage/hybrid units),
   - the outputs produced (variables, result JSON/CSV, objective breakdown),
   - how scenarios are defined (count, probabilities, which data vary per scenario).
3. List any assumptions or ambiguities and **ask me before continuing** if something critical is unclear.

## Technology

- **Streamlit** (preferred – pure Python, fast, good-looking) with **Plotly** for interactive charts and **pandas** for tables.
- Python 3.10+, runs on **Windows** inside a virtual environment.
- Provide `requirements_gui.txt` and a launcher: `streamlit run gui/app.py`.
- Keep GUI code in a separate `gui/` folder; no new heavy dependencies beyond streamlit, plotly, pandas.

## Design & aesthetics

- Clean, modern, "energy control room" look: dark theme by default (`.streamlit/config.toml`), with one accent colour (e.g. teal/cyan) and consistent colours per unit type (diesel/thermal, biomass/CHP, PV, wind, hybrid/battery, load shedding = red).
- **The same unit always has the same colour across every chart.** Scenarios use a consistent sequential palette; the expected/weighted value is drawn bold.
- Generous spacing, card-style KPI tiles, clear section headers, icons sparingly.
- Every input field has a **tooltip** (`help=`) explaining the parameter and its unit (MW, kW/min, €/MWh, h, %).
- Units of measure shown on all axes, tables and KPIs. Times shown as hours (RDAS: 24 h, hour 1 = previous day's hour 24) and 15-minute intervals (DS: 16 × 15 min).
- Non-blocking feedback: spinners while solving, toast/success/error messages, never a raw traceback (show it in a collapsible "Details" expander).

## Layout

**Sidebar (always visible)**
- Project/case selector (load input JSON or folder), mode switch **RDAS ⇄ DS**, scenario selector (single scenario / all / expected value), big **▶ Run optimization** button, status badge (Not run / Running / Optimal / Infeasible / Time limit), last-run timestamp.

**Page 1 – 🏠 Overview (dashboard)**
- KPI cards: expected total cost, cost breakdown (generation, start-up/shut-down, reserves, penalties), number of scenarios, units committed, total load shedding (expected), RES share, MIP gap, solve time, model size (rows / columns / binaries).
- Stacked area chart: expected dispatch per unit vs. load forecast.
- Small warning panel listing any non-zero slack/penalty variables (reserve shortfall, ramp relaxation, load shedding, forbidden-zone, testing).

**Page 2 – 📥 Inputs**
- Tabs: *Units* (editable table via `st.data_editor` with validation: min ≤ max, ramps ≥ 0, etc.), *Forecasts* (load, PV, wind, hybrid – line charts, per scenario as a fan chart), *Scenarios* (table of scenarios + probabilities, check they sum to 1; scenario-tree diagram if multi-stage), *Initial conditions* (current power, state, time on/off left, SOC).
- Buttons: Reset to file, Validate inputs, Save as new case (JSON). Show a diff of what the user changed.

**Page 3 – ⚙️ Parameters**
- Solver (CBC/Gurobi/CPLEX), time limit, MIP gap, threads, Big-M values, penalty costs, reserve requirements (primary/secondary/tertiary), horizon/resolution, terminal SOC value, toggles for optional constraints (MustRun, testing, N1/N2, RES-share equalisation).
- Each parameter: default value, allowed range, tooltip. "Restore defaults" button. Parameters saved to/loaded from a `config.yaml`/JSON.

**Page 4 – 📊 Results**
- *Common (first-stage) decisions*: unit commitment heatmap (units × hours, on/off & operating state), start-ups/shut-downs markers. Clearly labelled **"common to all scenarios"**.
- *Scenario schedules*: dispatch per unit per scenario (selector + small multiples), expected value overlay, battery/hybrid SOC and charge/discharge, load shedding per scenario.
- *Reserves*: required vs. provided (primary/secondary/tertiary), headroom/footroom per unit.
- *Costs*: waterfall or stacked bar of the expected objective; per-scenario cost table weighted by probability.
- *Constraint health*: table of binding/violated constraints and slacks.
- Every table downloadable (CSV/Excel); every chart exportable (PNG via Plotly).

**Page 5 – 🔁 Compare runs (optional, nice-to-have)**
- Keep a history of runs (inputs + parameters + results in `runs/<timestamp>/`), select two to compare KPIs and dispatch side by side; deterministic vs. stochastic comparison (VSS / EVPI if available).

**Page 6 – ❓ Help**
- Short "How to use" in 5 steps, glossary (RDAS, DS, scenario, nonanticipativity, recourse, reserve types, load shedding), and the meaning of each status.

## Behaviour & engineering requirements

- Run the solver in a way that doesn't freeze the UI (show a spinner; stream solver log into an expander).
- Cache loaded inputs with `st.cache_data`; keep state in `st.session_state`.
- Validate inputs before solving and show human-readable errors pointing to the exact unit/field.
- Handle infeasible / time-limit results gracefully (show what is available + suggestions).
- Code structure:
  ```
  gui/
    app.py              # entry, sidebar, navigation
    pages/              # one file per page
    components/         # kpi cards, charts, tables
    adapter.py          # load inputs, run model, parse results -> pandas
    theme.py            # colours, unit-type palette, plot template
  .streamlit/config.toml
  requirements_gui.txt
  ```
- Type hints, docstrings and comments in English; small focused functions.
- Add a `README_GUI.md` with install & run instructions for Windows (venv).

## Deliverables & working style

1. First: the project summary from Step 0 and a short plan. Wait for my OK.
2. Then build incrementally: adapter → Overview → Inputs → Parameters → Results → Compare/Help. After each step tell me how to run and what to check.
3. Test with the existing sample input in the repo; if none exists, create a small synthetic case (3 thermal units, 1 PV, 1 hybrid with battery, 3 scenarios).
4. At the end, list known limitations and possible improvements.
