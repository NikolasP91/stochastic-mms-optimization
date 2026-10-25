"""Behavioral tests for the stochastic extension, separate from legacy regressions."""

from copy import deepcopy
import json
from pathlib import Path

import pulp as pl
import pytest

from mms.stochastic.data import load, validate
from mms.stochastic.evaluation import compare, evaluate_out_of_sample
from mms.stochastic.model import build_model, compile_legacy, empirical_cvar, solve, SHARED_PREFIXES
from mms.stochastic.rolling import advance
from mms.stochastic.scenarios import nominal, synthetic

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def small():
    return load(ROOT / "examples/small_stochastic.json")


@pytest.fixture(scope="module")
def solved():
    return solve(load(ROOT / "examples/small_stochastic.json"))


def test_probability_one_matches_independent_deterministic_solve(small):
    small["stochastic"] = {"scenarios": [nominal(small)], "slack_policy": {"mode": "legacy"}}
    deterministic, _ = compile_legacy(small)
    deterministic.solve(pl.HiGHS(msg=False, threads=1, gapRel=0))
    stochastic = solve(small)
    assert stochastic["expected_cost_eur"] == pytest.approx(pl.value(deterministic.objective), abs=1e-5)
    assert stochastic["num_constraints"] == len(deterministic.constraints)
    assert stochastic["num_variables"] == deterministic.numVariables()


def test_shared_decisions_and_independent_balance(small, solved):
    common = solved["common_schedule"]
    for scenario in small["stochastic"]["scenarios"]:
        values = solved["scenario_dispatch"][scenario["id"]]["variables"]
        for name, value in values.items():
            if name.startswith(SHARED_PREFIXES):
                assert value == pytest.approx(common[name], abs=1e-6)
        for t, load_mw in enumerate(scenario["load_mw"], 1):
            generation = sum(values[f"power_{i+1}_{t}"] for i in range(4))
            assert generation + values[f"s_load_minus_{t}"] == pytest.approx(load_mw, abs=1e-7)
            for gid, path in scenario["renewables_mw"].items():
                assert values[f"power_{int(gid)+1}_{t}"] <= path[t-1] + 1e-7
            for i in range(2):
                up = sum(values[f"activation_{p}_up_{i+1}_{t}"] for p in ("primary", "secondary", "tertiary"))
                down = sum(values[f"activation_{p}_down_{i+1}_{t}"] for p in ("primary", "secondary", "tertiary"))
                assert values[f"power_{i+1}_{t}"] == pytest.approx(common[f"reference_{i+1}_{t}"] + up - down, abs=1e-7)
                assert min(up, down) < 1e-7
    assert solved["validation"]["passed"]
    assert solved["expected_cost_eur"] == pytest.approx(solved["first_stage_cost_eur"] + solved["expected_recourse_cost_eur"])
    for output in solved["scenario_dispatch"].values():
        assert output["total_cost_eur"] == pytest.approx(output["operating_cost_eur"] + output["penalty_cost_eur"] + output["renewable_priority_cost_eur"])


def test_nonanticipativity_is_enforced_by_one_problem(small):
    model = build_model(small)
    blocks = list(model.blocks.values())
    model.problem += blocks[0]["variables"]["state_1_1"] == 0
    model.problem += blocks[1]["variables"]["state_1_1"] == 1
    model.problem.solve(pl.HiGHS(msg=False, threads=1))
    assert model.problem.status == pl.LpStatusInfeasible


def test_vss_evpi_and_same_scenario_evaluation(small):
    report = compare(small)
    assert report["WS"] <= report["RP"] + 1e-5 <= report["EEV"] + 2e-5
    assert report["VSS"] == pytest.approx(report["EEV"] - report["RP"])
    assert report["EVPI"] == pytest.approx(report["RP"] - report["WS"])
    assert report["VSS"] > 0
    held_out = synthetic(small, count=2, seed=17)
    evaluation = evaluate_out_of_sample(small, report["stochastic"]["common_schedule"], held_out)
    assert evaluation["common_schedule"] == pytest.approx(report["stochastic"]["common_schedule"], abs=1e-6)


def test_cvar_includes_first_stage_once(small):
    small["stochastic"]["risk"] = {"alpha": 0.7, "weight": 0.25}
    result = solve(small)
    assert result["objective_eur"] == pytest.approx(result["expected_cost_eur"] + 0.25 * result["cvar_eur"], abs=1e-5)
    assert empirical_cvar([(0, 0.8), (100, 0.2)], 0.5) == pytest.approx(40)


def test_storage_changes_balance_with_efficiency_and_terminal_limit(small):
    for g in small["Generating_Units"]:
        for key, val in list(g.items()):
            if isinstance(val, list) and len(val) == 4 and key not in ("operating-states", "operating-state-transitions"):
                g[key] = val[:2]
    small["Load_forecast"] = [0, 2, 3]
    small["Generating_Units"][2]["Production_Forecast"] = [6, 0]
    small["Generating_Units"][3]["Production_Forecast"] = [0, 0]
    small["stochastic"]["scenarios"] = [nominal(small)]
    small["stochastic"]["reserve_link"] = False
    small["stochastic"]["storage"] = [{"id": "wind_store", "capacity_mwh": 4, "min_mwh": 0,
        "initial_mwh": 0, "terminal_min_mwh": 0, "charge_mw": 4, "discharge_mw": 4,
        "charge_efficiency": 0.95, "discharge_efficiency": 0.95,
        "throughput_eur_per_mwh": 1, "grid_charge": False, "renewable_gen_id": 2}]
    fixed = {f"state_{i}_{t}": 0 for i in (1, 2) for t in (1, 2)}
    result = solve(small, fixed_first_stage=fixed)
    values = result["scenario_dispatch"]["nominal"]["variables"]
    energy = 0
    for t, demand in enumerate([2, 3], 1):
        charge, discharge = values[f"storage_charge_0_{t}"], values[f"storage_discharge_0_{t}"]
        energy += 0.95 * charge - discharge / 0.95
        assert energy == pytest.approx(values[f"storage_energy_0_{t}"], abs=1e-7)
        assert min(charge, discharge) < 1e-8
        assert values[f"power_3_{t}"] + discharge - charge == pytest.approx(demand, abs=1e-7)
    assert values["storage_discharge_0_2"] == pytest.approx(3)
    assert energy >= -1e-7
    small["stochastic"]["storage"][0]["terminal_min_mwh"] = 4
    # At most 0.95*4 = 3.8 MWh can be stored: rejected before solving, with the cause.
    with pytest.raises(ValueError, match="unreachable in scenario 'nominal'"):
        solve(small, fixed_first_stage=fixed)


def test_rolling_uses_observations_and_preserves_commitments(small, solved):
    conditional = next(iter(solved["scenario_dispatch"].values()))["variables"]
    observations = {"units": {}}
    for g in small["Generating_Units"]:
        gid = g["gen_id"]
        state = next(k["id"] for k in g["operating-states"] if conditional[f"u_2_{gid+1}_1_{k['id']}"] > 0.5)
        observations["units"][str(gid)] = [{"power_mw": conditional[f"power_{gid+1}_1"], "operating_state_id": state}]
    refreshed, fixed = advance(small, solved, observations, small, executed_steps=1, committed_steps=1)
    assert refreshed["Generating_Units"][0]["state-transitions"][0]["transitions"]["min-transition-time-left"] == 60
    assert fixed["state_1_1"] == solved["common_schedule"]["state_1_2"]
    assert refreshed["Generating_Units"][0]["current_Power(MW)"] == observations["units"]["0"][0]["power_mw"]
    assert len(refreshed["Load_forecast"]) == len(small["Load_forecast"])
    assert solve(refreshed, fixed_first_stage=fixed)["validation"]["passed"]


def test_maximum_on_carries_elapsed_history(small):
    g = small["Generating_Units"][0]
    g["state"] = 1
    g["operating-states"][0]["isEnabled"] = False
    g["operating-states"][1]["isEnabled"] = True
    small["stochastic"]["maximum_on"] = {"0": {"hours": 3, "elapsed_hours": 2}}
    with pytest.raises(RuntimeError, match="Infeasible"):
        solve(small, fixed_first_stage={"state_1_1": 1, "state_1_2": 1})


@pytest.mark.parametrize("mutation", [
    lambda d: d["stochastic"]["scenarios"][0].update(probability=0.9),
    lambda d: d["stochastic"]["scenarios"][0].update(probability=float("nan")),
    lambda d: d["stochastic"]["scenarios"][0]["load_mw"].pop(),
    lambda d: d["stochastic"]["scenarios"][0]["renewables_mw"]["2"].__setitem__(0, 99),
    lambda d: d["stochastic"]["scenarios"][0].update(availability=[1]),
    lambda d: d["Generating_Units"][0].update(state=1),
    lambda d: d["stochastic"]["risk"].update(alpha=1),
])
def test_bad_data_rejected(small, mutation):
    mutation(small)
    with pytest.raises(ValueError):
        validate(small)


def test_seeded_joint_paths_and_input_immutability(small):
    before = deepcopy(small)
    assert synthetic(small, 3, 11) == synthetic(small, 3, 11)
    assert synthetic(small, 3, 11) != synthetic(small, 3, 12)
    build_model(small)
    assert small == before


def test_unknown_fixed_decision_rejected(small):
    with pytest.raises(ValueError, match="Unknown first-stage"):
        build_model(small, {"typo_1_1": 1})


def test_zero_probability_path_does_not_constrain_schedule(small, solved):
    ignored = deepcopy(small["stochastic"]["scenarios"][0])
    ignored.update(id="ignored", probability=0, load_mw=[1000]*4)
    small["stochastic"]["scenarios"].append(ignored)
    result = solve(small)
    assert result["expected_cost_eur"] == pytest.approx(solved["expected_cost_eur"], abs=1e-5)
    assert "ignored" not in result["scenario_dispatch"]


def test_rolling_carries_transition_timers_and_zero_maximum(small):
    unit = small["Generating_Units"][0]
    arc = unit["operating-state-transitions"][0]["transitions"][0]
    arc.update({"min-transition-time_b": 180, "max-transition-time_b": 240})
    small["stochastic"]["maximum_on"] = {"0": {"hours": 8, "elapsed_hours": 0}}
    observations = {"units": {str(g["gen_id"]): [{"power_mw": 0, "operating_state_id": 1}]
                              for g in small["Generating_Units"]}}
    next_data, _ = advance(small, {"common_schedule": {}}, observations, small)
    timer = next_data["Generating_Units"][0]["operating-state-transitions"][0]["transitions"][0]
    assert timer["min-transition-time-left_b"] == 120
    assert timer["max-transition-time-left_b"] == 180
    assert next_data["stochastic"]["maximum_on"]["0"]["elapsed_hours"] == 1
    next_data["stochastic"]["initial_operating_obligations"] = {"0": {"state_id": 1, "maximum_remaining_hours": 0}}
    with pytest.raises(RuntimeError, match="Infeasible"):
        solve(next_data, fixed_first_stage={"state_1_1": 1})


def test_rolling_requires_and_uses_measured_soc():
    data = load(ROOT / "examples/small_storage_cvar.json")
    observations = {"units": {str(g["gen_id"]): [{"power_mw": 0, "operating_state_id": 0}]
                              for g in data["Generating_Units"]}}
    with pytest.raises(ValueError, match="SOC"):
        advance(data, {"common_schedule": {}}, observations, data)
    observations["storage_mwh"] = {"hybrid_wind_store": 1.25}
    next_data, _ = advance(data, {"common_schedule": {}}, observations, data)
    assert next_data["stochastic"]["storage"][0]["initial_mwh"] == 1.25
