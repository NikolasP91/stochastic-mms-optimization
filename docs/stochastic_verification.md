# Verification record — 2026-10-12

Executed in Python 3.13.7 with PuLP 3.3.0 and HiGHS 1.15.1. Detailed numerical
results and actual package versions are in `verification_report.json`.

| Check | Result |
| --- | --- |
| Original regression suite | 70 tests and 36 subtests passed |
| Original stochastic suite | 20 tests passed |
| Review regression tests | 141 tests passed |
| Combined suite after review | 231 tests and 36 subtests passed |
| Original one-scenario objective | 382562.14962105255 EUR; matches existing expected value within 1e-3 |
| Original one-scenario model size | 5191 variables, 12032 constraints; unchanged |
| In-sample stochastic RP | 25622.614735290634 EUR |
| Evaluated deterministic EEV | 28730.29402836211 EUR |
| Wait-and-see WS | 25620.512004372453 EUR |
| VSS = EEV − RP | 3107.6792930714764 EUR |
| EVPI = RP − WS | 2.102730918180896 EUR |
| HiGHS / CBC smoke runs | Both Optimal and audited; CBC 25622.615757 EUR, about 0.001022 EUR above HiGHS at reported precision |

The [implementation review](implementation_review.md) records reproduced
defects, their corrections and remaining limitations. Added checks cover
cumulative reserve response, ineligible reserve providers, strict input shapes,
repeated rolling obligations, complete fixed schedules, finite solution values,
objective reconciliation, and preservation of prior run artifacts on failure.
The revised reports separate solver optimality from operational shortfalls and
include source/input hashes and environment/solver metadata.

The single-scenario regression also checks identical variable/constraint counts.
The original full CLI regression independently checks its known objective and
legacy output artifacts. New tests directly check balance and reserve linkage,
force contradictory scenario commitments to prove infeasibility under
nonanticipativity, verify CVaR from a discrete tail distribution, and force
storage charging/discharging with efficiencies. Rolling tests cover inherited
minimum time, maximum ON history, maximum state dwell, shifted commitments and
measured SOC. Invalid probabilities, mismatched horizons, impossible renewable
availability and unknown fixed decisions are rejected.

Five separate paths generated with seed 2026 give:

| Metric | Stochastic schedule | Deterministic schedule |
| --- | ---: | ---: |
| Expected objective, EUR | 36282.863963 | 37225.362757 |
| Unserved energy, MWh | 0.357727 | 0.451978 |
| Renewable curtailment, MWh | 0.121803 | 0.187583 |
| Reserve shortage, MW-hours | 0.006934 | 0.023658 |

Both schedules have nonzero permitted shortfalls out of sample. Passing solver
residual validation means the formulated constraints and declared slack caps
are satisfied; it does not mean uninterrupted service. These are toy generated
paths and a two-stage perfect-information recourse evaluation, not a field
reliability claim.

The storage/CVaR example uses a lower first-hour demand to demonstrate active
charging/discharging. It is a separate instance, not a direct cost comparison
with the no-storage example. Terminal energy is constrained to at least initial
energy in each path. Actual dispatch and nonzero-slack reports are saved under
`runs/` by the CLI.

Reproduce:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe tools/verify_examples.py
.\.venv\Scripts\python.exe stochastic_main.py examples/small_stochastic.json --solver cbc -o runs/cbc.json
```

The one-scenario legacy equivalence is deliberately separate from adding
bounded slacks, reserve activation limits, storage, or maximum ON constraints.
Those additions change the feasible set when enabled. Remaining source-data
and modeling limitations are listed in `stochastic_formulation.md`.

## Update after the October 2026 review (2026-10-23)

Same environment (Python 3.13.7, PuLP 3.3.0, HiGHS 1.15.1). Changes and their
rationale are in [REVIEW_CHANGES.md](REVIEW_CHANGES.md).

| Check | Result |
| --- | --- |
| Full suite | **264 tests and 36 subtests passed** (231 previous + 27 review-extension + 6 schema/regression) |
| Original one-scenario regression, now a pytest | 5191 variables, 12032 constraints, 382562.14962105255 EUR (unchanged) |
| Previous example objectives | small_stochastic 25622.614735, small_storage_cvar 22613.379293 (unchanged; defaults reproduce the previous model) |
| Previous VSS/EVPI | 3107.679293 / 2.102731 EUR (unchanged) |
| VSS decomposition (small_stochastic) | commitment only ≈ 0; + reserves 485.39; full 3107.68 EUR |
| Tree + hybrid BESS example RP / EEV / WS | 1660.305093 / 1737.110634 / 1659.837884 EUR |
| Tree example VSS / EVPI | 76.805541 / 0.467209 EUR; no permitted slack used; 2324 variables, 6104 constraints, 120 tree equalities |
| Multistage vs full-path recourse | RP(tree) ≥ RP(full path) asserted by test |
| Schema | every example validates against `schemas/stochastic_extension.schema.json`; field sets match the validator |

The VSS decomposition qualifies the earlier VSS figure: on the four-hour
example the EV commitment equals the stochastic commitment, and the value comes
from reserve awards and reference points under reserve linkage; most of the
EEV excess is load-shedding penalty (about 0.119 MWh at 20000 EUR/MWh). The
absolute costs of the earlier examples are dominated by the legacy online charge
(24000 of 25623 EUR), now reported in `first_stage_breakdown`; the tree example
uses an explicit hourly `cost_policy`.
