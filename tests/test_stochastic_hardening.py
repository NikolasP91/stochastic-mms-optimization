"""Regression tests for the implementation review and reliable run artifacts."""
import json
from pathlib import Path
from types import SimpleNamespace

import pulp as pl
import pytest

from mms.stochastic.artifacts import canonical_hash, write_json
from mms.stochastic.data import load
from mms.stochastic.evaluation import evaluate_out_of_sample
from mms.stochastic.model import audit_model, build_model, empirical_cvar, solve
from stochastic_main import main

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def small():
    return load(ROOT / "examples/small_stochastic.json")


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf")])
def test_audit_rejects_missing_or_nonfinite_solution(bad):
    problem = pl.LpProblem("audit", pl.LpMinimize)
    x = pl.LpVariable("x", 0, 10)
    problem += x
    problem += x <= 5
    x.varValue = bad
    assert not audit_model(SimpleNamespace(problem=problem))["passed"]


def test_cvar_keeps_tiny_probability_tails():
    alpha = 1 - 1e-14
    probability = 1e-15
    expected = (100 * probability + 10 * ((1 - alpha) - probability)) / (1 - alpha)
    assert empirical_cvar([(10, 1 - probability), (100, probability)], alpha) == pytest.approx(expected)


@pytest.mark.parametrize("alpha", [0, 1, float("nan"), True])
def test_cvar_rejects_invalid_alpha(alpha):
    with pytest.raises(ValueError):
        empirical_cvar([(1, 1)], alpha)


def test_evaluation_requires_complete_fixed_schedule(small):
    with pytest.raises(ValueError, match="complete"):
        evaluate_out_of_sample(small, {"state_1_1": 1}, small["stochastic"]["scenarios"])


def test_unused_slack_cap_rejected(small):
    small["stochastic"]["slack_policy"]["caps"]["s_load_minus_999_"] = 1
    with pytest.raises(ValueError):
        build_model(small)


def test_report_distinguishes_operational_shortfalls():
    result = solve(load(ROOT / "examples/small_storage_cvar.json"))
    assert result["validation"]["passed"]
    assert result["operational_status"] == "degraded"
    assert any(note["code"] == "NONZERO_SLACKS" for note in result["model_notes"])
    assert len(result["run_metadata"]["input_sha256"]) == 64
    assert result["run_metadata"]["source_files"]
    assert result["validation"]["objective_reconciliation_residual_eur"] < 1e-5


def test_atomic_json_preserves_previous_file_on_serialization_failure(tmp_path):
    target = tmp_path / "result.json"
    write_json(target, {"previous": True})
    with pytest.raises(ValueError):
        write_json(target, {"invalid": float("nan")})
    assert json.loads(target.read_text()) == {"previous": True}


def test_cli_validation_and_missing_input(tmp_path, capsys):
    output = tmp_path / "result.json"
    assert main([str(ROOT / "examples/small_stochastic.json"), "--validate-only", "-o", str(output)]) == 0
    assert "no optimization" in capsys.readouterr().out
    assert not output.exists()
    assert main([str(tmp_path / "missing.json"), "-o", str(output)]) == 2
    assert not output.exists()
    assert json.loads(output.with_suffix(".error.json").read_text())["status"] == "FileError"


def test_cli_never_overwrites_input(tmp_path, small):
    target = tmp_path / "input.json"
    write_json(target, small)
    before = target.read_bytes()
    assert main([str(target), "-o", str(target)]) == 2
    assert target.read_bytes() == before


def test_cli_saves_reproducible_artifacts(tmp_path):
    output = tmp_path / "result.json"
    assert main([str(ROOT / "examples/small_stochastic.json"), "-o", str(output)]) == 0
    result = json.loads(output.read_text())
    artifacts = Path(result["artifact_directory"])
    manifest = json.loads((artifacts / "manifest.json").read_text())
    assert manifest["status"] == "Completed"
    assert manifest["result_sha256"] == canonical_hash(result)
    assert manifest["input_sha256"] == canonical_hash(json.loads((artifacts / "input.json").read_text()))


def test_no_operational_state_cannot_supply_reserves(small):
    for state in small["Generating_Units"][2]["operating-states"]:
        state["isOperational"] = False
    model = build_model(small)
    model.problem += model.shared["primary_ActPR_plus3_1"] >= 1
    model.problem.solve(pl.HiGHS(msg=False, threads=1))
    assert model.problem.status == pl.LpStatusInfeasible


def test_failed_rerun_preserves_completed_artifacts(tmp_path, monkeypatch):
    from mms.stochastic.errors import OptimizationError
    import stochastic_main

    output = tmp_path / "result.json"
    args = [str(ROOT / "examples/small_stochastic.json"), "-o", str(output)]
    assert main(args) == 0
    before = output.read_bytes()
    completed = Path(json.loads(before)["artifact_directory"])
    snapshot = (completed / "input.json").read_bytes()

    def fail(*args, **kwargs):
        raise OptimizationError("Time limit", status="Not Solved", solver="highs")

    monkeypatch.setattr(stochastic_main, "solve", fail)
    assert main(args) == 2
    assert output.read_bytes() == before
    assert (completed / "input.json").read_bytes() == snapshot
    manifests = [json.loads(p.read_text()) for p in (tmp_path / "result_artifacts").glob("*/manifest.json")]
    assert sorted(m["status"] for m in manifests) == ["Completed", "Failed"]


def test_fixed_schedule_keys_must_be_strings(small):
    with pytest.raises(ValueError, match="keys"):
        build_model(small, {1: 0, "unknown": 0}, require_complete_first_stage=True)


def test_evaluation_validates_training_input(small):
    scenarios = small["stochastic"]["scenarios"]
    small["stochastic"]["scenarios"] = None
    with pytest.raises(ValueError):
        evaluate_out_of_sample(small, {}, scenarios)


@pytest.mark.parametrize("time_limit", [0, -1, float("inf"), True])
def test_solver_rejects_invalid_time_limit(small, time_limit):
    with pytest.raises(ValueError):
        solve(small, time_limit=time_limit)
