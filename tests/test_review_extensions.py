"""Tests for the review extensions: scenario trees, professional BESS, reserve-link
modes, explicit cost policy, rolling robustness and reporting (docs/REVIEW_CHANGES.md)."""

from copy import deepcopy
import json
from pathlib import Path

import pulp as pl
import pytest

import stochastic_main
from mms.stochastic.data import load, validate
from mms.stochastic.evaluation import compare
from mms.stochastic.model import TREE_RECOURSE, build_model, solve
from mms.stochastic.rolling import advance
from mms.stochastic.scenarios import nominal, synthetic_tree

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def small():
    return load(ROOT / "examples/small_stochastic.json")


@pytest.fixture
def storage():
    data = load(ROOT / "examples/small_storage_cvar.json")
    data["stochastic"]["risk"]["weight"] = 0
    return data


@pytest.fixture(scope="module")
def tree_result():
    return solve(load(ROOT / "examples/small_tree_bess.json"))


def without_paths(scenarios):
    return [{k: v for k, v in s.items() if k != "tree_path"} for s in scenarios]


# --------------------------------------------------------------------- tree

def test_tree_generator_shares_history_until_branching(storage):
    scenarios = synthetic_tree(storage, [1, 2, 3], [1, 2, 2], seed=3)
    assert len(scenarios) == 4 and sum(s["probability"] for s in scenarios) == pytest.approx(1)
    assert len({s["load_mw"][0] for s in scenarios}) == 1           # root hour shared
    first = [s for s in scenarios if s["tree_path"][1] == scenarios[0]["tree_path"][1]]
    assert len({s["load_mw"][1] for s in first}) == 1                # siblings share hour 2
    assert len({tuple(s["load_mw"][2:]) for s in scenarios}) == 4    # leaves differ afterwards


def test_tree_validation_rejects_information_leaks(storage):
    storage["stochastic"]["scenarios"] = synthetic_tree(storage, [1, 2], [1, 2], seed=1)
    with pytest.raises(ValueError, match="requires stochastic.scenario_tree"):
        validate(storage)
    storage["stochastic"]["scenario_tree"] = {"stage_start_hours": [1, 2]}
    validate(storage)
    leaked = deepcopy(storage)
    leaked["stochastic"]["scenarios"][1]["load_mw"][0] += 0.5       # differs inside the root node
    with pytest.raises(ValueError, match="identical data"):
        validate(leaked)
    rooted = deepcopy(storage)
    rooted["stochastic"]["scenarios"][1]["tree_path"][0] = "other_root"
    with pytest.raises(ValueError, match="one root node"):
        validate(rooted)
    for starts in ([2, 3], [1, 1], [1, 9]):
        bad = deepcopy(storage)
        bad["stochastic"]["scenario_tree"]["stage_start_hours"] = starts
        with pytest.raises(ValueError):
            validate(bad)


def test_tree_enforces_equal_recourse_in_shared_nodes(tree_result):
    data = load(ROOT / "examples/small_tree_bess.json")
    by_id = {s["id"]: s for s in data["stochastic"]["scenarios"]}
    outputs = tree_result["scenario_dispatch"]
    for stage in tree_result["scenario_tree"]["stages"]:
        for node in stage["nodes"]:
            reference = outputs[node["scenarios"][0]]["variables"]
            for sid in node["scenarios"][1:]:
                values = outputs[sid]["variables"]
                for name, value in reference.items():
                    match = TREE_RECOURSE.fullmatch(name)
                    if match and int(match.group(2)) in stage["hours"]:
                        assert values[name] == pytest.approx(value, abs=1e-6), (sid, name)
    assert tree_result["scenario_tree"]["nonanticipativity_constraints"] > 0
    assert tree_result["model_notes"][0]["code"] == "MULTISTAGE_SCENARIO_TREE"
    root = tree_result["implementable_dispatch"]
    assert root["hours"] == [1]
    for sid in by_id:
        assert outputs[sid]["variables"]["storage_charge_0_1"] == pytest.approx(root["decisions"]["storage_charge_0_1"])


def test_tree_costs_at_least_full_path_recourse():
    data = load(ROOT / "examples/small_tree_bess.json")
    multistage = solve(data)["expected_cost_eur"]
    two_stage = deepcopy(data)
    del two_stage["stochastic"]["scenario_tree"]
    two_stage["stochastic"]["scenarios"] = without_paths(two_stage["stochastic"]["scenarios"])
    full_path = solve(two_stage)
    assert full_path["implementable_dispatch"] is None
    assert multistage >= full_path["expected_cost_eur"] - 1e-6


# --------------------------------------------------------------------- BESS

def _store(data):
    return data["stochastic"]["storage"][0]


def test_bess_reserve_is_first_stage_and_enters_requirement(storage):
    _store(storage)["reserve"] = {"products": {"primary": ["up", "down"]}, "sustain_minutes": {"primary": 30},
                                  "capacity_cost_eur_per_mw_h": {"up": 0.25, "down": 0.25}}
    model = build_model(storage)
    names = [n for n in model.shared if n.startswith("storage_reserve_")]
    assert sorted({n.split("_")[3] for n in names}) == ["down", "up"] and len(names) == 8
    var = model.shared["storage_reserve_primary_up_0_1"]
    rows = [c for name, c in model.problem.constraints.items()
            if c.sense == pl.LpConstraintEQ and var in c.keys() and "primary_active_power_reserves" in name]
    assert len(rows) == len(storage["stochastic"]["scenarios"])     # one requirement row per scenario
    result = solve(storage)
    assert result["validation"]["passed"]
    expected = 0.25 * sum(v for n, v in result["common_schedule"].items() if n.startswith("storage_reserve_"))
    assert result["first_stage_breakdown"]["storage_reserve_capacity_eur"] == pytest.approx(expected)


def test_bess_reserve_respects_power_and_energy_headroom(storage):
    _store(storage)["reserve"] = {"products": {"primary": ["up"]}, "sustain_minutes": {"primary": 60}}
    model = build_model(storage)
    model.problem += model.shared["storage_reserve_primary_up_0_1"] >= 2.1   # > discharge power 2 MW
    model.problem.solve(pl.HiGHS(msg=False))
    assert model.problem.status == pl.LpStatusInfeasible
    result = solve(storage)
    for output in result["scenario_dispatch"].values():
        report = output["storage"]["hybrid_wind_store"]
        for t, reserve in enumerate(report["committed_reserve"]["primary_up_mw"], 1):
            energy = min(report["energy_mwh"][t - 1], report["energy_mwh"][t])
            assert reserve * 1.0 <= 0.95 * (energy - 0) + 1e-6           # sustain 60 min from usable SOC


def test_bess_self_discharge_terminal_value_cycles_and_report(storage):
    store = _store(storage)
    store.update(self_discharge_per_hour=0.02, terminal_value_eur_per_mwh=30, max_cycles_per_horizon=0.3)
    result = solve(storage)
    for output in result["scenario_dispatch"].values():
        report = output["storage"]["hybrid_wind_store"]
        e = report["energy_mwh"]
        for t in range(1, len(e)):
            assert e[t] == pytest.approx(0.98 * e[t - 1] + 0.95 * report["charge_mw"][t - 1]
                                         - report["discharge_mw"][t - 1] / 0.95, abs=1e-6)
        assert report["equivalent_full_cycles"] <= 0.3 + 1e-6
        assert report["terminal_value_eur"] == pytest.approx(30 * e[-1])


def test_bess_soft_terminal_target_reports_shortfall_instead_of_infeasibility(storage):
    store = _store(storage)
    store.update(initial_mwh=0, terminal_min_mwh=4, charge_mw=0.5)
    with pytest.raises(ValueError, match="unreachable"):
        validate(storage)
    store["terminal_shortfall_penalty_eur_per_mwh"] = 500
    result = solve(storage)
    slacks = [s for o in result["scenario_dispatch"].values() for s in o["nonzero_slacks"]
              if s["variable"] == "s_storage_terminal_0"]
    assert slacks and all(s["penalty_coefficient"] == 500 for s in slacks)


def test_bess_export_limit_and_power_availability(storage):
    store = _store(storage)
    store.update(export_limit_mw=1.0, power_availability=[0, 1, 1, 1])
    result = solve(storage)
    for output in result["scenario_dispatch"].values():
        values = output["variables"]
        report = output["storage"]["hybrid_wind_store"]
        assert report["charge_mw"][0] == 0 and report["discharge_mw"][0] == 0
        for t in range(1, 5):
            assert values[f"power_3_{t}"] + report["net_injection_mw"][t - 1] <= 1.0 + 1e-6


def test_bess_soc_recovery_below_operating_minimum(storage):
    store = _store(storage)
    store.update(min_mwh=1.0, initial_mwh=0.2, terminal_min_mwh=1.0)
    with pytest.raises(ValueError, match="soc_recovery_penalty"):
        validate(storage)
    store["soc_recovery_penalty_eur_per_mwh"] = 100
    assert solve(storage)["validation"]["passed"]


def test_bess_inert_renewable_link_is_rejected(storage):
    _store(storage)["grid_charge"] = True
    with pytest.raises(ValueError, match="has no effect"):
        validate(storage)


# ------------------------------------------------------- reserve-link modes

def _activation_case(small, mode):
    data = deepcopy(small)
    if mode:
        data["stochastic"]["reserve_link_mode"] = mode
    data["stochastic"]["scenarios"] = [dict(data["stochastic"]["scenarios"][0], probability=1.0)]
    model = build_model(data)
    block = next(iter(model.blocks.values()))["variables"]
    fix = {"state_1_2": 1, "reference_1_2": 4, "tertiary_ActPR_plus1_2": 6,
           "primary_ActPR_plus1_2": 0, "secondary_ActPR_plus1_2": 0}
    for name, value in fix.items():
        model.problem += model.shared[name] == value
    model.problem += block["activation_tertiary_up_1_2"] >= 6
    model.problem.solve(pl.HiGHS(msg=False))
    return model.problem.status


def test_deploy_from_procured_allows_full_activation(small):
    # Availability 12 MW, reference 4 + reserve 6 = 10 MW. Deploying the whole 6 MW is
    # physical; the default rows also demand 6 MW of untouched room (4 + 6 + 6 > 12).
    assert _activation_case(small, None) == pl.LpStatusInfeasible        # default: r + e of room
    assert _activation_case(small, "deploy_from_procured") == pl.LpStatusOptimal


def test_balancing_deployment_flag_removes_product_activation(small):
    small["stochastic"]["reserve_products"]["primary"]["balancing_deployment"] = False
    model = build_model(small)
    names = {n for b in model.blocks.values() for n in b["variables"]}
    assert not any(n.startswith("activation_primary_") for n in names)
    assert any(n.startswith("activation_tertiary_") for n in names)


def test_reserve_link_requires_an_enabled_product(small):
    for product in ("primary", "secondary", "tertiary"):
        small["constraints"][f"{product}_active_power_reserves_constraint"] = False
    with pytest.raises(ValueError, match="at least one enabled reserve product"):
        validate(small)


# ------------------------------------------------------------- cost policy

def test_cost_policy_replaces_legacy_online_charge_and_minute_scaling(small):
    legacy = build_model(small)
    small["stochastic"]["cost_policy"] = {"legacy_time_scaled_costs": "per_hour",
                                          "thermal_online_charge_eur_per_h": 50,
                                          "renewable_curtailment_eur_per_mwh": 200}
    policy = build_model(small)
    weight = 1 / len(small["stochastic"]["scenarios"])
    state, new_state = legacy.shared["state_1_1"], policy.shared["state_1_1"]
    # The shared copy belongs to scenario 0, so its coefficient is weighted by π_0.
    assert legacy.problem.objective[state] - policy.problem.objective[new_state] == pytest.approx((6000 - 50) * weight)
    reserve = "scenario_0__primary_ActPR_plus1_1"
    old = {v.name: c for v, c in legacy.problem.objective.items()}[reserve]
    new = {v.name: c for v, c in policy.problem.objective.items()}[reserve]
    assert new == pytest.approx(old / 60)
    pv = {v.name: c for v, c in policy.problem.objective.items()}["scenario_0__power_4_1"]
    assert pv == pytest.approx(-200 * weight)                        # PV curtailment is now priced
    result = solve(small)
    assert result["first_stage_breakdown"]["thermal_online_charge_eur_per_h"] == 50
    assert result["first_stage_breakdown"]["online_charge_source"] == "cost_policy"


def test_curtailment_weight_conflicts_with_setpoint_algorithm(small):
    small["constraints"]["res_pv_dispatch_variables_constraints"] = True
    small["stochastic"]["cost_policy"] = {"renewable_curtailment_eur_per_mwh": 100}
    with pytest.raises(ValueError, match="setpoint dispatch"):
        validate(small)


# ---------------------------------------------------- legacy interplay fixes

def test_renewable_reserve_is_bounded_by_scenario_resource(small):
    unit = small["Generating_Units"][2]
    for product in ("Primary", "Secondary", "Tertiary"):
        unit[f"{product}_Active_Power_Reserves(MW)"] = [5, 5]
    for scenario in small["stochastic"]["scenarios"]:
        scenario["renewables_mw"]["2"] = [1.0] * 4
    model = build_model(small)
    for block in model.blocks.values():
        model.problem += block["variables"]["power_3_2"] >= 1.0
    model.problem += model.shared["tertiary_ActPR_plus3_2"] >= 0.5
    model.problem.solve(pl.HiGHS(msg=False))
    assert model.problem.status == pl.LpStatusInfeasible


def test_first_stage_slacks_are_attributed_to_first_stage(small):
    base = solve(small)
    small["Generating_Units"][1]["mustRun"] = [1, 1, 1, 1]
    small["Cost_parameters"]["x_must_run"] = 50
    small["stochastic"]["slack_policy"]["caps"]["s_must_run_"] = 1
    forced = solve(small, fixed_first_stage={f"state_2_{t}": 0 for t in range(1, 5)})
    assert forced["first_stage_cost_eur"] >= base["first_stage_cost_eur"] + 4 * 50 - 1e-6
    stages = {s["stage"] for o in forced["scenario_dispatch"].values() for s in o["nonzero_slacks"]
              if s["variable"].startswith("s_must_run_")}
    assert stages == {"first"}


def test_zero_probability_paths_are_reported(small):
    extra = dict(deepcopy(small["stochastic"]["scenarios"][0]), id="stress", probability=0.0)
    small["stochastic"]["scenarios"].append(extra)
    result = solve(small)
    note = next(n for n in result["model_notes"] if n["code"] == "EXCLUDED_ZERO_PROBABILITY")
    assert note["scenario_ids"] == ["stress"]


def test_maximum_on_history_rules(small):
    g = small["Generating_Units"][0]
    g["state"] = 1
    g["operating-states"][0]["isEnabled"] = False
    g["operating-states"][1]["isEnabled"] = True
    small["stochastic"]["maximum_on"] = {"0": {"hours": 2, "elapsed_hours": 0}}
    with pytest.raises(ValueError, match="current ON period"):
        validate(small)
    small["stochastic"]["maximum_on"]["0"]["elapsed_hours"] = 3
    with pytest.raises(ValueError, match="violation_penalty"):
        validate(small)
    small["stochastic"]["maximum_on"]["0"]["violation_penalty_eur_per_h"] = 500
    result = solve(small, fixed_first_stage={"state_1_1": 1})
    slacks = {s["variable"] for o in result["scenario_dispatch"].values() for s in o["nonzero_slacks"]}
    assert "s_maximum_on_1_1" in slacks


# ----------------------------------------------------------------- rolling

def _observe(data, solved, override=None):
    conditional = next(iter(solved["scenario_dispatch"].values()))["variables"]
    observations = {"units": {}}
    for g in data["Generating_Units"]:
        gid = g["gen_id"]
        state = next(k["id"] for k in g["operating-states"] if conditional[f"u_2_{gid+1}_1_{k['id']}"] > 0.5)
        observations["units"][str(gid)] = [{"power_mw": conditional[f"power_{gid+1}_1"], "operating_state_id": state}]
    observations["units"].update(override or {})
    return observations


def test_failed_start_with_committed_prefix_is_solvable(small):
    solved = solve(small)
    started = [g for g in range(4) if solved["common_schedule"][f"startup_{g+1}_1"] > 0.5]
    assert started
    gid = started[0]
    observations = _observe(small, solved, {str(gid): [{"power_mw": 0, "operating_state_id": 0}]})
    refreshed, fixed = advance(small, solved, observations, small, executed_steps=1, committed_steps=1)
    assert not any(name.startswith(("startup_", "shutdown_", "transition_arc_")) for name in fixed)
    assert solve(refreshed, fixed_first_stage=fixed)["validation"]["passed"]
    released, kept = advance(small, solved, observations, small, executed_steps=1, committed_steps=1,
                             released_units=[gid])
    assert not any(name.startswith(f"state_{gid+1}_") for name in kept)


def test_rolling_clamps_soc_metering_noise(storage):
    observations = {"units": {str(g["gen_id"]): [{"power_mw": 0, "operating_state_id": 0}]
                              for g in storage["Generating_Units"]},
                    "storage_mwh": {"hybrid_wind_store": 4 + 5e-7}}
    next_data, _ = advance(storage, {"common_schedule": {}}, observations, storage)
    assert next_data["stochastic"]["storage"][0]["initial_mwh"] == 4
    observations["storage_mwh"]["hybrid_wind_store"] = 4.1
    with pytest.raises(ValueError, match="physical energy bounds"):
        advance(storage, {"common_schedule": {}}, observations, storage)


def test_maximum_on_overrun_rolls_forward(small):
    g = small["Generating_Units"][0]
    g["state"] = 1
    g["operating-states"][0]["isEnabled"] = False
    g["operating-states"][1]["isEnabled"] = True
    g["current_Power(MW)"] = 5
    small["stochastic"]["maximum_on"] = {"0": {"hours": 1, "elapsed_hours": 1}}
    observations = {"units": {str(u["gen_id"]): [{"power_mw": 5 if u["gen_id"] == 0 else 0,
                                                   "operating_state_id": 1 if u["gen_id"] == 0 else 0}]
                              for u in small["Generating_Units"]}}
    clamped, _ = advance(small, {"common_schedule": {}}, observations, small)
    assert clamped["stochastic"]["maximum_on"]["0"]["elapsed_hours"] == 1
    small["stochastic"]["maximum_on"]["0"]["violation_penalty_eur_per_h"] = 1000
    carried, _ = advance(small, {"common_schedule": {}}, observations, small)
    assert carried["stochastic"]["maximum_on"]["0"]["elapsed_hours"] == 2


def test_infeasible_fixed_schedule_is_diagnosed(small):
    fixed = {f"state_{i}_{t}": 0 for i in range(1, 5) for t in range(1, 5)}
    small["stochastic"]["slack_policy"]["caps"]["s_load_minus_"] = 0
    with pytest.raises(RuntimeError) as info:
        solve(small, fixed_first_stage=fixed)
    assert info.value.details["diagnosis"]["feasible_without_fixed_decisions"] is True


def test_solve_after_other_highs_run_in_same_process(small):
    toy = pl.LpProblem("toy", pl.LpMinimize)
    x = pl.LpVariable("x", 0, 10)
    toy += x
    toy += x >= 1
    toy.solve(pl.HiGHS(msg=False))          # default thread count initializes the scheduler
    assert solve(small)["status"] == "Optimal"


# -------------------------------------------------------------- evaluation

def test_vss_decomposition_is_reported(small):
    report = compare(small)
    decomposition = report["VSS_decomposition"]
    assert decomposition["full"]["VSS"] == pytest.approx(report["VSS"])
    for key in ("commitment_only", "commitment_and_reserves"):
        assert decomposition[key]["VSS"] >= -1e-5
        assert decomposition[key]["fixed_decisions"] < decomposition["full"]["fixed_decisions"]


def test_cli_rejects_incumbent_with_compare_and_reports_internal_errors(tmp_path, monkeypatch):
    output = tmp_path / "out.json"
    code = stochastic_main.main([str(ROOT / "examples/small_stochastic.json"), "--compare",
                                 "--accept-incumbent", "-o", str(output)])
    assert code == 2
    assert "accept-incumbent" in json.loads(output.with_suffix(".error.json").read_text(encoding="utf-8"))["message"]

    def broken(*args, **kwargs):
        raise KeyError("boom")

    monkeypatch.setattr(stochastic_main, "solve", broken)
    code = stochastic_main.main([str(ROOT / "examples/small_stochastic.json"), "-o", str(output)])
    assert code == 2
    assert json.loads(output.with_suffix(".error.json").read_text(encoding="utf-8"))["status"] == "InternalError"
    manifests = list((tmp_path / "out_artifacts").glob("*/manifest.json"))
    assert any(json.loads(m.read_text(encoding="utf-8"))["status"] == "Failed" for m in manifests)
