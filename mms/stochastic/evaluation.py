"""Consistent risk-neutral RP, EEV, WS, VSS and EVPI on the same support."""

from copy import deepcopy

from .artifacts import canonical_hash
from .data import validate
from .errors import InfeasibleModelError, OptimizationError
from .model import solve
from .scenarios import expected_value_scenario

COMMITMENT_PREFIXES = ("state_", "startup_", "shutdown_", "u_2_", "transition_arc_")
RESERVE_PREFIXES = ("primary_ActPR_", "secondary_ActPR_", "tertiary_ActPR_", "storage_reserve_")


def compare(data, solver="highs", time_limit=None):
    data = deepcopy(data)
    validate(data)
    requested_risk_weight = data["stochastic"].get("risk", {}).get("weight", 0)
    data["stochastic"].setdefault("risk", {})["weight"] = 0
    kwargs = {"solver": solver, "time_limit": time_limit}
    rp = solve(data, **kwargs)
    mean = deepcopy(data)
    mean["stochastic"]["scenarios"] = [expected_value_scenario(data["stochastic"]["scenarios"])]
    ev = solve(mean, **kwargs)
    try:
        eev = solve(data, fixed_first_stage=ev["common_schedule"], **kwargs)
        eev_cost, eev_status = eev["expected_cost_eur"], "Optimal"
    except InfeasibleModelError:
        eev, eev_cost, eev_status = None, None, "Infeasible: no complete recourse under selected slack policy"
    # Ανάλυση VSS ανά σύνολο δεσμευμένων αποφάσεων: δεν είναι προσθετική και
    # εξαρτάται από τη σειρά δέσμευσης· δείχνει από πού προέρχεται η αξία.
    decomposition = {}
    for label, prefixes in (("commitment_only", COMMITMENT_PREFIXES),
                            ("commitment_and_reserves", COMMITMENT_PREFIXES + RESERVE_PREFIXES)):
        subset = {k: v for k, v in ev["common_schedule"].items() if k.startswith(prefixes)}
        try:
            partial = solve(data, fixed_first_stage=subset, **kwargs)["expected_cost_eur"]
            decomposition[label] = {"EEV": partial, "VSS": partial - rp["expected_cost_eur"], "fixed_decisions": len(subset)}
        except InfeasibleModelError:
            decomposition[label] = {"EEV": None, "VSS": None, "fixed_decisions": len(subset)}
    decomposition["full"] = {"EEV": eev_cost, "VSS": eev_cost - rp["expected_cost_eur"] if eev_cost is not None else None,
                             "fixed_decisions": len(ev["common_schedule"])}
    decomposition["note"] = "Not additive: each row re-optimizes every unfixed first-stage decision."
    ws = 0.0
    for scenario in data["stochastic"]["scenarios"]:
        if scenario["probability"] == 0:
            continue
        single = deepcopy(data)
        single["stochastic"]["scenarios"] = [dict(scenario, probability=1.0)]
        ws += scenario["probability"] * solve(single, **kwargs)["expected_cost_eur"]
    rp_cost = rp["expected_cost_eur"]
    tolerance = max(1e-4, 1e-7 * max(abs(rp_cost), abs(ws), abs(eev_cost or 0)))
    if ws > rp_cost + tolerance or (eev_cost is not None and rp_cost > eev_cost + tolerance):
        raise OptimizationError("Risk-neutral ordering WS <= RP <= EEV failed",
                                status="InvalidBenchmark", solver=solver,
                                details={"WS": ws, "RP": rp_cost, "EEV": eev_cost, "tolerance_eur": tolerance})
    return {"schema_version": "1.1", "criterion": "risk_neutral_expected_total_cost",
            "requested_risk_weight": requested_risk_weight, "evaluation_risk_weight": 0,
            "scenario_support_sha256": canonical_hash(data["stochastic"]["scenarios"]),
            "ordering_validation": {"passed": True, "tolerance_eur": tolerance},
            "RP": rp_cost, "EV_objective": ev["expected_cost_eur"],
            "EEV": eev_cost, "EEV_status": eev_status, "WS": ws,
            "VSS": eev_cost - rp["expected_cost_eur"] if eev_cost is not None else None,
            "VSS_interpretation": "EEV-RP; infinite if EEV infeasible (JSON null)",
            "EVPI": rp["expected_cost_eur"] - ws,
            "VSS_decomposition": decomposition,
            "stochastic": rp, "deterministic_evaluated": eev, "deterministic": ev}


def evaluate_out_of_sample(data, schedule, scenarios, solver="highs", time_limit=None):
    validate(data)
    # Η αξιολόγηση δεσμεύει ΟΛΕΣ τις πρώτου σταδίου μεταβλητές του σχεδίου.
    # Μερικό λεξικό θα επέτρεπε επαναβελτιστοποίηση και αισιόδοξη μεροληψία.
    if not isinstance(schedule, dict):
        raise ValueError("Evaluation requires a complete common_schedule mapping")
    evaluation = deepcopy(data)
    evaluation["stochastic"]["scenarios"] = deepcopy(scenarios)
    evaluation["stochastic"].setdefault("risk", {})["weight"] = 0
    # Ανεξάρτητες διαδρομές χωρίς δέντρο αξιολογούνται με πλήρη γνώση διαδρομής
    # (αισιόδοξο για την προσαρμογή)· δηλώνεται ρητά στο αποτέλεσμα.
    has_paths = [isinstance(s, dict) and "tree_path" in s for s in scenarios]
    if "scenario_tree" in evaluation["stochastic"] and not any(has_paths):
        del evaluation["stochastic"]["scenario_tree"]
    information = ("scenario_tree" if "scenario_tree" in evaluation["stochastic"] else "full_path_recourse")
    result = solve(evaluation, solver=solver, time_limit=time_limit, fixed_first_stage=schedule,
                   require_complete_first_stage=True)
    training_paths = {canonical_hash({k: v for k, v in s.items() if k not in ("id", "probability")})
                      for s in data["stochastic"]["scenarios"]}
    overlapping = [s["id"] for s in scenarios if canonical_hash(
        {k: v for k, v in s.items() if k not in ("id", "probability")}) in training_paths]
    result["evaluation"] = {"training_input_sha256": canonical_hash(data),
                            "fixed_decision_count": len(schedule),
                            "overlapping_training_path_ids": overlapping,
                            "recourse_information": information,
                            "independence": "Not inferred from IDs or seeds; requires external provenance."}
    return result
