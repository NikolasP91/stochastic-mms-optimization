# Dispatch Scheduling Model Notes

This project builds a deterministic mixed-integer linear optimization model for
dispatch scheduling / unit commitment with thermal units, RES/PV units, reserve
requirements, operating-state logic, ramping, availability limits, and
high-penalty relaxation variables.

## Governing Requirement Sources

Future model, input, output, and validation changes should be checked against
the following local PDF sources before implementation:

- `512811 ΔΙΑΚΗΡΥΞΗ - ΚΗΜΔΗΣ (2) -w_o comments.pdf`
- `κώδικας-διαχείρισης-μδν-4η-έκδοση-3ος-2022.pdf`

The tender document and the MDN management code are treated as governing
requirements for the rest of development. When a change touches dispatch
scheduling rules, reserve sizing/provision, operating states, data interfaces,
reports, or validation checks, cite or summarize the relevant PDF requirement in
the associated notes, tests, or commit message.

Accepted near-term additions are tracked in
`docs/requirements_traceability.md` and `docs/development_roadmap.md`. Real-Time
Dispatch (RTD) is explicitly excluded from this project and should not be
implemented.

## Current Strengths

- MILP structure with binary commitment/state variables and continuous dispatch.
- Explicit startup/shutdown, min/max generation, ramping, reserve, and RES/PV
  dispatch constraints.
- High-cost relaxation variables for diagnosing infeasibility instead of failing
  without a useful solution trace.
- Native HiGHS solver support through PuLP/highspy.
- Automatic post-solve validation through `solution_validation.py`.
- Reduced binary footprint in the reserve and operating-state transition
  formulation.
- MMS-style post-solve reports for dispatch instructions, reserve monitoring,
  and RES/PV curtailment.
- Structured warning and diagnostics reports for validation failures, reserve
  shortfalls, nonzero relaxation/slack values, and non-optimal solver status.
- Run-level and pipeline-level performance profiling in the output and artifact
  set.

## Model Package Layout

The active optimization algebra has been modularized under `mms/model/`:

- `preprocessing.py`: unit-order preservation, unit category construction, and
  time-granularity conversion used before model construction.
- `problem.py`: top-level PuLP problem assembly, objective assembly, MPS export,
  solver selection, and solve metadata.
- `core.py`: global decision variables, min/max handling, RES aggregation, load
  balance, and commitment startup/shutdown consistency.
- `thermal_constraints.py`: thermal-unit ramping, must-run, forbidden-zone,
  availability, testing-mode, OOS-mode, and variable-cost-curve constraints.
- `operating_states.py`: operating-state power levels, allowed transitions,
  minimum transition timing, and online/offline state-duration logic.
- `reserves.py`: primary, secondary, and tertiary active-power reserve algebra.
- `res_dispatch.py`: RES/PV dispatch, setpoint, grid-capacity, and curtailment
  variables.
- `bounds.py`: local bound helpers used to replace broad big-M constants where
  constraint-specific limits are available.
- `time_resolution.py`: RDAS/DS time-resolution preprocessing, including
  sub-period operating-state classification, transient-state embedding, and
  timing-resolution audit reporting.

The active workflow is now split across:

- `mms/pipeline.py`: optimization workflow orchestration from prepared input to
  output JSON payload.
- `mms/postsolve.py`: solution-variable parsing, setpoint reconstruction,
  violation summaries, and legacy output JSON assembly.
- `RV_genericMmsOptimization.py`: compatibility facade for older imports only.
- `mms/cost_curves.py`: thermal production-cost curve audit utilities.
- `mms/penalties.py`: soft-constraint penalty hierarchy audit utilities.
- `mms/objective.py`: post-solve objective component reconstruction.
- `mms/slacks.py`: priced soft-constraint slack normalization and penalty
  reporting.

New algebra should be added to the appropriate `mms/model/` module, and new
post-solve/output behavior should be added under `mms/postsolve.py` or
`mms/reports.py` rather than re-expanding the compatibility facade.

## Automatic Validation Checks

The runner now validates the input before building the optimization model and
validates the output after solution.

Input validation checks include:

- Required top-level JSON sections.
- Load horizon consistency.
- Required generating-unit fields.
- Thermal/conventional production-cost curve shape and numeric consistency.
- Soft-constraint penalty hierarchy and numeric consistency.
- Forecast and availability array lengths.
- Nonnegative physical limits and reserve capacities.
- Unique `gen_id` values, with a warning when IDs are not contiguous.
- Solver, time-limit, and big-M parameter validity.

The repository also contains a high-level JSON Schema at
`schemas/input_schema.json` for documentation and tool integration.

Post-solve validation checks include:

- Solver status is `Optimal` unless `require_optimal` is disabled.
- Output unit count matches input unit count.
- Per-period arrays have the expected length.
- Load balance is respected after reported load curtailment.
- Reported load curtailment is zero within tolerance.
- Dispatch does not exceed input availability.
- Units do not produce power while reported off.
- State, startup, and shutdown outputs are binary within tolerance.
- Startup and shutdown outputs match consecutive state changes.
- Reserve arrays have the expected shape and are nonnegative.
- Reserve outputs do not exceed unit reserve capability.
- Reported APR violation arrays are zero within tolerance.

The validation report is embedded under the `Validation` key in the output JSON.

## Diagnostics And Warnings

The runner now builds structured warning and diagnostics payloads after every
successful solve, and writes a diagnostics report on input-validation or
optimization failures.

`Warning_Report` records:

- Nonzero load curtailment / augmentation.
- Nonzero APR violation slack fields.
- Reserve-monitoring shortfalls by reserve type, direction, and period.
- Failed validation checks with their severity.
- Thermal cost-curve generation/audit issues and penalty hierarchy issues.

`Diagnostics_Report` summarizes:

- Solver and validation status.
- Validation and solve issues, including non-optimal solver statuses such as
  infeasible or unbounded outcomes.
- Maximum load-curtailment and APR slack magnitudes.
- RES/PV curtailment totals.
- Model size, objective, big-M value, and the slowest constraint build sections.
- Thermal cost-curve and penalty hierarchy audit summaries.
- Nonzero soft-constraint slack counts and their total penalty cost.

These reports are intended to make infeasible or degraded runs auditable without
requiring manual parsing of the console log.

## Thermal Cost Curves

Thermal/conventional units use an active incremental piecewise-linear production
cost formulation. The current input field is:

```json
"var_gen_cost(euro/MW)": [
  [p0, p1, p2, "..."],
  [base_cost_at_p0, marginal_cost_segment_1, marginal_cost_segment_2, "..."]
]
```

For an online unit, the model enforces:

- dispatch equals the first breakpoint plus the sum of incremental segment
  variables;
- the objective includes the base cost at the first breakpoint plus marginal
  segment costs for the dispatched increments.

The implementation chooses the formulation from the supplied slopes:

- If marginal segment costs are nondecreasing, the curve is convex and the model
  uses only continuous incremental segment variables with
  `0 <= delta_s <= segment_width_s * state`. In a cost-minimizing model, the
  optimizer naturally fills cheaper segments first, so extra binaries are not
  needed.
- If marginal segment costs decrease, the curve is nonconvex and the model uses
  ordered-fill binary variables. A later segment can be used only after all
  previous segments are full. This preserves the intended PWL shape but is
  computationally heavier.

This is a PWL representation that can approximate a quadratic fuel/cost curve
when the input breakpoints and marginal segment costs were derived from such a
quadratic. A thermal unit may optionally provide:

```json
"quadratic_cost_coefficients": {"a": 0.0, "b": 0.0, "c": 0.0},
"cost_curve_generation": {"segments": 3}
```

When `var_gen_cost(euro/MW)` is missing, `main.py` can generate it before
validation by using equal-width breakpoints from `min_power(MW)` to
`max_power(MW)` and secant slopes between adjacent breakpoints. This preserves
the quadratic cost exactly at the breakpoints. Existing manual PWL curves are
left unchanged unless `replace_existing` is enabled. The generation report is
embedded as `Thermal_Cost_Curve_Generation` and written to
`runs/latest/thermal_cost_curve_generation.json`.

Units may also provide provenance metadata:

```json
"cost_curve_source": {
  "type": "manual_pwl",
  "reference": "...",
  "currency": "EUR",
  "basis": "euro_per_mw_per_minute",
  "method": "incremental_breakpoints_and_marginal_slopes"
}
```

`Thermal_Cost_Curve_Audit` checks:

- every thermal unit has numeric `[breakpoints, coefficients]` data;
- breakpoint and coefficient lengths match;
- breakpoints are strictly increasing;
- coefficients are nonnegative;
- marginal segment costs are nondecreasing, as expected for a convex quadratic
  cost approximation;
- the first breakpoint matches minimum power;
- the last breakpoint covers declared `max_power(MW)`, because the cost curve is
  unit data and should span the full technical dispatch range;
- the last breakpoint also covers the maximum input availability for the current
  scenario, so the active model cannot dispatch beyond the priced curve.

The audit is embedded in `optimization_output.json` and written separately as
`runs/latest/thermal_cost_curve_audit.json`.

`Thermal_Cost_Report` reconstructs the solved base cost, segment dispatch,
segment cost, total thermal cost, and any unpriced MW by unit and period. It is
written separately as `runs/latest/thermal_cost_report.json`.

## Penalty And Objective Audits

`Penalty_Hierarchy_Audit` checks the soft-constraint penalty weights in
`Cost_parameters`. It verifies that active penalty coefficients are positive and
that the intended priority order is not inverted, for example:

- load-balance slack should not be cheaper than reserve-shortfall slack;
- primary reserve shortfall should not be cheaper than secondary or tertiary
  reserve shortfall in the same direction;
- operational feasibility slacks such as ramp, forbidden-zone, OOS/testing, and
  grid-capacity relaxations should be priced at least as strongly as the
  strongest reserve shortfall;
- RES/PV forecast-deviation penalties should not make load slack attractive.

The audit allows asymmetric upward/downward reserve penalties, because that can
be a deliberate operational choice.

`Objective_Breakdown_Report` reconstructs observable objective components from
the solved output:

- thermal variable cost;
- startup, shutdown, online commitment, and operating-state costs;
- reserve capacity costs and reserve-shortfall penalties;
- load-curtailment penalties;
- RES/PV tracking penalties and setpoint reward terms.
- additional priced soft-constraint slacks from `Slack_Penalty_Report`.

The post-solve JSON exports `Setpoints` for both RES and PV units when RES/PV
dispatch variables are active, because the objective reward term is applied to
both `RES_SP` and `PV_SP` units in the MIP.

`Slack_Penalty_Report` exports nonzero priced soft-constraint slacks in a common
format with slack family, source variable, unit index when applicable, period,
slack value, penalty coefficient key, and euro contribution. It currently covers
load, reserve-shortage, ramp, grid-capacity, forbidden-zone, must-run,
operating-state transition, optional operating-state minimum/maximum dwell-time,
state transition, testing-mode, OOS-mode, and RES/PV forecast-tracking slacks.
The objective report includes an
`unreconstructed_or_rounding_residual` component equal to the solver objective
minus reconstructed components, so any remaining hidden objective mass remains
visible.

Cost-curve time scaling is explicit through
`optimization_parameters.cost_curve_time_unit`:

- `euro_per_mw_per_minute`: legacy/current project convention, multiplying by
  `Time_granularity`;
- `euro_per_mwh`: academic market-style convention, multiplying by
  `Time_granularity / 60`;
- `euro_per_dispatch_period`: coefficients already apply to one dispatch
  period.

Run the validation unit tests with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Numerical Settings

The JSON file supports:

```json
"optimization_parameters": {
  "solver": "highs",
  "require_optimal": true,
  "big_m": "auto",
  "cost_curve_time_unit": "euro_per_mw_per_minute",
  "highs_options": {
    "user_objective_scale": -4
  },
  "early_stopping": {
    "time_limit": null
  }
}
```

`user_objective_scale` is a HiGHS option used to improve numerical conditioning
when the objective has very large penalty coefficients.

`big_m` can be a number or `"auto"`. In automatic mode the code estimates a
scenario-scaled value from load, availability, reserve, operating-state, and
transition-cost magnitudes. This is tighter than a fixed global constant while
still allowing explicit override when a larger instance needs it.

The model assigns stable names to anonymous PuLP constraints by build section
before the MPS file is written, for example `mms_load_balance_000001`. The solve
metadata also records the number of constraints and variables added by each
section. This improves MPS inspection and makes solver diagnostics less opaque
than default `_C1234` names.

Generating units are kept in the model even when their availability is zero
throughout the modeled horizon. Earlier filtering created a fragile mismatch
between `gen_id` values and list positions. The active model keeps the original
unit order and lets the period-by-period availability constraints enforce zero
available power.

## Formulation Tightening

The operating-state transition cost formulation now uses explicit transition arc
variables instead of big-M indicator-cost constraints. Each arc is tied to the
previous and current operating-state binaries and carries its own transition
cost in the objective. This is closer to a standard network-flow-style unit
commitment transition formulation and removes a source of weak big-M relaxation.

The final active timing formulation uses one unit state-level family and three
operating-state transition families:

- `state_min_time_constraint` uses `state-transitions[].transitions.min-transition-time`
  and `min-transition-time-left` to enforce minimum online/offline time through
  startup/shutdown variables.
- `operating_states_min_transition_time_between_states_constraint_a` uses
  `min-transition-time_a` and `min-transition-time-left_a` on an allowed
  operating-state transition to prevent leaving source state A too soon. Slack
  is charged per remaining protected period after an early departure, so leaving
  with five periods still owed creates five A-side slack periods rather than
  one transition-event slack.
- `operating_states_min_transition_time_between_states_constraint_b` uses
  `min-transition-time_b` and `min-transition-time-left_b` to require the
  destination state B to persist after a specific A -> B transition.
- `operating_states_max_transition_time_between_states_constraint_b` uses
  `max-transition-time_b` and `max-transition-time-left_b` to cap the stay in
  destination state B after a specific A -> B transition. Slack is charged per
  excess period in the continuous destination-state stay.

Do not use A-style maximum transition timing fields
(`max-transition-time_a`, `max-transition-time-left_a`); they are intentionally
unsupported and validation warns that they are ignored. New input files should
express operating-state timing through the transition-specific A/B fields above;
the older generic operating-state dwell helpers have been removed from the
active model module.

RDAS/DS timing is period-indexed. A short operating-state duration such as 5 or
25 minutes cannot be exactly represented by an hourly binary state variable. The
model therefore separates timing data into:

- period-level states, which remain ordinary `u_2[unit, period, state]`
  decisions;
- explicitly marked sub-period transient states, which can be embedded into
  allowed transition arcs before the hourly MIP is built.

The implementation is conservative and data-driven. A state is eligible for
embedding only when it is explicitly marked as transient and all positive timing
values that belong to that state are shorter than `Time_granularity`. For a
candidate state `T`, the relevant transition timers are B-side fields on arcs
entering `T` and A-side fields on arcs leaving `T`. A-side timing from the
predecessor arc and B-side timing from the successor arc are preserved on the
new direct arc because they still belong to explicit endpoint states. Use
`isTransient: true` or `isTransient: false` in each operating state as the
authoritative input switch. When `isTransient` is omitted, the legacy markers
`time_resolution_class: "transient"` or transient `state_role` values such as
`synchronization` and `desynchronization` are still accepted. Initial, shutdown,
and operational states are not embedded unless explicitly allowed through
`optimization_parameters.time_resolution`, because removing those states can
change commitment, reserve, or offline semantics. Non-embedded sub-period timing
data are reported in `Time_Resolution_Report` so the run remains auditable.
If a candidate path `A -> T -> B` would collide with an already declared direct
`A -> B` transition, the transient state is kept explicit and the report records
`transient_state_duplicate_direct_arc`. This avoids silently merging two
different transition paths.

The bypass strategy is selected in the input JSON through:

```json
"optimization_parameters": {
  "time_resolution": {
    "subperiod_operating_state_policy": "embed_transient"
  }
}
```

Use `"embed_transient"` to allow eligible transient states to be embedded into
transition arcs. Use `"period_rounding"` to keep all operating states explicit
and only round their timing data to dispatch-period counts.

Minimum timing values are rounded up to dispatch periods. Maximum timing values
are rounded down to dispatch periods. This avoids the previous unsafe behavior
where a 5-minute maximum stay could become an allowed full-hour stay in an
hourly RDAS/DS model. The academic reason is the same one emphasized by
time-adaptive and continuous-time UC literature: fixed hourly UC variables do not
capture intra-hour startup/shutdown/ramping trajectories exactly. Supporting
references include:

- Pineda, Fernandez-Blanco, and Morales, "Time-Adaptive Unit Commitment",
  2018, https://arxiv.org/abs/1810.00206.
- Rajabdorri, Lobato, Sigrist, and Aghaei, "Data-Driven Continuous-Time
  Framework for Frequency-Constrained Unit Commitment", 2024,
  https://arxiv.org/abs/2312.11387.
- Hreinsson, Analui, and Scaglione, "Continuous Time Multi-stage Stochastic
  Reserve and Unit Commitment", 2018, https://arxiv.org/abs/1803.07115.
- Pan and Guan, "Convex Hulls for the Unit Commitment Polytope", 2017,
  https://arxiv.org/abs/1701.08943.

Thermal/conventional desynchronization is represented as a separate connected
but non-operational operating state. In the biomass test case this state uses
`state_role: "desynchronization"`, `isShutdown: false`, `isOperational: false`,
and the same active-power band as operating state `3`. This keeps the unit
globally online while it ramps down and produces within the desynchronization
band, but excludes it from reserve-capability calculations because reserve
constraints only use `isOperational: true` operating states. The shutdown arc is
therefore modeled as full operation -> desynchronization -> offline, so global
shutdown costs are triggered only when the unit finally reaches an
`isShutdown: true` state.

Reserve requirement maxima are represented as lower envelopes: the APRR variable
is constrained to be at least every active reserve-sizing expression. Because
APRR is linked by equality to reserve provision plus shortage slack, and both
provision and slack are costed, the optimizer drives APRR to the active maximum
without extra max-selection binaries.

The largest-online-unit and largest-two-online-units terms used in reserve
sizing are now modeled with continuous capacity envelope variables rather than
the former `N_1` / `N_2` binary selector formulation. This removes selector
binaries and big-M comparison constraints while preserving the reserve-sizing
quantities needed by the current deterministic case.

Several remaining broad big-M bounds have also been tightened with local
constraint-specific bounds:

- Reserve activation upper bounds use the applicable reserve capability,
  availability, and selected operating-state limits.
- Forbidden-zone disjunctions use a local zone/availability bound, capped by the
  configured global big-M value.

Some RES/PV setpoint-selector and reserve disjunctive constraints still use the
global big-M where endogenous relaxed quantities still need a more careful
reformulation before tightening. The active DS RES/PV dispatch path now applies
period-specific local bounds for grid-capacity min selectors, positive-part
setpoint capacity, RES/PV forecast/setpoint min selectors, and the
minimum-power threshold selector. The `s_Grid_Capacity_2` and RES/PV
`s_power_minus` relaxations also receive local upper bounds derived from the
same physical availability/forecast limits.

## Reproducibility Artifacts

By default, `main.py` writes run artifacts to `runs/latest`:

- `input_snapshot.json` with the raw JSON loaded from disk before preprocessing
- `preprocessed_mip_input.json` with transient-state decisions and timing
  conversion applied before MIP construction
- `output_snapshot.json`
- `output_through_solution_status.json`
- `run_metadata.json`
- `solve_metadata.json`
- `validation_report.json`
- `example_model.mps`
- `dispatch_instructions.json`
- `reserve_monitoring_report.json`
- `res_curtailment_report.json`
- `thermal_cost_curve_audit.json`
- `thermal_cost_curve_generation.json`
- `thermal_cost_report.json`
- `penalty_hierarchy_audit.json`
- `objective_breakdown_report.json`
- `slack_penalty_report.json`
- `time_resolution_report.json`
- `warning_report.json`
- `diagnostics_report.json`
- `performance_profile.json`
- `run_events.jsonl`
- `run_log.txt`
- `solver_log.txt`

These are ignored by git because they are generated per run.

The output JSON includes:

- `Solve_Metadata`: objective, solver, big-M value, model size, constraint
  section statistics, and solve time.
- `Run_Metadata`: input hash, git commit, git dirty flag, Python version,
  platform, and package versions.
- `Dispatch_Instructions`, `Reserve_Monitoring_Report`, and
  `RES_Curtailment_Report`: MMS-style DS evidence derived from the solved
  schedule. These are also written as separate artifacts under `runs/latest`.
- `Warning_Report` and `Diagnostics_Report`: structured run health evidence.
- `Thermal_Cost_Curve_Audit`: thermal PWL cost-curve structure, segment slopes,
  cost-at-breakpoint reconstruction, and warnings/errors for nonconvex or
  malformed curves.
- `Thermal_Cost_Curve_Generation`: generated PWL curves derived from optional
  quadratic coefficients.
- `Thermal_Cost_Report`: solved thermal base cost, segment dispatch, segment
  cost, total cost, and unpriced MW by unit and period.
- `Penalty_Hierarchy_Audit`: soft-constraint penalty priority checks.
- `Objective_Breakdown_Report`: reconstructed objective components and residual
  against the solver objective.
- `Slack_Penalty_Report`: nonzero priced soft-constraint slacks and their euro
  contribution by family.
- `Performance_Profile`: total runtime plus stage timings for input loading,
  validation, model build/solve, post-solve reports, diagnostics, output, and
  artifact writing.

The plain text run log mirrors Python/application console output. The native
HiGHS solver log is written separately when HiGHS is used. The JSONL event log
records structured milestones such as run start, validation, optimization
completion, and artifact writing.

## Benchmark Fixtures

`benchmarks/known_answer_cases.json` contains small hand-checkable validation
and reporting cases. They cover exact load balance, RES curtailment accounting,
reserve shortfall diagnostics, commitment transition instructions, and
zero-availability unit handling. They are intentionally tiny, so they can run quickly
in unit tests and catch regressions in the accounting logic.

`tests/test_full_run_regression.py` runs the accepted biomass case through
`main.py` and checks the known objective value, solver status, validation
status, model size, and artifact set. This is slower than the small fixtures,
but it protects the full DS execution path.

## Research-Grade Improvements Still To Do

- Continue replacing broad big-M constants with constraint-specific tight bounds
  in remaining reserve-disjunction constraints and inactive legacy RES/PV
  dispatch paths.
- Add additional full optimization benchmark cases with known optimal schedules
  and objective values.
- Add equation-level documentation for each constraint family.
- Add deeper tests that compare ramping, startup/shutdown timing, minimum
  operating-state transition timing, and online/offline state-duration behavior
  against hand-computed expectations.
- Stochastic renewables, network constraints, and CI were intentionally left out
  of this implementation batch.
