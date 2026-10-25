# Development Roadmap

## Accepted Scope

The accepted roadmap items are:

- Requirements traceability against the tender and MDN Code.
- Incremental modularization into MMS-oriented packages.
- Dispatch instruction output.
- Reserve monitoring report.
- RES/PV curtailment report.
- Benchmark and regression cases tied to requirements.

## Explicitly Excluded

Real-Time Dispatch (RTD) is not part of this project. The codebase may mention
RTD only as an external tender concept or as an explicitly unsupported run mode.
It must not add an RTD optimizer, RTD execution loop, AGC base-point engine, or
5-minute real-time redispatch workflow.

Maximum operating-state timing is supported as an optional, data-driven layer:
use the generic max dwell-time constraint for state-level limits and the B-style
max timing constraint for destination-state limits after a transition. These
constraints should remain inactive unless the specific scheduling case requires
finite max-time data.

## Implementation Sequence

1. Keep the current MIP kernel stable while extracting post-solve MMS artifacts.
2. Add modular report builders under `mms/`.
3. Add report artifacts to `runs/latest`.
4. Add tests that prove the artifacts are produced consistently.
5. Continue moving algebra from `RV_genericMmsOptimization.py` into focused
   modules only when each move can be covered by tests and compared against the
   current known case.
6. Move post-solve/output processing into MMS package modules.
7. Add full-run regression checks for the accepted biomass case.
8. Add structured run/event logging while preserving plain text solver logs.

## Modularization Status

The active model-building algebra has been extracted from
`RV_genericMmsOptimization.py` into `mms/model/`. The workflow and post-solve
processing have also been extracted into `mms/pipeline.py` and
`mms/postsolve.py`. The historical script remains as a compatibility facade.
Boundary tests in `tests/test_model_modules.py` protect the public entry point
and preparation helpers, while `tests/test_full_run_regression.py` protects the
known full optimization case.

## Completed High-Value Additions

- Active model algebra, workflow orchestration, post-solve parsing, reports, and
  logging are now separated into MMS-oriented modules.
- The accepted biomass case has a full-run regression guard for solver status,
  objective value, model dimensions, validation status, and artifacts.
- Runs now emit a plain text log and a structured JSONL event log.
