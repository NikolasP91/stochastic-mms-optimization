# Benchmarks

Benchmark fixtures should be small, auditable cases tied to the governing
requirements in `docs/requirements_traceability.md`.

Current benchmark coverage:

- `known_answer_cases.json`: hand-checkable exact-balance, RES-curtailment,
  reserve-shortfall, commitment-transition, and zero-availability unit handling
  checks.
- `tests/test_mms_reports.py`: dispatch instruction, reserve monitoring, and
  RES curtailment report checks.
- `tests/test_full_run_regression.py`: full accepted biomass-case optimization
  regression for solver status, objective value, model size, validation status,
  and artifact creation.

Recommended next benchmark fixtures:

- Additional full optimization cases with known optimal objective values.
- Edge cases for ramp-rate limits and operating-state minimum-time constraints.
- Larger performance benchmark scenarios for comparing solver settings and
  formulation variants.

RTD benchmark cases are intentionally excluded from this project.
