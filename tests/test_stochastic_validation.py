"""Reject unsafe or ambiguous stochastic inputs before invoking a solver."""

from copy import deepcopy
import json
from pathlib import Path
import re

import pytest

from mms.stochastic.data import load, validate


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def data():
    return load(ROOT / "examples/small_storage_cvar.json")


def replace(data, path, value):
    parent = data
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value


@pytest.mark.parametrize("path,value,location", [
    (("stochastic", "risk", "wieght"), 0.5, "stochastic.risk"),
    (("stochastic", "reserve_lnik"), True, "stochastic"),
    (("stochastic", "reserve_products", "primray"), {}, "stochastic.reserve_products"),
    (("stochastic", "reserve_products", "primary", "response_minute"), 5, "reserve_products.primary"),
    (("stochastic", "storage", 0, "charge_effiency"), 0.8, "stochastic.storage[0]"),
    (("stochastic", "slack_policy", "cap"), {}, "stochastic.slack_policy"),
    (("stochastic", "maximum_on"), {"0": {"hours": 4, "elapsed_hours": 0, "hour": 2}}, "maximum_on.0"),
    (("stochastic", "initial_operating_obligations"), {"0": {"state_id": 0, "maximum_remaining_hours": 1, "remaining": 1}}, "initial_operating_obligations.0"),
])
def test_typos_never_silently_change_the_model(data, path, value, location):
    replace(data, path, value)
    with pytest.raises(ValueError, match=re.escape(location) + ".*unknown field"):
        validate(data)


@pytest.mark.parametrize("path,value,location", [
    (("stochastic",), [], "stochastic"),
    (("stochastic", "scenarios"), {}, "stochastic.scenarios"),
    (("stochastic", "scenarios", 0), None, "stochastic.scenarios[0]"),
    (("stochastic", "scenarios", 0, "renewables_mw"), [], "renewables_mw"),
    (("stochastic", "risk"), None, "stochastic.risk"),
    (("stochastic", "slack_policy"), [], "stochastic.slack_policy"),
    (("stochastic", "slack_policy", "caps"), [], "slack_policy.caps"),
    (("stochastic", "reserve_products", "primary"), None, "reserve_products.primary"),
    (("stochastic", "storage"), {}, "stochastic.storage"),
    (("stochastic", "storage", 0), None, "stochastic.storage[0]"),
    (("stochastic", "maximum_on"), [], "stochastic.maximum_on"),
    (("Generating_Units", 0), [], "Generating_Units[0]"),
    (("Generating_Units", 0, "operating-state-transitions", 0, "transitions"), {}, "operating-state-transitions[0].transitions"),
    (("constraints",), [], "constraints"),
])
def test_malformed_containers_raise_value_error_with_path(data, path, value, location):
    replace(data, path, value)
    with pytest.raises(ValueError, match=re.escape(location)):
        validate(data)


@pytest.mark.parametrize("path,location", [
    (("stochastic", "scenarios", 0, "id"), "stochastic.scenarios[0]"),
    (("stochastic", "scenarios", 0, "load_mw"), "stochastic.scenarios[0]"),
    (("stochastic", "storage", 0, "capacity_mwh"), "stochastic.storage[0]"),
    (("stochastic", "storage", 0, "renewable_gen_id"), "renewable_gen_id"),
    (("stochastic", "reserve_products", "primary", "response_minutes"), "reserve_products.primary"),
    (("Generating_Units", 0, "state-transitions"), "state-transitions"),
    (("Generating_Units", 0, "operating-state-transitions", 0, "from"), "operating-state-transitions[0]"),
])
def test_missing_fields_fail_before_any_key_error(data, path, location):
    parent = data
    for key in path[:-1]:
        parent = parent[key]
    del parent[path[-1]]
    with pytest.raises(ValueError, match=re.escape(location)):
        validate(data)


@pytest.mark.parametrize("path,value,location", [
    (("stochastic", "reserve_link"), "false", "reserve_link"),
    (("stochastic", "risk", "weight"), True, "risk.weight"),
    (("stochastic", "scenarios", 0, "probability"), True, "probability"),
    (("stochastic", "storage", 0, "grid_charge"), 1, "grid_charge"),
    (("stochastic", "storage", 0, "renewable_gen_id"), 2.0, "renewable_gen_id"),
    (("Generating_Units", 0, "gen_id"), False, "gen_id"),
    (("Generating_Units", 0, "state"), False, "state"),
    (("Generating_Units", 0, "operating-states", 1, "id"), True, "id"),
    (("Generating_Units", 0, "availability", 0), True, "availability"),
    (("constraints", "load_production_balance_constraint"), "false", "load_production_balance_constraint"),
    (("stochastic", "maximum_on"), {"0": {"hours": 3.0, "elapsed_hours": 0}}, "maximum_on.0.hours"),
    (("stochastic", "initial_operating_obligations"), {"0": {"state_id": 0, "maximum_remaining_hours": 0.0}}, "maximum_remaining_hours"),
])
def test_booleans_and_float_ids_do_not_masquerade_as_numbers(data, path, value, location):
    replace(data, path, value)
    with pytest.raises(ValueError, match=re.escape(location)):
        validate(data)


@pytest.mark.parametrize("path", [
    ("stochastic", "risk", "weight"),
    ("stochastic", "scenarios", 0, "load_mw", 0),
    ("stochastic", "storage", 0, "capacity_mwh"),
    ("Generating_Units", 0, "ramp_up_rate(kW/min)"),
    ("Generating_Units", 0, "operating-states", 1, "max-power"),
    ("Load_forecast", 0),
    ("Cost_parameters", "x_load"),
])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_input_is_rejected_in_legacy_and_new_fields(data, path, value):
    replace(data, path, value)
    with pytest.raises(ValueError, match="finite number"):
        validate(data)


@pytest.mark.parametrize("path,value,location", [
    (("stochastic", "scenarios", 0, "id"), " ", ".id"),
    (("stochastic", "scenarios", 0, "probability"), 1.1, "probability"),
    (("stochastic", "scenarios", 0, "probability"), 0.2, "sum to 1"),
    (("stochastic", "scenarios", 0, "load_mw"), [1], "load_mw"),
    (("stochastic", "scenarios", 0, "renewables_mw", "2", 0), 7, "physical availability"),
    (("Generating_Units", 2, "Production_Forecast", 0), 7, "Production_Forecast"),
    (("stochastic", "storage", 0, "initial_mwh"), 10, "energy bounds"),
    (("stochastic", "storage", 0, "discharge_efficiency"), 0, "efficiency"),
    (("stochastic", "storage", 0, "renewable_gen_id"), 0, "renewable unit"),
    (("stochastic", "maximum_on"), {"0": {"hours": 3, "elapsed_hours": 1}}, "offline"),
    (("stochastic", "maximum_on"), {"0": {"hours": 3, "elapsed_hours": 4}}, "maximum ON"),
    (("stochastic", "initial_operating_obligations"), {"0": {"state_id": 1, "maximum_remaining_hours": 0}}, "initial operating state"),
    (("Generating_Units", 0, "operating-state-transitions", 0, "transitions", 0, "id"), 99, "destination state"),
    (("Generating_Units", 0, "operating-state-transitions", 0, "from"), 99, "source state"),
    (("Generating_Units", 0, "operating-states", 0, "max-power"), 1, "shutdown state"),
    (("Generating_Units", 0, "operating-states", 1, "max-power"), 99, "maximum power"),
    (("Generating_Units", 0, "current_Power(MW)"), 1, "initial operating state"),
])
def test_inconsistent_physical_and_history_data_fail_fast(data, path, value, location):
    replace(data, path, value)
    with pytest.raises(ValueError, match=re.escape(location)):
        validate(data)


def test_duplicate_scenarios_and_storage_links_are_rejected(data):
    data["stochastic"]["scenarios"][1]["id"] = data["stochastic"]["scenarios"][0]["id"]
    with pytest.raises(ValueError, match="duplicate scenario"):
        validate(data)
    data["stochastic"]["scenarios"][1]["id"] = "unique"
    duplicate = deepcopy(data["stochastic"]["storage"][0])
    duplicate["id"] = "second_store"
    data["stochastic"]["storage"].append(duplicate)
    with pytest.raises(ValueError, match="at most one"):
        validate(data)


def test_invalid_reserve_settings_rejected_even_when_link_is_disabled(data):
    data["stochastic"]["reserve_link"] = False
    data["stochastic"]["reserve_products"]["primary"]["response_minutes"] = 0
    with pytest.raises(ValueError, match="response_minutes"):
        validate(data)


def test_enabled_reserve_link_requires_settings_for_active_product(data):
    del data["stochastic"]["reserve_products"]["primary"]
    with pytest.raises(ValueError, match="reserve_products.primary"):
        validate(data)


@pytest.mark.parametrize("field,value", [
    ("min-time-enabled", 120), ("min-time-enabled-left", 60),
    ("max-time-enabled", 120), ("max-time-enabled-left", 0),
])
def test_unimplemented_state_timers_are_never_silently_ignored(data, field, value):
    data["Generating_Units"][0]["operating-states"][1][field] = value
    with pytest.raises(ValueError, match="state-level dwell limits are not enforced"):
        validate(data)
    data["stochastic"]["slack_policy"] = {"mode": "legacy"}
    validate(data)


def test_supported_transient_embedding_may_use_state_timers(data):
    unit = data["Generating_Units"][0]
    transient = deepcopy(unit["operating-states"][1])
    transient.update(id=2, isOperational=False, isTransient=True)
    transient["min-time-enabled"] = 15
    unit["operating-states"].append(transient)
    unit["operating-state-transitions"][0]["transitions"][0]["id"] = 2
    unit["operating-state-transitions"].append({"from": 2, "transitions": [{"id": 1, "transition-cost": 0}]})
    before = deepcopy(data)
    validate(data)
    assert data == before
    data["optimization_parameters"]["time_resolution"]["subperiod_operating_state_policy"] = "period_rounding"
    with pytest.raises(ValueError, match="state-level dwell limits are not enforced"):
        validate(data)


def test_legacy_regression_exemption_is_explicit():
    data = load(ROOT / "examples/original_single_scenario.json")
    data["stochastic"]["slack_policy"] = {"mode": "bounded"}
    with pytest.raises(ValueError, match="physical availability"):
        validate(data)


def test_legacy_mode_does_not_accept_ignored_caps(data):
    data["stochastic"]["slack_policy"]["mode"] = "legacy"
    with pytest.raises(ValueError, match="caps are ignored"):
        validate(data)


def test_validation_preserves_valid_input_and_rejects_nonstandard_json(tmp_path, data):
    before = deepcopy(data)
    assert validate(data) is data
    assert data == before
    data["stochastic"]["risk"]["weight"] = float("nan")
    file = tmp_path / "invalid.json"
    file.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="stochastic.risk.weight.*finite number"):
        load(file)
