# October 2026 review — changes made by Claude

Review and extension of the Codex stochastic RDAS implementation, 22–23 October
2026. Goal: a professional-grade stochastic RDAS with a proper Battery Energy
Storage System (BESS) model, plus a Greek textbook chapter explaining the
formulation. Codex's earlier review is in
[implementation_review.md](implementation_review.md) and is left unchanged.

## 1. Summary

- **Multistage scenario tree (new, optional).** Recourse decisions (dispatch,
  reserve activation, load shedding, RES curtailment, BESS charge/discharge/SOC)
  are now nonanticipative per tree node. This removes the "full-path foresight"
  that made the battery act on information it could not have. The root-node
  decisions are exported as an issuable instruction (`implementable_dispatch`).
- **Professional BESS model (new options).** First-stage BESS reserve provision
  that counts towards the legacy reserve requirement, with power headroom and
  SOC-sustainability checks in every scenario. Also: self-discharge, hourly
  power availability, terminal energy value, soft terminal target with
  reported shortfall, SOC recovery below the operating minimum, cycle limit,
  hybrid connection (export) limit, terminal-target reachability check, and a
  per-scenario storage report.
- **Economics made explicit.** The legacy kernel's hard-coded 6000 EUR per
  online thermal hour (94% of the example objective) and its ×60 minute scaling
  are now reported, and can be replaced through `cost_policy`.
- **Reserve-linkage semantics made explicit.** A new `deploy_from_procured`
  mode implements the standard two-stage reserve-deployment model. Per-product
  `balancing_deployment` keeps FCR out of hourly balancing.
- **Bug fixes.**
  - Rolling handover became infeasible after a failed start or trip.
  - Rolling crashed on a `maximum_on` overrun.
  - RES/PV could sell reserve their scenario resource cannot deliver.
  - HiGHS returned "Not Solved" after any earlier HiGHS run in the same process.
  - Several validation holes, reporting misattributions and CLI error paths.
- **Backward compatible.** With no new options every previous result is
  reproduced exactly: the original 24-h fixture (5191 variables, 12032
  constraints, 382562.15 EUR), both previous example objectives, and VSS/EVPI.
- **Tests.** 264 tests + 36 subtests pass (previously 231).
- **Greek chapter.** A 34-page Word chapter
  ([Κεφάλαιο_Στοχαστικός_Προγραμματισμός_RDAS.docx](Κεφάλαιο_Στοχαστικός_Προγραμματισμός_RDAS.docx)),
  reproducible from source, with native Word equations and code-generated figures.

## 2. How the review was done

Five independent reviewers each examined one dimension:

- core model
- BESS
- rolling/evaluation/CLI
- docs/schema/tests
- interplay with the legacy kernel

They produced 41 findings, and each finding was then handed to a separate
adversarial verifier instructed to refute it and to reproduce it with a
script. 29 were confirmed and 12 partially confirmed; none was refuted, and
several severities were corrected. A design scout mapped the integration
points for the tree and BESS work. Every change below was then implemented
and tested.

## 3. Findings and resolution

Severity is as corrected by the verifier.

| # | Finding | Sev. | Resolution |
| --- | --- | --- | --- |
| 1 | Full-path recourse: BESS and hour-1 dispatch use future information; no issuable BESS instruction | high→medium | **Implemented** optional `scenario_tree` with node-wise nonanticipativity, one-root and equal-data validation, `implementable_dispatch` output |
| 2 | BESS invisible to reserve procurement; battery displaces reserve-capable units | high | **Implemented** first-stage BESS reserve entering every requirement row, with headroom and SOC-duration constraints and first-stage cost |
| 3 | Hard terminal SOC outranks serving load; unreachable target gives a bare "Infeasible" | medium | **Implemented** soft target (`terminal_shortfall_penalty_eur_per_mwh`), terminal value, per-scenario reachability check with a clear message; hard target remains the default and is documented |
| 4 | Measured SOC outside the band stops rolling | medium | **Implemented** clamping of metering noise (≤1e-6 MWh), physical bounds [0, capacity], priced SOC recovery below the operating minimum |
| 5 | No connection limit; `renewable_gen_id` silently ignored with grid charging | medium | **Implemented** `export_limit_mw`; inert `renewable_gen_id` now rejected |
| 6 | No self-discharge, availability, cycle limit; degradation only linear | medium/low | **Implemented** `self_discharge_per_hour`, `power_availability`, `max_cycles_per_horizon`; throughput cost kept and documented |
| 7 | Storage results not reported | medium | **Implemented** per-scenario `storage` report keyed by store ID: SOC, flows, net injection, cycles, costs, committed reserve |
| 8 | Rolling committed prefix fixes startup/shutdown/arc at the new t=1 → infeasible after any deviation | high | **Fixed**: boundary variables are no longer fixed; `released_units` releases a failed/tripped unit; fixed-schedule infeasibility is now diagnosed |
| 9 | Rolling crashes on observed `maximum_on` overrun | medium | **Fixed**: overrun carried when `violation_penalty_eur_per_h` is set (priced recovery), otherwise clamped |
| 10 | `maximum_on` accepts `elapsed_hours=0` for an online unit (allows M+1 hours) | low | **Fixed** in validation |
| 11 | Hard-coded online charge 100×60 EUR/h dominates the objective and changes commitment | high | **Implemented** `cost_policy.thermal_online_charge_eur_per_h`; `first_stage_breakdown` reports the charge; default unchanged for regression |
| 12 | Legacy ×60 scaling of reserve/state/curtailment costs vs EUR/MWh fuel curves; PV curtailment free | medium | **Implemented** `cost_policy.legacy_time_scaled_costs: per_hour` and `renewable_curtailment_eur_per_mwh` (also prices PV); default unchanged |
| 13 | Reserve linkage double-counts headroom (activation needs r+e of room) | medium | **Implemented** `reserve_link_mode: deploy_from_procured` (legacy rows rewritten around the reference); default kept and its exact rule documented |
| 14 | Hourly deviations deployed from primary/FCR | medium | **Implemented** per-product `balancing_deployment` flag |
| 15 | `reserve_link` with no enabled product silently freezes thermal dispatch | medium | **Fixed** in validation |
| 16 | RES/PV reserve bounded by nameplate, not by the scenario resource | medium | **Fixed** (bounded mode): `p + Σr↑ ≤ W_s`, `p − Σr↓ ≥ 0` |
| 17 | Slacks of first-stage-only rows booked as recourse | low | **Fixed** attribution to `first_stage_cost_eur`; slack report has `stage` |
| 18 | Zero-probability paths silently dropped | low | **Fixed**: `EXCLUDED_ZERO_PROBABILITY` note |
| 19 | VSS driven by reserve awards/reference, not commitment; undisclosed | low | **Implemented** `VSS_decomposition` in `compare()`; documented |
| 20 | With `--compare` and CVaR the risk-averse plan is never evaluated | low | **Fixed**: `stochastic_risk_averse` solved and evaluated out of sample |
| 21 | CLI lets unexpected exceptions escape (manifest stays "Running") | low | **Fixed**: catch-all `InternalError` diagnostic, manifest `Failed` |
| 22 | Time limit discards any incumbent | medium | **Implemented** opt-in `accept_incumbent` / `--accept-incumbent` (status `Feasible`, note; refused with `--compare`) |
| 23 | Schema never tested and diverges from the validator | low | **Fixed**: schema rewritten with all fields; tests validate examples and compare field sets |
| 24 | 24-h regression and verification numbers not guarded by pytest | low | **Added** pytest for the 24-h fixture; verification script extended |
| 25 | README duplicated paragraphs and list numbering | low | **Fixed** (README rewritten) |
| 26 | Storage and other branches lacked tests | medium | **Added** 27 tests (see §6) |
| 27 | Synthetic generator rank-one (correlation ±1), no lead-time growth, clipping bias | low | **Documented** (README, formulation, chapter); `synthetic()` kept unchanged so seeded examples stay reproducible |
| 28 | Out-of-sample evaluation is single-shot full-path; no closed-loop simulator | medium | **Partially**: held-out paths with `tree_path` are evaluated under the tree; result states `recourse_information`. A closed-loop rolling simulator is **not** implemented |
| 29 | Hybrid store cannot absorb RES curtailed by the legacy penetration limits (setpoint algorithm) | medium | **Not changed** (needs a station-contract model of the legacy setpoint algebra); documented as a limitation |

Found during this work, not by the reviewers:

- **HiGHS process-wide scheduler.** After any earlier HiGHS run in the same
  Python process (a notebook, or the deterministic and stochastic solvers in
  one session), `solve()` with `threads=1` always ended "Not Solved".
  Fixed by resetting the scheduler before each HiGHS solve; regression test added.
- **Stray reviewer file.** A review agent left `dev_base.json` in the project
  root despite read-only instructions. It was removed; nothing referenced it.

## 4. New input options (all optional)

```json
"stochastic": {
  "scenario_tree": {"stage_start_hours": [1, 2, 3]},
  "scenarios": [{"id": "...", "probability": 0.25, "tree_path": ["root", "s2b0", "s3b0"], "...": "..."}],
  "reserve_link_mode": "deploy_from_procured",
  "reserve_products": {"primary": {"...": "...", "balancing_deployment": false}},
  "cost_policy": {"legacy_time_scaled_costs": "per_hour",
                  "thermal_online_charge_eur_per_h": 100,
                  "renewable_curtailment_eur_per_mwh": 1000},
  "maximum_on": {"0": {"hours": 8, "elapsed_hours": 3, "violation_penalty_eur_per_h": 5000}},
  "storage": [{"...": "existing fields",
               "self_discharge_per_hour": 0.005, "power_availability": [1, 1, 0.5, 1],
               "terminal_value_eur_per_mwh": 45, "terminal_shortfall_penalty_eur_per_mwh": 500,
               "soc_recovery_penalty_eur_per_mwh": 300, "max_cycles_per_horizon": 1.5,
               "export_limit_mw": 6,
               "reserve": {"products": {"primary": ["up", "down"], "secondary": ["up"]},
                           "sustain_minutes": {"primary": 15, "secondary": 30},
                           "capacity_cost_eur_per_mw_h": {"up": 0.5, "down": 0.5}}}]
}
```

Equations are in [stochastic_formulation.md](stochastic_formulation.md), section
"Review extensions". New example: [examples/small_tree_bess.json](../examples/small_tree_bess.json)
(three stages, four leaves, hybrid BESS with reserve, explicit cost policy).

## 5. Output changes (`schema_version` 1.2)

- **New fields:**
  - `first_stage_breakdown`
  - `implementable_dispatch`
  - `scenario_tree`
  - per-scenario `storage` and `tree_path`
  - a `stage` field on each slack-report entry
  - `VSS_decomposition` in `compare()`
  - `stochastic_risk_averse` in CLI comparisons
  - `recourse_information` in out-of-sample evaluation
- **New notes:**
  - `MULTISTAGE_SCENARIO_TREE`
  - `EXCLUDED_ZERO_PROBABILITY`
  - `INCUMBENT_NOT_PROVEN_OPTIMAL`
- **Changed values:**
  - `status` can be `Feasible`, but only with `accept_incumbent`.
  - `first_stage_cost_eur` now includes penalties of first-stage-only slacks and
    BESS reserve cost. Their total is unchanged; only the first-stage/recourse
    split moves.

## 6. Tests

- [tests/test_review_extensions.py](../tests/test_review_extensions.py), 27 tests:
  - tree generator and validation (leaks, root, stage hours)
  - node-wise equality, and RP(tree) ≥ RP(full path)
  - BESS reserve (first stage, requirement rows, power and energy limits, cost)
  - self-discharge recursion, terminal value, cycles
  - soft terminal target, export limit, availability, SOC recovery
  - inert link rejection
  - full activation possible only in `deploy_from_procured`
  - `balancing_deployment`
  - reserve-link validation
  - cost-policy coefficients (online charge, ×60 removal, PV curtailment) and setpoint conflict
  - RES phantom reserve
  - first-stage slack attribution
  - zero-probability note
  - `maximum_on` history rules and priced overrun
  - failed start with committed prefix, and `released_units`
  - SOC metering clamp
  - overrun rolling
  - infeasible-fixed diagnosis
  - HiGHS scheduler regression
  - VSS decomposition
  - CLI incumbent/compare refusal and internal-error handling
- [tests/test_schema_and_regression.py](../tests/test_schema_and_regression.py), 6 tests:
  - schema validation of all examples
  - schema/validator field agreement
  - the original 24-h one-scenario regression
- One existing test was updated: an unreachable terminal target is now
  rejected before solving with a specific message (previously a generic
  `Infeasible`).

## 7. Documentation and tooling

- [stochastic_formulation.md](stochastic_formulation.md):
  - corrected statements that were no longer true (tree not implemented; stores offer no reserves)
  - the exact reserve-link rule
  - new "Review extensions" section with all equations
- [stochastic_verification.md](stochastic_verification.md) and
  [stochastic_mapping.md](stochastic_mapping.md): update sections appended.
- [verification_report.json](verification_report.json): regenerated, with the VSS
  decomposition and the tree example added; previous numbers are unchanged.
- [README.md](../README.md): rewritten without duplicates; documents all features.
- Greek chapter, about 34 pages, sources in [tools/chapter_gr_content/](../tools/chapter_gr_content/):
  - generator: `tools/write_chapter_gr_sources.py` → `docs/chapter_gr/*.json`
  - builder: `tools/build_stochastic_chapter_gr.py`, which converts LaTeX to native
    Word equations through Office's `MML2OMML.XSL`
  - figures: `tools/make_chapter_figures.py`, with the scenario and BESS figures computed from the code
  - every numerical example was checked with PuLP/HiGHS
  - the earlier `Stochastic_Programming_RDAS.docx`, which states that it did not
    inspect the code, is kept untouched
- Requirements:
  - `requirements-dev.txt`: `jsonschema`
  - `requirements-docs.txt`: `latex2mathml`, `matplotlib`

## 8. Compatibility and verification

With none of the new options every result is identical:

| Quantity | Value |
| --- | --- |
| Original 24-h fixture | 382562.14962105 EUR; 5191 variables; 12032 constraints |
| small_stochastic | 25622.614735 EUR |
| small_storage_cvar | 22613.379293 EUR |
| VSS / EVPI | 3107.679293 / 2.102731 EUR |
| Out-of-sample costs | 36282.86 / 37225.36 EUR |

Behaviour changes only where the previous behaviour was a defect:

- the committed boundary variables in rolling
- the validation rejections listed above
- the RES reserve bound in bounded mode
- the first-stage cost attribution

Run `python -m pytest tests -q` (with `--basetemp` pointing to a writable
folder if the system temp folder is restricted) and `python tools/verify_examples.py`.

## 9. Remaining limitations (not addressed)

- Commitment and reserve capacity stay first stage for the whole horizon even
  with a tree. Re-committing later hours inside a tree is not modelled.
- Within a stage, data are revealed at the stage's first hour.
- No closed-loop rolling simulator for out-of-sample evaluation.
- The hybrid station is not a full contract model: legacy penetration and
  setpoint limits still apply to gross RES output, and there is no auxiliary
  consumption or SOC-dependent power limit.
- BESS is not part of the legacy largest-unit reserve envelopes.
- Legacy online charge and ×60 scaling remain the default for regression.
  Studies should set `cost_policy` and check the penalty hierarchy
  (load shedding > reserve shortfall > curtailment > fuel).
- `synthetic()` and `synthetic_tree()` are demonstration generators. Real studies
  need scenarios built from the island's forecast errors.
- The `accept_incumbent` path is unit-tested only through validation and
  status handling. It was not exercised on a model that actually hits the
  time limit.
- No claim of complete MDN Code compliance is made.

## 10. Files

**Modified:**

- `mms/stochastic/model.py`, `data.py`, `rolling.py`, `evaluation.py`, `scenarios.py`
- `stochastic_main.py`
- `tools/make_examples.py`, `tools/verify_examples.py`
- `schemas/stochastic_extension.schema.json`
- `tests/test_stochastic.py` (one expectation)
- `README.md`
- `docs/stochastic_formulation.md`, `docs/stochastic_verification.md`, `docs/stochastic_mapping.md`
- `docs/verification_report.json`
- `requirements-dev.txt`, `requirements-docs.txt`

**Added:**

- `examples/small_tree_bess.json`
- `tests/test_review_extensions.py`, `tests/test_schema_and_regression.py`
- `tools/build_stochastic_chapter_gr.py`, `tools/write_chapter_gr_sources.py`, `tools/make_chapter_figures.py`
- `tools/chapter_gr_content/`, `docs/chapter_gr/`
- `docs/Κεφάλαιο_Στοχαστικός_Προγραμματισμός_RDAS.docx`
- this file

**Not modified:**

- the deterministic kernel (`mms/model/`, `mms/*.py`, `main.py`)
- the original JSON inputs and the previous examples
- the earlier Word documents and `runs/`
