"""Tests of the GUI adapter, runner and pages (the optimization model is not modified)."""

from copy import deepcopy
import math
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("plotly")

from gui import adapter  # noqa: E402
from input_validation import validate_input_data  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SMALL = ROOT / "examples" / "small_stochastic.json"
TREE = ROOT / "examples" / "small_tree_bess.json"


def case(path):
    data, _ = adapter.prepare_case(adapter.read_json(path))
    return data


def test_discovers_example_cases():
    names = {p.name for p in adapter.discover_cases()}
    assert {"small_stochastic.json", "small_tree_bess.json"} <= names


def test_plain_mms_input_gets_nominal_scenario():
    data, notes = adapter.prepare_case(adapter.read_json(ROOT / "new_json_test.json"))
    assert notes and len(data["stochastic"]["scenarios"]) == 1
    assert data["stochastic"]["scenarios"][0]["probability"] == 1.0
    assert not [i for i in adapter.validate_case(data) if i.severity == "error"]


def test_validation_points_to_unit_and_scenarios():
    data = case(SMALL)
    data["Generating_Units"][0]["min_power(MW)"] = 50
    data["stochastic"]["scenarios"][0]["probability"] = 0.5
    issues = [i for i in adapter.validate_case(data) if i.severity == "error"]
    assert any(i.location.startswith("Unit G0") and "exceeds max power" in i.message for i in issues)
    assert any("probabilities" in i.location.lower() for i in issues)


def test_unit_colors_are_stable_and_unique():
    infos = adapter.unit_infos(case(TREE))
    assert len({u.color for u in infos}) == len(infos)
    assert {u.type for u in infos} >= {"thermal", "hybrid", "pv", "storage"}
    assert adapter.unit_infos(case(TREE))[0].color == infos[0].color


def test_ds_conversion_is_15_minute_and_valid():
    data = case(SMALL)
    ds = adapter.build_ds_input(data, adapter.EXPECTED_ID, ds_hours=4)
    assert ds["Time_granularity"] == 15
    assert len(ds["Load_forecast"]) == 1 + 16
    assert all(len(u["availability"]) == 16 for u in ds["Generating_Units"])
    assert "stochastic" not in ds
    assert not validate_input_data(deepcopy(ds))["errors"]
    first_hour = sum(s["probability"] * s["load_mw"][0] for s in data["stochastic"]["scenarios"])
    assert ds["Load_forecast"][1:5] == pytest.approx([first_hour] * 4)


def test_editing_round_trip_leaves_case_unchanged():
    data = case(TREE)
    before = deepcopy(data)
    adapter.apply_units_frame(data, adapter.units_frame(data))
    adapter.apply_initial_conditions(data, adapter.initial_conditions_frame(data))
    adapter.apply_storage_frame(data, adapter.storage_frame(data))
    for i in range(len(data["Generating_Units"])):
        adapter.apply_unit_series(data, i, adapter.unit_series_frame(data, i))
        adapter.apply_operating_states(data, i, adapter.operating_states_frame(data, i))
    adapter.apply_parameters(data, adapter.parameters_snapshot(data))
    assert adapter.diff(before, data).empty


@pytest.mark.parametrize("mode,compare", [("RDAS", False), ("RDAS", True), ("DS", False)])
def test_runner_end_to_end(tmp_path, monkeypatch, mode, compare):
    monkeypatch.setattr(adapter, "RUNS_ROOT", tmp_path)
    data = case(TREE if mode == "RDAS" and not compare else SMALL)
    handle = adapter.start_run(data, mode=mode, case_name="test", solver="highs", time_limit=None,
                               accept_incumbent=False, compare=compare, scenario_choice=adapter.EXPECTED_ID,
                               ds_hours=4)
    assert handle.process.wait(timeout=600) == 0
    res = adapter.load_results(handle.run_dir)
    assert res.status == "Optimal" and not res.error
    assert res.meta["num_binaries"] > 0
    assert math.isclose(res.waterfall["eur"].sum(), res.meta["expected_cost_eur"], rel_tol=1e-6, abs_tol=0.01)
    assert set(res.dispatch["t"]) == set(res.periods)
    if mode == "DS":
        assert res.minutes == 15 and len(res.periods) == 16
    if compare:
        assert res.benchmarks["VSS"] >= -1e-6 and res.benchmarks["EVPI"] >= -1e-6


def test_infeasible_run_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "RUNS_ROOT", tmp_path)
    data = case(SMALL)
    for unit in data["Generating_Units"]:
        if unit["comments"].startswith("Therm"):
            unit["availability"] = [0.5] * 4
    data["stochastic"]["slack_policy"] = {"mode": "bounded"}
    handle = adapter.start_run(data, mode="RDAS", case_name="inf", solver="highs", time_limit=None,
                               accept_incumbent=False, compare=False, scenario_choice=adapter.EXPECTED_ID, ds_hours=4)
    handle.process.wait(timeout=600)
    assert adapter.finalize_run(handle) == "Infeasible"
    assert adapter.load_results(handle.run_dir).status == "Infeasible"


@pytest.mark.parametrize("page", ["overview", "inputs", "parameters", "results", "compare", "help"])
def test_pages_render_without_exceptions(page):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "gui" / "app.py"), default_timeout=120)
    at.run()
    at.switch_page(f"pages/{page}.py")
    at.run()
    assert not at.exception, [e.message for e in at.exception]
