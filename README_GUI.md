# GUI for the Stochastic RDAS / DS Scheduler

A Streamlit + Plotly front end for the stochastic Rolling Day-Ahead Scheduling (RDAS) model of this
repository. It shows the inputs, lets you edit them and the model parameters, runs the solver in the
background and presents first-stage decisions, scenario schedules, reserves, costs and slacks.

The GUI **wraps** the existing programs. It does not change any constraint, bound or objective term:

| Mode | Engine called | Resolution | Uncertainty |
|------|---------------|------------|-------------|
| **RDAS** | `mms.stochastic.model.solve` (or `evaluation.compare` for VSS/EVPI) | 60 min | all scenarios, two-stage or multistage tree |
| **DS** | the deterministic legacy program `main.py` | 15 min | one forecast: a chosen scenario or the expected value |

## Install and run (Windows, PowerShell)

```powershell
cd "D:\projects\Stochastic MMS Optimization"
python -m venv .venv                      # skip if .venv already exists
.\.venv\Scripts\python.exe -m pip install -r requirements_gui.txt
.\.venv\Scripts\python.exe -m streamlit run gui/app.py
```

Run the command from the project root so `.streamlit/config.toml` (dark theme) is picked up.
The browser opens at <http://localhost:8501>.

Tests of the GUI layer (adapter, runner, all pages):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_gui_adapter.py -q -p no:cacheprovider --basetemp .pytest_tmp
```

## Using it

1. **Sidebar** – pick a case (`examples/`, `cases/`, project root, or upload a JSON), choose **RDAS** or
   **DS**, choose the *scenario view* (expected value / all scenarios / one scenario), press
   **▶ Run optimization**. The status badge, elapsed time, live solver log and a *Cancel* button appear while
   the solver works in a separate process; the pages stay usable.
2. **🏠 Overview** – KPI cards (expected cost and its breakdown, scenarios, committed units, expected load
   shedding, RES share, MIP gap, solve time, rows / columns / binaries), expected dispatch vs load and a
   warning panel for every non-zero slack.
3. **📥 Inputs** – editable tables for units, hourly series, operating states, BESS, scenario forecasts,
   probabilities and initial conditions; scenario fan charts and the scenario tree; a synthetic scenario
   generator; *Reset to file*, *Validate inputs*, *Save as new case* (`cases/<name>.json`) and a diff of all edits.
4. **⚙️ Parameters** – solver and time limit, incumbent acceptance, VSS/EVPI, horizon, Big-M, slack policy and
   caps, CVaR, cost policy, penalty weights, reserve requirement coefficients and methods (incl. N-1 / N-2),
   reserve linkage, constraint toggles (MustRun, testing, OOS, RES set-point dispatch …) and BESS economics.
   *Restore defaults* returns to the case-file values; configs are saved to / loaded from `configs/*.json`.
5. **📊 Results** – commitment heatmap with start/stop markers (*common to all scenarios*), reserve awards,
   dispatch per scenario (single, expected or small multiples), BESS SOC and flows, load shedding, reserves
   required vs provided, headroom/footroom, cost waterfall and per-scenario costs, VSS/EVPI, constraint health
   (residual audit, slacks, binding limits) and downloads (CSV per table, Excel workbook, raw JSON; PNG from
   each chart's toolbar).
6. **🔁 Compare runs** – run history from `runs/gui/`, open any past run, compare two runs side by side.
7. **❓ Help** – five-step guide, glossary and status meanings.

## Files

```
gui/
  app.py            entry point: sidebar, navigation
  adapter.py        load / validate / convert inputs, start runs, parse results -> pandas
  runner.py         executed in a child process; calls the engine, writes result/status JSON
  state.py          session state (loaded case, edited copy, solver options, current run)
  theme.py          colours, unit-type palette, Plotly template, CSS
  components/       kpi.py (cards, badges), charts.py (Plotly figures), tables.py (tables, errors)
  pages/            overview, inputs, parameters, results, compare, help
.streamlit/config.toml
requirements_gui.txt
tests/test_gui_adapter.py
```

Each run folder `runs/gui/<timestamp>_<mode>_<case>/` contains `input.json` (exactly what the engine
solved), `request.json` (mode, solver options, parameter snapshot), `solver_log.txt`, `status.json` and
`result.json` or `error.json`. DS runs also keep `case_input.json` (the hourly case) and the legacy
artifacts.

## Assumptions and design decisions

- **DS mode is deterministic.** The stochastic extension accepts only `Time_granularity = 60`
  (`mms/stochastic/data.py`). DS therefore runs the legacy MMS kernel on a 15-min input built from the hourly
  case: the selected scenario (or the probability-weighted expected scenario) becomes the forecast, hourly
  arrays are held constant over the four quarter-hours, minute-based timers are unchanged, and the first
  *N* hours are used (default 4 h = 16 × 15 min). The legacy kernel has no BESS model, so storage is ignored in DS.
- **Solver choice:** the engine supports HiGHS and CBC. Gurobi/CPLEX are listed but disabled.
- **MIP gap and threads are read-only** (0 and 1): `solve()` fixes them so that *Optimal* means proven
  optimal and VSS/EVPI are exact. Changing them would require editing the model code.
- **Observational hooks only:** the runner wraps `pulp.LpProblem.solve` to record rows, columns, binaries and
  the HiGHS MIP gap, and passes `msg=True` to stream the log.
- **Cost breakdown:** first-stage online charge and BESS reserve cost come from the engine's
  `first_stage_breakdown`; start-up / shut-down costs are reconstructed from the common schedule; the
  remainder of the first stage is shown as *reserve capacity, state & transition costs*. The waterfall sums
  exactly to the engine's expected cost.
- **Binding limits** are detected from solution values (unit at upper / minimum limit, ramp-limited moves,
  BESS full / empty). Duals are not available for a MILP.
- **Probabilities are never rescaled silently;** *Normalize to 1* is an explicit button.
- **Colours:** one hue per unit type (thermal orange, biomass green, wind blue, PV yellow, hybrid/BESS violet,
  load shedding red), lighter/darker steps for several units of the same type; scenarios use one blue ramp and
  the expected value is the bold light line.

## Known limitations and possible improvements

- DS is single-forecast; a stochastic 15-min DS would need the extension to accept other resolutions.
- Gurobi/CPLEX, MIP gap and thread settings need small engine changes before the GUI can expose them.
- The MIP gap KPI comes from HiGHS; CBC runs show “0” only when proven optimal.
- Hourly per-state power limits stored as lists are shown but not editable in the operating-state table;
  operating-state transition arcs and forbidden zones are read-only.
- Editing `comments` (which defines the legacy unit category) is disabled on purpose.
- Rolling (closed-loop) RDAS and out-of-sample evaluation are available in the Python API but not yet in the GUI.
- A run started before a browser refresh keeps running and appears in *Compare runs*, but its live log is not
  re-attached to the new session.
- Possible next steps: rolling-horizon page using `mms.stochastic.rolling.advance`, held-out scenario
  evaluation, scenario reduction, map/one-line diagram of the island network, user authentication for
  multi-user deployment.
