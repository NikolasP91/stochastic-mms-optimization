# Stochastic implementation review — 12 October 2026

The implementation is a two-stage extensive-form MILP with shared commitment,
operating states, transitions, reserve procurement and optional reference power.
Its conditional dispatch, activation and storage decisions use the complete
scenario path. The architecture and probability-weighted objective are suitable
for a research study under that information assumption. The review found
correctness and traceability gaps; the changes below address the reproduced
defects and strengthen the study workflow.

This is a hardened research implementation. Deployment still needs calibrated
joint forecast scenarios, asset-specific data and contractual rules, and
validation against actual operating records. Passing the tests is evidence for
the tested behavior, not certification of every possible dataset.

## Review scope and changes

| Finding | Consequence before the review | Implemented correction and evidence |
| --- | --- | --- |
| Reserve eligibility — high | A unit with no reserve-eligible operating state could receive reserve because the inherited eligibility loop added no bounds. | In bounded mode, enabled reserve capacities of such a unit are fixed to zero. A forced positive reserve now makes the model infeasible. Legacy regression retains the original algebra. |
| Shared ramp capability — high | Several simultaneous reserve products could each consume the full ramp capability independently. Three 1 MW products with a one-minute deadline were accepted on a 1 MW/min unit. | With reserve linkage enabled, every distinct deadline limits the sum of all products due by that deadline. Tests cover up/down directions, equal and different deadlines, and the disabled linkage branch. |
| Rolling technical definitions — high | A refreshed graph could be overwritten with old transitions; some remaining maximum dwell obligations could be lost across repeated updates. | Compare immutable operating definitions; reject incompatible changes. Carry minimum/maximum obligations and transient-embedded transition metadata, require complete committed prefixes, and validate observed paths. |
| Input contracts — medium/high | Malformed shapes, ignored options, boolean numbers, fractional integer fields and nonfinite values could reach construction or silently change meaning. | Explicit path-specific validation, strict stochastic options and synchronized JSON schema; 90 additional input-validation cases. Unsupported timers on retained operating states are rejected in bounded mode. Supported transient embedding and transition A/B timing remain available. |
| Fixed-plan evaluation — high | A partial schedule could let the evaluator optimize missing first-stage decisions and overstate performance. | Held-out evaluation requires exactly the complete common schedule and validates the training input. Path overlaps are reported; independence still requires external provenance. |
| Solution audit — high | Missing/NaN solution values could evade ordinary comparison checks. | Reject missing/nonfinite variables, residuals and objective values; retain bound/integrality checks. Independently reconcile expected cost plus weighted empirical CVaR with the solver objective. |
| Very small CVaR tails — medium | An early numerical cutoff could discard a legitimate tiny tail probability. | Accumulate the full requested tail mass; directly test a tail smaller than 1e-12. |
| Interpretation and errors — medium | Mathematical feasibility could be confused with uninterrupted service; infeasibility handling depended on matching exception text. | Separate solver status, residual validation and operational status. Typed errors distinguish proven infeasibility, unavailable/failed solver and invalid results. Nonoptimal incumbents remain unacceptable as benchmark optima. |
| Reproducibility — medium | A reused output path could lose the exact inputs/settings of an earlier run. | Unique run folders, atomic JSON replacement, preserved prior snapshots, source/input/result hashes and environment/solver metadata. Failed attempts have a separate manifest and diagnostic; a failed rerun preserves the prior successful result. |

## Mathematical effect

For each enabled response deadline τ and direction d, the additional reserve
constraint is

```text
sum(r[g,t,j,d] for products j with response_minutes[j] <= τ)
    <= ramp[g,d] * τ / 1000
```

The factor 1000 converts the inherited kW/min ramp input to MW. This supplements
the original individual-product and power-headroom constraints. A unit with no
eligible operational state has zero reserve in bounded mode. These corrections
can reduce the feasible set on previously invalid cases.

The review adds no economic objective terms and no optimization decision
variables. The objective remains expected total scenario cost plus the
configured weight times CVaR of total cost. RP/EEV/WS comparisons explicitly
use zero CVaR weight and check `WS <= RP <= EEV` within numerical tolerance.
Infeasible EEV remains explicit rather than being relaxed into a finite score.

## Verification performed

The full suite passed **231 tests and 36 subtests** on Python 3.13.7,
PuLP 3.3.0 and HiGHS 1.15.1. This includes the 90 pre-review tests plus
141 new tests: 90 validation, 23 rolling, 5 reserve-response and 23 audit,
evaluation and artifact tests. The final full run took 46.04 seconds.

The original one-scenario legacy fixture still has **5,191 variables and
12,032 constraints**, with objective **382,562.14962105255 EUR**. The known
objective regression tolerance is 1e-3 EUR. Original deterministic tests remain
in the suite; the original source directory was not edited.

| Four-hour synthetic study | EUR |
| --- | ---: |
| Stochastic optimum RP | 25,622.614735 |
| Evaluated mean-data plan EEV | 28,730.294028 |
| Perfect-information lower bound WS | 25,620.512004 |
| VSS = EEV − RP | 3,107.679293 |
| EVPI = RP − WS | 2.102731 |

CBC also returned an audited optimum, 25,622.615757 EUR, about 0.001022 EUR
above the HiGHS result at reported precision. The storage/CVaR example has
expected cost 20,556.830622 EUR and risk-adjusted objective 22,613.379293 EUR;
it is a separate demand instance, so this is not a storage-savings comparison.

On five held-out synthetic paths, expected costs are 36,282.863963 EUR for the
stochastic plan and 37,225.362757 EUR for the deterministic plan. Both are
`degraded`: expected unmet demand is approximately 0.357727 and 0.451978 MWh,
respectively, and both have reserve shortfalls. These small synthetic studies
do not establish statistical performance or real-system reliability.

Machine-readable evidence, input/source hashes and solve audits are in
[verification_report.json](verification_report.json). The CBC CLI run is in
`runs/review_cbc.json` and its referenced artifact directory.

## Reproduce and interpret a run

From the project directory in PowerShell:

```powershell
.\.venv\Scripts\python.exe stochastic_main.py examples/small_stochastic.json --validate-only
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe tools/verify_examples.py
.\.venv\Scripts\python.exe stochastic_main.py examples/small_stochastic.json --compare --evaluation-scenarios examples/held_out_scenarios.json -o runs/comparison.json
.\.venv\Scripts\python.exe stochastic_main.py examples/small_storage_cvar.json -o runs/storage_cvar.json
```

An input JSON is mandatory. `--validate-only` checks data contracts; it does
not prove model feasibility. Exit code 0 means the requested operation completed;
handled input, filesystem or optimization errors return 2. Argparse also uses
2 for invalid command syntax. A failed optimization does not publish a new
successful result; any existing output may belong to an earlier run. Consult
the unique run manifest and `<output stem>.error.json` diagnostic.

Successful output identifies `artifact_directory`. That folder preserves the
input JSON, optional held-out scenarios, result JSON and manifest. Each run
gets its own directory, so later failures do not change earlier snapshots.
Hashes establish identity of recorded files/data; they do not guarantee
bit-for-bit solver results across platforms or library versions.

Check `validation.passed`, `operational_status`, each scenario's
`nonzero_slacks`, and `expected_metrics` together. `no_reported_violations`
means no slack exceeded the reporting threshold; it is not a reliability
certificate. A solver time limit never converts an unproven incumbent into an
optimal RP/EEV/WS result. No infeasibility relaxation or IIS report is invented.

## Remaining model boundaries

- Full-path recourse assumes the complete path is revealed before recourse.
  Rolling updates do not add multistage nonanticipativity for dispatch/storage.
- Reserve constraints retain the inherited headroom around actual dispatch
  as well as new reference-power bounds. This is deliberately conservative.
- Storage is aggregate and provides no reserve. Station export limits,
  charging permissions and contracts need an asset-specific extension.
- Legacy regression intentionally preserves known baseline conventions,
  including the wind forecast inconsistency in the supplied fixture. Use
  bounded mode for new studies and calibrate permitted slack caps.
- Renewable priority is an inherited weighted objective. Tariffs, hard-coded
  online costs and penalty magnitudes require study-specific calibration.
- Synthetic scenarios need replacement with calibrated joint forecast-error
  paths and independently documented held-out data. Larger production-scale
  scenarios and rolling backtests have not been certified by this review.

The revised English comparison and its Greek translation describe the same
version 1.1 behavior, preserve editable equations, and include the review
changes. Their XML structure and text/numeric correspondence are checked by
the translation tool; visual Word pagination has not been rendered here.
