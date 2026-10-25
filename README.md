# Stochastic MMS Optimization

Python/PuLP stochastic MILP for the hourly Rolling Day-Ahead Scheduling (RDAS,
ΚΗΕΠ) of a non-interconnected island, built on a local copy of the supplied MMS
Optimization project. The original deterministic `main.py`, constraint modules,
JSON and tests are retained; the source folder on the Desktop is unchanged.

The model is solved as **one** extensive-form MILP. First-stage (day-ahead)
decisions are common to all scenarios: commitment, operating states, transition
arcs, reserve capacity, optional reference output and optional BESS reserve.
Recourse decisions are per scenario: dispatch, reserve activation, storage
charge/discharge/SOC and permitted slacks. Recourse is either:

- **two-stage, full-path** (default): each scenario's recourse sees its whole path; or
- **multistage**: with `scenario_tree`, scenarios sharing a tree node must take
  identical recourse decisions in that node's hours (nonanticipativity), and the
  root-node dispatch is reported as an implementable instruction.

Further features: CVaR, explicit cost policy, two reserve-linkage semantics,
professional BESS options (reserve provision with SOC sustainability,
self-discharge, terminal value or soft target, SOC recovery, cycle limit,
hybrid connection limit, hourly availability), rolling-state handover,
RP/EEV/WS/VSS/EVPI with VSS decomposition, and held-out evaluation.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe stochastic_main.py examples/small_stochastic.json --validate-only
.\.venv\Scripts\python.exe stochastic_main.py examples/small_stochastic.json --compare --evaluation-scenarios examples/held_out_scenarios.json -o runs/comparison.json
.\.venv\Scripts\python.exe stochastic_main.py examples/small_storage_cvar.json -o runs/storage_cvar.json
.\.venv\Scripts\python.exe stochastic_main.py examples/small_tree_bess.json --compare -o runs/tree_bess.json
.\.venv\Scripts\python.exe -m pytest tests -q
```

`--solver highs` is the default; `--solver cbc` is also available. PuLP is pinned
to 3.3.0 to match the inherited code's solver API. `--time-limit SECONDS` is
optional. Nonoptimal or infeasible solves fail explicitly. `--accept-incumbent`
reports a time-limited feasible solution with status `Feasible`; it cannot be
combined with `--compare`, because VSS/EVPI require proven optima.

Always supply the input JSON after `stochastic_main.py`. `--validate-only`
checks structure and cross-field rules (including tree data consistency and
storage terminal reachability) without solving.

Each optimization creates a unique folder under `<output stem>_artifacts/`
(override with `--artifacts-dir`) holding the exact input, optional evaluation
paths, result, and a manifest with SHA-256 hashes. Results record source
hashes, Python/package versions and solver settings. Any failure, including
unexpected internal errors, returns exit code 2, marks the manifest `Failed`
and writes `<output stem>.error.json`; an older result file may remain, so check
the exit code. `--compare` uses zero CVaR weight for VSS/EVPI; when the input
has a nonzero weight, the risk-averse plan is also solved and evaluated.

## Documents

1. [Source audit and deterministic/stochastic mapping](docs/stochastic_mapping.md).
2. [Equations, information timing, assumptions and limitations](docs/stochastic_formulation.md),
   including the "Review extensions" section.
3. Examples: [four-hour two-stage case](examples/small_stochastic.json),
   [storage/CVaR case](examples/small_storage_cvar.json),
   [three-stage tree with hybrid BESS and explicit cost policy](examples/small_tree_bess.json),
   [original one-scenario regression input](examples/original_single_scenario.json).
   Regenerate with `python tools/make_examples.py`.
4. Tests: all original tests, [extension tests](tests/test_stochastic.py),
   [review-extension tests](tests/test_review_extensions.py) and
   [schema/regression tests](tests/test_schema_and_regression.py).
5. [Verification record](docs/stochastic_verification.md) and
   [machine-readable results](docs/verification_report.json)
   (`python tools/verify_examples.py`).
6. [Codex implementation review](docs/implementation_review.md) and
   **[October 2026 review: changes and rationale](docs/REVIEW_CHANGES.md)**.
7. Word comparisons, [English](docs/MMS_Deterministic_vs_Stochastic_Comparison.docx) and
   [Greek](docs/MMS_Deterministic_vs_Stochastic_Comparison_GR.docx)
   (`python tools/build_comparison_document.py`, `python tools/build_greek_comparison_document.py`).
8. Greek textbook chapter on stochastic programming for this RDAS model:
   [Κεφάλαιο_Στοχαστικός_Προγραμματισμός_RDAS.docx](docs/Κεφάλαιο_Στοχαστικός_Προγραμματισμός_RDAS.docx),
   built from `docs/chapter_gr/` with `python tools/build_stochastic_chapter_gr.py`
   (needs `requirements-docs.txt` and Microsoft Office's `MML2OMML.XSL`).

The four-hour examples deliberately use a small synthetic two-state schema and
disable the legacy grid/setpoint algorithm; they are not a simplified
replacement of the original six-state 24-hour regression case.

## Input

Add a `stochastic` object to an existing MMS JSON; see the examples and the
[extension schema](schemas/stochastic_extension.schema.json), which a test keeps
in sync with the runtime validator. Each scenario has an ID, probability,
`load_mw` and `renewables_mw` keyed by legacy unit ID, each with exactly H
hourly decision values (index 0 of `Load_forecast` is history). Probabilities
must sum to one and are never normalized. Unit availability and initial
conditions stay in the original JSON.

For a multistage study add `"scenario_tree": {"stage_start_hours": [1, 7, 13]}`
and a `tree_path` (one node label per stage, common root) to every scenario;
scenarios sharing a node must have identical data in that node's hours.
`mms.stochastic.scenarios.synthetic_tree` builds a seeded demonstration tree.

## Python API and rolling runs

```python
from mms.stochastic.data import load
from mms.stochastic.model import solve
from mms.stochastic.rolling import advance

data = load("examples/small_tree_bess.json")
result = solve(data)
# observations: measured power/state paths and final storage MWh.
# refreshed: the next horizon's complete forecasts and scenarios.
# next_data, fixed = advance(data, result, observations, refreshed,
#                            executed_steps=1, committed_steps=1,
#                            released_units=[])   # e.g. a tripped unit
# next_result = solve(next_data, fixed_first_stage=fixed)
```

Output separates `common_schedule`, `implementable_dispatch` (tree root only),
`scenario_dispatch` (per-scenario costs, slacks with stage attribution,
metrics, variables and a `storage` report with SOC trajectory, cycles and
committed reserve), `expected_metrics`, `first_stage_breakdown`,
`scenario_tree` and CVaR. Scenario-averaged generation is not an operating
schedule. `operational_status` is `degraded` when any reported slack is nonzero;
it is separate from solver status and is not a reliability certificate.

Rolling updates must preserve the operating graph, timing definitions and
maximum-ON configuration. Committed prefixes fix commitment and reserve awards
but not startup/shutdown/transition arcs, which follow from the observed state.

## Implementation boundary

This is a tested research implementation, not a certified operational tool.
Commitment remains first-stage for the whole horizon even with a tree.
Renewable priority uses weighted penalties, not proven lexicographic priority.
The legacy online charge and minute-scaled costs are kept by default for
regression; use `cost_policy` for hourly economics. The hybrid BESS is not a
complete station-contract model (legacy grid-penetration limits still apply to
gross RES output). Synthetic scenarios are toy AR(1) paths, not calibrated
forecasts. No claim of complete MDN regulatory compliance is made.
Source hashes are recorded in `docs/source_manifest.json`; the only change to
the original model assembly remains the optional `build_only` return path.
