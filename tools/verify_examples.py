"""Write reproducible compact evidence for the supplied examples."""

import importlib.metadata
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mms.stochastic.data import load
from mms.stochastic.artifacts import write_json
from mms.stochastic.evaluation import compare, evaluate_out_of_sample
from mms.stochastic.model import solve


def summary(result):
    return {key: result[key] for key in ("status", "operational_status", "model_notes", "run_metadata", "expected_cost_eur", "objective_eur", "cvar_eur",
            "first_stage_cost_eur", "expected_recourse_cost_eur", "expected_metrics",
            "build_seconds", "solve_seconds", "num_variables", "num_constraints", "validation")}


def main():
    data = load(ROOT / "examples/small_stochastic.json")
    report = compare(data)
    held_out = json.loads((ROOT / "examples/held_out_scenarios.json").read_text(encoding="utf-8"))
    original = solve(load(ROOT / "examples/original_single_scenario.json"))
    expected = 382562.14962105
    if abs(original["expected_cost_eur"] - expected) > 1e-3:
        raise AssertionError("Original single-scenario objective regression")
    evidence = {
        "date": datetime.now(timezone.utc).date().isoformat(), "python": sys.version.split()[0],
        "packages": {p: importlib.metadata.version(p) for p in ("pulp", "highspy", "numpy", "pandas")},
        "original_single_scenario": summary(original),
        "original_known_objective_eur": expected,
        "comparison": {key: report[key] for key in ("RP", "EV_objective", "EEV", "EEV_status", "WS", "VSS", "EVPI")},
        "stochastic_in_sample": summary(report["stochastic"]),
        "deterministic_in_sample": summary(report["deterministic_evaluated"]),
        "out_of_sample": {},
        "storage_cvar": summary(solve(load(ROOT / "examples/small_storage_cvar.json"))),
        "interpretation": "Synthetic paths only. Positive unserved energy/reserve shortage is reported even when algebraic validation passes. Two-stage recourse knows the full path; the tree example restricts recourse to node information.",
    }
    tree = load(ROOT / "examples/small_tree_bess.json")
    tree_report = compare(tree)
    evidence["tree_bess"] = {
        "comparison": {key: tree_report[key] for key in ("RP", "EV_objective", "EEV", "EEV_status", "WS", "VSS", "EVPI")},
        "VSS_decomposition": tree_report["VSS_decomposition"],
        "in_sample": summary(tree_report["stochastic"]),
        "first_stage_breakdown": tree_report["stochastic"]["first_stage_breakdown"],
        "scenario_tree": tree_report["stochastic"]["scenario_tree"],
        "implementable_dispatch": tree_report["stochastic"]["implementable_dispatch"],
    }
    evidence["comparison"]["VSS_decomposition"] = report["VSS_decomposition"]
    for name in ("stochastic", "deterministic"):
        evidence["out_of_sample"][name] = summary(evaluate_out_of_sample(data, report[name]["common_schedule"], held_out))
    target = ROOT / "docs/verification_report.json"
    write_json(target, evidence)
    print(target)


if __name__ == "__main__":
    main()
