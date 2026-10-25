"""Schema/validator agreement and the original 24-hour one-scenario regression."""

import json
from pathlib import Path

import pytest

from mms.stochastic import data as stochastic_data
from mms.stochastic.data import load
from mms.stochastic.model import solve

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/stochastic_extension.schema.json").read_text(encoding="utf-8"))
EXAMPLES = ["small_stochastic", "small_storage_cvar", "small_tree_bess", "original_single_scenario"]


@pytest.mark.parametrize("name", EXAMPLES)
def test_examples_satisfy_schema(name):
    jsonschema = pytest.importorskip("jsonschema")
    section = json.loads((ROOT / f"examples/{name}.json").read_text(encoding="utf-8"))["stochastic"]
    jsonschema.validate(section, SCHEMA)


def test_schema_fields_match_runtime_validator():
    assert set(SCHEMA["properties"]) == stochastic_data.CONFIG_FIELDS
    storage = SCHEMA["$defs"]["storage"]
    assert set(storage["properties"]) == stochastic_data.STORAGE_FIELDS
    assert set(storage["required"]) == stochastic_data.STORAGE_REQUIRED
    product = SCHEMA["$defs"]["product"]
    assert set(product["properties"]) == stochastic_data.PRODUCT_FIELDS | stochastic_data.PRODUCT_OPTIONAL
    assert set(SCHEMA["properties"]["cost_policy"]["properties"]) == stochastic_data.COST_POLICY_FIELDS
    assert set(SCHEMA["$defs"]["storageReserve"]["properties"]) == stochastic_data.STORAGE_RESERVE_FIELDS


def test_original_fixture_one_scenario_regression():
    # Codex's documented equivalence: same size and objective as the deterministic kernel.
    result = solve(load(ROOT / "examples/original_single_scenario.json"))
    assert result["num_variables"] == 5191
    assert result["num_constraints"] == 12032
    assert result["expected_cost_eur"] == pytest.approx(382562.14962105, abs=1e-3)
