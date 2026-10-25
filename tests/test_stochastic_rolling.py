"""Observed handover must preserve operating rules and all binding decisions."""

from copy import deepcopy
from pathlib import Path

import pytest

from mms.stochastic.data import load
from mms.stochastic.model import solve
from mms.stochastic.rolling import advance


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def small():
    return load(ROOT / "examples/small_stochastic.json")


def observed(data, state=0, steps=1):
    return {"units": {str(g["gen_id"]): [
        {"power_mw": 0, "operating_state_id": state} for _ in range(steps)
    ] for g in data["Generating_Units"]}}


def handover(data, observations=None, refreshed=None, **kwargs):
    return advance(data, {"common_schedule": {}}, observations or observed(data),
                   refreshed or data, **kwargs)[0]


@pytest.mark.parametrize("change", [
    lambda d: d["Generating_Units"][0]["operating-state-transitions"][0]["transitions"].clear(),
    lambda d: d["Generating_Units"][0]["state-transitions"][0]["transitions"].update({"min-transition-time": 180}),
    lambda d: d["Generating_Units"][0]["operating-states"][1].update({"max-power": 11}),
    lambda d: d["Generating_Units"][0].update(comments="Therm: different unit category"),
    lambda d: d.setdefault("optimization_parameters", {}).update(time_resolution={"subperiod_operating_state_policy": "period_rounding"}),
])
def test_changed_operating_rules_require_migration(small, change):
    refreshed = deepcopy(small)
    change(refreshed)
    with pytest.raises(ValueError, match="migration"):
        handover(small, refreshed=refreshed)


@pytest.mark.parametrize("replacement", [{}, {"0": {"hours": 5, "elapsed_hours": 0}}])
def test_maximum_on_cannot_be_silently_removed_or_changed(small, replacement):
    small["stochastic"]["maximum_on"] = {"0": {"hours": 6, "elapsed_hours": 0}}
    refreshed = deepcopy(small)
    refreshed["stochastic"]["maximum_on"] = replacement
    with pytest.raises(ValueError, match="maximum_on"):
        handover(small, refreshed=refreshed)


@pytest.mark.parametrize("field,value", [
    ("operating_state_id", True), ("operating_state_id", 0.0),
    ("operating_state_id", 999), ("power_mw", True),
    ("power_mw", float("nan")), ("power_mw", float("inf")),
])
def test_observations_reject_invalid_ids_and_nonfinite_power(small, field, value):
    observations = observed(small)
    observations["units"]["0"][0][field] = value
    with pytest.raises(ValueError):
        handover(small, observations)


def test_observation_cannot_use_forbidden_transition(small):
    small["Generating_Units"][0]["operating-state-transitions"][0]["transitions"] = []
    with pytest.raises(ValueError, match="observed transition 0 -> 1"):
        handover(small, observed(small, state=1))


@pytest.mark.parametrize("field", ["executed_steps", "committed_steps"])
def test_boolean_period_counts_are_rejected(small, field):
    with pytest.raises(ValueError, match=field):
        handover(small, **{field: True})


def test_explicit_remaining_maximum_survives_repeated_rolls(small):
    small["stochastic"]["initial_operating_obligations"] = {
        "0": {"state_id": 0, "maximum_remaining_hours": 2}}
    data = small
    for remaining in (1, 0, 0):
        data = handover(data, refreshed=small)
        assert data["stochastic"]["initial_operating_obligations"]["0"]["maximum_remaining_hours"] == remaining
    data = handover(data, observed(data, state=1), refreshed=small)
    assert "0" not in data["stochastic"]["initial_operating_obligations"]


def test_multi_hour_and_repeated_handover_carry_same_obligations(small):
    small["stochastic"]["maximum_on"] = {"0": {"hours": 8, "elapsed_hours": 0}}
    arc = small["Generating_Units"][0]["operating-state-transitions"][0]["transitions"][0]
    arc.update({"min-transition-time_b": 180, "max-transition-time_b": 240})
    batch = handover(small, observed(small, state=1, steps=3), executed_steps=3)
    repeated = small
    for _ in range(3):
        repeated = handover(repeated, observed(repeated, state=1), refreshed=small)
    assert batch["Generating_Units"] == repeated["Generating_Units"]
    assert batch["stochastic"]["maximum_on"] == repeated["stochastic"]["maximum_on"]
    assert batch["stochastic"]["initial_operating_obligations"] == repeated["stochastic"]["initial_operating_obligations"]
    assert batch["stochastic"]["initial_operating_obligations"]["0"]["maximum_remaining_hours"] == 1


def test_unlimited_maximum_is_not_converted_to_integer(small):
    arc = small["Generating_Units"][0]["operating-state-transitions"][0]["transitions"][0]
    arc["max-transition-time_b"] = 100000000000
    data = handover(small, observed(small, state=1))
    assert "0" not in data["stochastic"]["initial_operating_obligations"]


def test_transient_embedding_preserves_destination_dwell_obligations(small):
    unit = small["Generating_Units"][0]
    transient = deepcopy(unit["operating-states"][0])
    transient.update(id=2, isEnabled=False, isShutdown=False, isTransient=True,
                     **{"min-time-enabled": 10, "max-time-enabled": 20})
    unit["operating-states"].append(transient)
    unit["operating-state-transitions"] = [
        {"from": 0, "transitions": [{"id": 2, "min-transition-time_b": 10}]},
        {"from": 2, "transitions": [{"id": 1, "min-transition-time_b": 180,
                                      "max-transition-time_b": 240}]},
        {"from": 1, "transitions": [{"id": 0}]},
    ]
    data = handover(small, observed(small, state=1))
    carried = data["Generating_Units"][0]["operating-state-transitions"][1]["transitions"][0]
    assert carried["min-transition-time-left_b"] == 120
    assert carried["max-transition-time-left_b"] == 180
    assert data["stochastic"]["initial_operating_obligations"]["0"]["maximum_remaining_hours"] == 3


def test_legacy_state_timer_metadata_is_decremented(small):
    small["stochastic"]["slack_policy"] = {"mode": "legacy"}
    initial = small["Generating_Units"][0]["operating-states"][0]
    initial.update({"min-time-enabled-left": 120, "max-time-enabled-left": 180})
    data = handover(small)
    state = data["Generating_Units"][0]["operating-states"][0]
    assert state["min-time-enabled-left"] == 60
    assert state["max-time-enabled-left"] == 120


def test_partial_schedule_cannot_release_binding_commitments(small):
    result = solve(small)
    # One removed reserve decision previously vanished silently from fixed.
    result["common_schedule"].pop("primary_ActPR_plus1_2")
    with pytest.raises(ValueError, match="Committed prefix must be complete"):
        advance(small, result, observed(small), small, committed_steps=1)


def test_handover_does_not_mutate_inputs(small):
    before = deepcopy(small)
    observations = observed(small, state=1)
    observed_before = deepcopy(observations)
    handover(small, observations)
    assert small == before
    assert observations == observed_before
