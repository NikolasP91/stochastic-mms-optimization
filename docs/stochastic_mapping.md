# Step 1 — source audit and extension boundary

Source: `C:\Users\nickp\OneDrive\Desktop\MMS\genericMmsOptimization`, copied
into this workspace on 2026-10-12. The source directory is not modified. The
copied deterministic runner and its regression tests remain available.

| Original component | Stochastic treatment | Evidence / qualification |
| --- | --- | --- |
| Unit order, IDs, technical availability | Known, identical in every scenario | `mms/model/preprocessing.py`; require contiguous IDs because algebra indexes lists by ID |
| Commitment, startup, shutdown | First stage, equal across all scenarios | `state`, `startup`, `shutdown` |
| Operating states and transition arcs | First stage, equal across all scenarios | `u_2`, `transition_arc`; preserve actual IDs, flags, graph and transient preprocessing |
| Primary, secondary, tertiary reserve capacity | First stage, equal across scenarios | All six `*_ActPR_*` families; legacy name does **not** mean reserve energy activation |
| Generation, PWL segments, forbidden-zone selectors | Recourse | Dispatch and cost depend on scenario; all original constraints retained |
| Renewable forecasts and load | Scenario inputs | Only decision-period series change; initial conditions remain common |
| Renewable setpoints, grid-capacity calculations | Recourse | Original allocation/reward rules retained in each scenario |
| Reserve requirements, shortages, technical slacks | Scenario dependent | Original sizing formulas and penalties retained; explicit slack policy added |
| Common reference dispatch | Added first stage | Not billed as generated energy; links recourse to purchased reserve |
| Reserve activation | Added recourse | Bounded by capacity and response rate; energy production billed only in actual dispatch |
| Storage / hybrid station | Added extension | No SOC, charge/discharge algebra exists in the inspected original kernel |
| CVaR | Added optional linear formulation | Total scenario cost includes common cost once |
| Rolling handover | Added interface | Observed power/state/SOC plus explicit residual timing; no average dispatch handover |

## Material gaps found before implementation

1. The prompt mentions seven states. The supplied first thermal unit actually
   has six (IDs 0–5), with only ID 5 explicitly labelled `desynchronization`.
   Other IDs are not assigned invented names. State counts remain data driven.
2. The file named BIOMASS currently contains two thermal, one RES and two PV
   units. Its name is not evidence of a biomass operating model. Legacy
   classification uses `comments`; dispatchable biomass must use the thermal
   technical schema and can carry separate technology metadata.
3. `Load_forecast` has 25 entries: index 0 is history, 1–24 are decisions.
   Unit availability/renewable arrays have 24 entries, indexed by `t-1`.
4. Original reserves are capacities, not activated energy. Response times and
   activation costs are absent. They must be explicit extension inputs. The
   extension conservatively requires simultaneous capacity across products;
   it does not infer permission to reuse the same MW across products.
5. Original ramp constraints use MW/min conversion and one priced relaxation;
   they do not implement distinct startup/shutdown ramp rates. Original state
   trajectories and initial power are preserved. No new startup exemption is
   silently introduced.
6. Several original constraints are soft, with unbounded slack variables.
   The extension requires explicit finite caps for permitted slack families;
   unlisted slacks are fixed to zero. This is a deliberate, reported policy
   change; strict equivalence is checked separately using the legacy policy.
7. No storage/hybrid contract, grid-charge entitlement or terminal SOC rule is
   supplied. Storage inputs must declare these. Storage does not provide
   reserves in this first extension. No regulatory entitlement is inferred.
8. The original kernel has transition-specific maximum state dwell but no
   generic maximum continuous ON time. Optional explicit maximum ON and
   elapsed ON history are added separately, not represented as MDN requirements.

## Preservation strategy

Build each deterministic scenario without solving, retain every original
constraint and its objective, and assemble **one** extensive-form MILP with
first-stage equalities. A single-scenario legacy-policy run provides an exact
algebraic regression before optional extension constraints are applied.
Risk-neutral, CVaR, reserve-linked, storage and rolling runs clearly report
their selected policy. Independent deterministic solves are used only for
the wait-and-see benchmark in EVPI, never as the stochastic solution.

The original project's requirement traceability is retained in
`requirements_traceability.md`. Its local PDFs are in `sources/`. New modeling
assumptions are not claims of compliance with the MDN Code.

## Additions of the October 2026 review

| Component | Stochastic treatment | Qualification |
| --- | --- | --- |
| Scenario tree (`scenario_tree`, `tree_path`) | Optional multistage information structure | Dispatch, activation, load shedding, RES tracking and BESS charge/discharge/SOC/mode equal within a node; commitment and reserves stay first stage |
| BESS reserve | Added first stage (`storage_reserve_*`) | Enters the legacy requirement row of every scenario; power headroom and SOC sustainability checked per scenario |
| BESS self-discharge, availability, cycles, connection limit, terminal value / soft target, SOC recovery | Added recourse options | All optional; defaults reproduce the previous storage model |
| Online charge and minute-scaled legacy costs | Unchanged by default; explicit `cost_policy` | Reported in `first_stage_breakdown` |
| Reserve linkage semantics | `reserve_link_mode`, `balancing_deployment` | Default keeps the previous conservative rule |
| RES/PV reserve | Bounded by the scenario resource (bounded mode) | Prevents reserve that the resource cannot deliver |
| Slacks of first-stage-only rows | Attributed to first-stage cost | Values unchanged; reporting corrected |
| Root-node dispatch | `implementable_dispatch` (tree only) | The issuable here-and-now instruction |
